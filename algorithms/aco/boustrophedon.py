# -*- coding: utf-8 -*-
"""子问题 2：凸子区域内部牛耕式（往复扫描）覆盖路径生成。

- 计算多边形各边对应的高度，取最大高度对应边为最优飞行方向；
- 按航线间距生成平行扫描线，与多边形求交得到覆盖条带；
- 蛇形连接各条带，输出 4 种等效方案（内部距离、转弯次数一致，
  仅进出点不同：4 个角落 × 起止方向）。
"""
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from shapely.geometry import Polygon, LineString, MultiLineString, GeometryCollection

XY = Tuple[float, float]


@dataclass
class RegionCoverPlan:
    """单个凸子区域的一种内部覆盖方案。"""
    path: List[XY]                 # 内部航点（entry=path[0], exit=path[-1]）
    entry: XY
    exit: XY
    internal_distance: float
    turns: int
    variant_id: int = 0            # 0..3

    def to_dict(self):
        return {
            "path": self.path, "entry": self.entry, "exit": self.exit,
            "internal_distance": round(self.internal_distance, 3),
            "turns": self.turns, "variant_id": self.variant_id,
        }


def _unit(v) -> np.ndarray:
    n = np.hypot(v[0], v[1])
    if n < 1e-12:
        return np.array([1.0, 0.0])
    return np.array([v[0] / n, v[1] / n])


def _polygon_height(pts: List[XY], edge_dir) -> float:
    """多边形在垂直于 edge_dir 方向上的高度（最大投影跨度）。"""
    d = _unit(edge_dir)
    normal = np.array([-d[1], d[0]])
    base = np.array(pts[0])
    proj = [(np.array(p) - base) @ normal for p in pts]
    return float(max(proj) - min(proj))


def choose_sweep_direction(pts: List[XY]) -> np.ndarray:
    """选择最优飞行方向：最大高度对应边的方向（论文方法）。

    对每条边计算垂直于该边的多边形高度，取高度最大的那条边，
    飞行方向平行于该边。
    """
    n = len(pts)
    best_dir = np.array([1.0, 0.0])
    best_h = -1.0
    for i in range(n):
        a = np.array(pts[i])
        b = np.array(pts[(i + 1) % n])
        edge = b - a
        if np.hypot(*edge) < 1e-12:
            continue
        h = _polygon_height(pts, edge)
        if h > best_h:
            best_h = h
            best_dir = _unit(edge)
    return best_dir


def _strip_segments(poly_pts: List[XY], sweep_dir, line_spacing: float
                    ) -> List[Tuple[XY, XY]]:
    """生成与 sweep_dir 垂直、间距 line_spacing 的扫描线，返回各条带线段。"""
    if line_spacing <= 1e-9:
        raise ValueError("航线间距必须大于 0（请检查相机参数与旁向重叠率）")
    poly = Polygon(poly_pts)
    pts = np.array(poly_pts)
    d = _unit(sweep_dir)
    normal = np.array([-d[1], d[0]])
    proj = pts @ normal
    tmin, tmax = float(proj.min()), float(proj.max())
    span = tmax - tmin
    n_strips = max(1, int(math.floor(span / line_spacing)))
    if span - n_strips * line_spacing > 1e-9:
        n_strips += 1

    # 扫描线覆盖长度（取包围盒对角线，保证直线完全穿越多边形）
    L = float(np.hypot(pts[:, 0].max() - pts[:, 0].min(),
                       pts[:, 1].max() - pts[:, 1].min())) + line_spacing * 2

    strips = []
    for k in range(n_strips):
        t = tmin + line_spacing * (k + 0.5)
        center = np.array(poly_pts[0]) + normal * (t - (np.array(poly_pts[0]) @ normal))
        a = center - d * L
        b = center + d * L
        inter = poly.intersection(LineString([tuple(a), tuple(b)]))
        seg = _longest_segment(inter)
        if seg is None:
            continue
        strips.append(seg)
    return strips


def _longest_segment(geom):
    """从交点几何中取最长的 LineString 段。"""
    geoms = []
    if geom.is_empty:
        return None
    if geom.geom_type == "LineString":
        geoms = [geom]
    elif geom.geom_type == "MultiLineString":
        geoms = list(geom.geoms)
    elif geom.geom_type in ("GeometryCollection",):
        for g in geom.geoms:
            if g.geom_type == "LineString":
                geoms.append(g)
            elif g.geom_type == "MultiLineString":
                geoms.extend(g.geoms)
    if not geoms:
        return None
    geoms.sort(key=lambda g: g.length, reverse=True)
    best = geoms[0]
    coords = list(best.coords)
    if len(coords) < 2:
        return None
    return (tuple(coords[0]), tuple(coords[-1]))


def plan_region_variants(poly_pts: List[XY], line_spacing: float,
                         sweep_dir: Optional[np.ndarray] = None,
                         ) -> List[RegionCoverPlan]:
    """生成一个凸子区域的 4 种牛耕式覆盖方案。

    :param poly_pts: 凸多边形顶点（CCW）
    :param line_spacing: 航线间距 (m)
    :param sweep_dir: 指定扫描方向（None 则按最大高度边自动选择）
    :return: 4 个 RegionCoverPlan
    """
    if sweep_dir is None:
        sweep_dir = choose_sweep_direction(poly_pts)
    d = _unit(sweep_dir)
    strips = _strip_segments(poly_pts, d, line_spacing)
    if not strips:
        raise ValueError("多边形与扫描线无交集，无法生成覆盖路径")

    # 按垂直于扫描线的方向排序条带
    normal = np.array([-d[1], d[0]])
    strips.sort(key=lambda s: (np.array(s[0]) @ normal + np.array(s[1]) @ normal) / 2.0)

    def build(order, flip_first):
        """按条带顺序与首段方向生成蛇形路径。

        每条带都追加 (entry, exit) 两个点；相邻条带之间的连接线
        由上一条的 exit 指向下一条的 entry 自动形成（同端垂直连接，
        而不是斜穿整个条带宽度）。
        """
        path = []
        segs = list(strips)
        if order == "desc":
            segs = list(reversed(segs))
        for idx, (a, b) in enumerate(segs):
            if (idx % 2 == 0) != flip_first:
                a, b = b, a
            path.append(a)
            path.append(b)
        dist = _seg_len(path)
        return path, dist

    variants = []
    for vid, (order, flip) in enumerate([("asc", False), ("asc", True),
                                         ("desc", False), ("desc", True)]):
        path, dist = build(order, flip)
        if len(path) < 2:
            continue
        variants.append(RegionCoverPlan(
            path=path, entry=path[0], exit=path[-1],
            internal_distance=dist, turns=max(0, len(strips) - 1),
            variant_id=vid))
    return variants


def _seg_len(pts) -> float:
    """计算折线总长度（含扫描线 + 条带间连接线）。"""
    total = 0.0
    for i in range(len(pts) - 1):
        total += math.hypot(pts[i + 1][0] - pts[i][0],
                            pts[i + 1][1] - pts[i][1])
    return total
