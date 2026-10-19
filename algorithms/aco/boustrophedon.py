# -*- coding: utf-8 -*-
"""子问题 2：凸子区域内部牛耕式（往复扫描）覆盖路径生成。

- 对每条边的最大高度取最小值，航线平行于对应支撑边；
- 按航线间距生成平行扫描线，与多边形求交得到覆盖条带；
- 先统一交线段端点方向，再交替连接；四变体里程分别计算。
- 航段覆盖整个条带内的纵向范围，避免只截中心交线导致尖角漏扫。
  条带端点可能在区域外；论文假定无禁飞区，此几何补全在结果中明确记录。
"""
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union
from algorithms.aco.polygon_decomp import clean_ring, ensure_ccw, reflex_indices

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
    scan_segments: List[Tuple[XY, XY]] = field(default_factory=list)

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
    """选择最优飞行方向（论文 Algorithm 1 / subproblem 2）。

    对每条边计算顶点到该边的最大距离（=多边形在垂直于该边方向的
    投影高度），取该距离**最小**的那条边。飞行方向平行于这条支撑边，使牛耕扫描线数量最少、内部转弯次数最少
    （与 Fig.6 矩形沿长边横扫一致）。
    """
    n = len(pts)
    best_dir = np.array([1.0, 0.0])
    best_h = float("inf")
    for i in range(n):
        a = np.array(pts[i])
        b = np.array(pts[(i + 1) % n])
        edge = b - a
        if np.hypot(*edge) < 1e-12:
            continue
        h = _polygon_height(pts, edge)
        if h < best_h:
            best_h = h
            best_dir = _unit(edge)
    return best_dir


def _strip_segments(poly_pts: List[XY], sweep_dir, line_spacing: float, boundary_mode='envelope'
                    ) -> List[Tuple[XY, XY]]:
    """等间距、居中的扫描线；用每条带的投影包络确定航段长度。

    每个条带宽度不超过 spacing，条带内任意点到其航段的法向距离
    不超过 spacing/2。由此连续拍摄宽度 >= spacing 时覆盖完整区域。
    """
    if boundary_mode not in ('inside', 'envelope'):
        raise ValueError('未知扫描边界模式')
    if not math.isfinite(line_spacing) or line_spacing <= 1e-9:
        raise ValueError("航线间距必须大于 0（请检查相机参数与旁向重叠率）")
    poly_pts = ensure_ccw(clean_ring(poly_pts))
    poly = Polygon(poly_pts)
    if not poly.is_valid or poly.area <= 1e-12 or reflex_indices(poly_pts):
        raise ValueError("牛耕扫描要求有效、非退化的凸多边形，请先完成凸分解")
    # 平移到局部原点，降低 UTM 大坐标造成的投影误差。
    origin = np.asarray(poly_pts[0], dtype=float)
    pts = np.asarray(poly_pts, dtype=float) - origin
    d = _unit(sweep_dir)
    normal = np.array([-d[1], d[0]])
    proj = pts @ normal
    tmin, tmax = float(proj.min()), float(proj.max())
    span = tmax - tmin
    n_strips = max(1, int(math.ceil(span / line_spacing - 1e-12)))
    if n_strips > 100000:
        raise ValueError("扫描条带超过 100000，请检查单位、航高和重叠率")
    start = (tmin + tmax - (n_strips - 1) * line_spacing) / 2.0
    us = pts @ d
    umin, umax = float(us.min()), float(us.max())
    local_poly = Polygon(np.column_stack((us, proj)))
    strips = []
    for k in range(n_strips):
        t = start + k * line_spacing
        lo, hi = max(tmin, t-line_spacing/2), min(tmax, t+line_spacing/2)
        band = Polygon([(umin-1, lo), (umax+1, lo),
                        (umax+1, hi), (umin-1, hi)])
        clipped = local_poly.intersection(band)
        if clipped.is_empty or clipped.area <= 0:
            raise RuntimeError("扫描条带退化，未生成完整覆盖方案")
        if boundary_mode == 'inside':
            segment = _longest_segment(local_poly.intersection(LineString([(umin-1, t), (umax+1, t)])))
            if segment is None:
                raise RuntimeError('子区内扫描线退化，请检查几何与航线间距')
            left, right = sorted((segment[0][0], segment[1][0]))
        else:
            left, _, right, _ = clipped.bounds
        a = origin + d * left + normal * t
        b = origin + d * right + normal * t
        strips.append((tuple(a), tuple(b)))
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
                         boundary_joints: bool = False,
                         boundary_mode: str = 'envelope',
                         ) -> List[RegionCoverPlan]:
    """生成一个凸子区域的 4 种牛耕式覆盖方案。

    :param poly_pts: 凸多边形顶点（CCW）
    :param line_spacing: 航线间距 (m)
    :param sweep_dir: 指定扫描方向（None 则按最小宽度支撑边自动选择）
    :return: 4 个 RegionCoverPlan
    """
    if sweep_dir is None:
        sweep_dir = choose_sweep_direction(poly_pts)
    d = _unit(sweep_dir)
    strips = _strip_segments(poly_pts, d, line_spacing, boundary_mode)
    if not strips:
        raise ValueError("多边形与扫描线无交集，无法生成覆盖路径")

    # 按垂直于扫描线的方向排序条带
    normal = np.array([-d[1], d[0]])
    strips.sort(key=lambda s: (np.array(s[0]) @ normal + np.array(s[1]) @ normal) / 2.0)

    def build(order, flip_first):
        """按条带顺序与首段方向生成蛇形路径。

        每条带都追加 (entry, exit) 两个点；相邻条带之间的连接线
        端点已按扫描方向投影升序统一，因此行号奇偶翻转始终可靠。
        非矩形边界的同侧连接可以倾斜，不能假定全部连接都垂直。
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
        if boundary_joints:
            # Li Eq.29/30：两条宽度支撑线各有1或2个边界连接点。
            # 显式连接实际扫描航段，不把理论连接点与执行端点混为一谈。
            points = np.asarray(poly_pts, dtype=float)
            local = points-points[0]
            heights = local @ normal
            tolerance = max(1e-8, float(np.ptp(heights))*1e-10)
            low = points[np.abs(heights-heights.min()) <= tolerance]
            high = points[np.abs(heights-heights.max()) <= tolerance]
            first_support, last_support = (low, high) if order == "asc" else (high, low)
            first_forward = np.dot(np.subtract(path[1], path[0]), d) > 0
            last_forward = np.dot(np.subtract(path[-1], path[-2]), d) > 0
            entry = first_support[np.argmin(first_support @ d) if first_forward else np.argmax(first_support @ d)]
            exit = last_support[np.argmax(last_support @ d) if last_forward else np.argmin(last_support @ d)]
            path = [tuple(entry)] + path + [tuple(exit)]
            dist = _seg_len(path)
        if len(path) < 2:
            continue
        variants.append(RegionCoverPlan(
            path=path, entry=path[0], exit=path[-1],
            internal_distance=dist, turns=max(0, len(strips) - 1),
            variant_id=vid, scan_segments=list(strips)))
    return variants


def coverage_geometry(plan: RegionCoverPlan, direction, footprint_width: float,
                      footprint_height: float):
    """固定航向、垂直相机连续拍摄的足迹并集，仅计算扫描航段。

    不把转运航段拍摄计入覆盖保证。离散拍照还要求触发间距 <= 足迹长度，
    触发器/曝光时间不属于本平台航点文件的执行语义。
    """
    if min(footprint_width, footprint_height) <= 0:
        raise ValueError("相机足迹必须为正数")
    d = _unit(direction)
    normal = np.array([-d[1], d[0]])
    hw, hh = footprint_width/2.0, footprint_height/2.0
    swept = []
    for a, b in plan.scan_segments:
        a, b = np.asarray(a)-d*hh, np.asarray(b)+d*hh
        swept.append(Polygon([a-normal*hw, b-normal*hw,
                              b+normal*hw, a+normal*hw]))
    return unary_union(swept)


def _seg_len(pts) -> float:
    """计算折线总长度（含扫描线 + 条带间连接线）。"""
    total = 0.0
    for i in range(len(pts) - 1):
        total += math.hypot(pts[i + 1][0] - pts[i][0],
                            pts[i + 1][1] - pts[i][1])
    return total
