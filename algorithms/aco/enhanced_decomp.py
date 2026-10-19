# -*- coding: utf-8 -*-
"""Li 2011 §4增强精确单元分解。

枚举凹点及边平行的可行切割，贪心选择两片宽度和最小者递归，
按§4.5合并同宽度方向且完全相邻的凸片。凸环宽度用O(n)对跖点卡壳；
凹的递归中间片先取凸包。无法执行规定切割或达到上限时明确报错，
不自动改用平分线，不输出凹片或遗失尚未处理的区域。
"""
import math
from core.execution_control import checkpoint
from typing import Dict, List, Optional, Tuple

from shapely.geometry import Polygon as _ShPolygon

from algorithms.aco.polygon_decomp import (
    EPS,
    XY,
    clean_ring,
    ensure_ccw,
    reflex_indices,
)
from algorithms.aco.pso_decomp import (
    _cut_piece,
    reflex_wedge_bounds,
    rotating_calipers_width,
    rotating_calipers_width_dir,
)


# ================================================================ 角度工具
def _normalize_into(angle: float, base: float) -> float:
    """把 angle 归一化到 [base, base + 2π)。"""
    while angle < base - EPS:
        angle += 2.0 * math.pi
    while angle >= base + 2.0 * math.pi - EPS:
        angle -= 2.0 * math.pi
    return angle


def _valid_cut_angle(poly: List[XY], i: int, edge_dir: float
                     ) -> Optional[float]:
    """过凹顶点 i、方向平行于某边（edge_dir 为该边方位角）时，返回有效射线角。

    凹点内部楔形为 (lo, hi)（跨度 α>π，见 reflex_wedge_bounds）。能把凹角
    分成两个均 ≤π 的角的"有效切割锥"为 [hi−π, lo+π]（跨度 2π−α<π）。
    直线的两条反向射线 edge_dir / edge_dir+π 中至多一条落入该锥，返回之；
    都不落入则返回 None（该边方向不能一次消解此凹点）。

    锥边界（方向恰为某条邻边反向延长线）同样有效：此时切出的一个角恰为 π
    （共线，非凹），正对应论文 Fig.7 的类型 (A)"凹顶点一条邻边的延长线"，
    也是轴对齐多边形最常见的最优切割，故边界纳入（取闭区间）并把近边界方向
    吸附到精确边界，避免数值抖动。
    """
    lo, hi = reflex_wedge_bounds(poly, i)
    cone_lo, cone_hi = hi - math.pi, lo + math.pi
    for ray in (edge_dir, edge_dir + math.pi):
        r = _normalize_into(ray, lo)
        if cone_lo - EPS <= r <= cone_hi + EPS:
            # 近边界吸附到精确边界（等价某邻边的反向延长方向）
            if abs(r - cone_lo) <= EPS:
                return cone_lo
            if abs(r - cone_hi) <= EPS:
                return cone_hi
            return r
    return None


# ================================================================ 单步最优切割
def _best_cut(poly: List[XY]
              ) -> Tuple[Optional[int], Optional[float], Optional[float], list]:
    """枚举 (凹顶点 i, 边 j)，返回使宽度和最小的切割方案。

    严格对应论文 Fig.8 的内层双重循环（i=1..ncc, j=1..n）：
      过凹顶点 i 作边 j 的平行线 → 切成 P1、P2 → 计算 D_ij = w(P1)+w(P2)，
      记录最小 D_ij 及其切割角。
    :return: (凹顶点索引 i, 有效切割角 θ, 最小宽度和, 切割记录列表)；
             无任何有效边平行切割时 i 为 None。
    """
    n = len(poly)
    reflex = reflex_indices(poly)
    best_i: Optional[int] = None
    best_angle: Optional[float] = None
    best_sum = float("inf")
    records: list = []

    for i in reflex:
        checkpoint("增强区域分割")
        lo, hi = reflex_wedge_bounds(poly, i)
        for j in range(n):
            ex = poly[(j + 1) % n][0] - poly[j][0]
            ey = poly[(j + 1) % n][1] - poly[j][1]
            if math.hypot(ex, ey) < 1e-15:
                continue
            theta = _valid_cut_angle(poly, i, math.atan2(ey, ex))
            if theta is None:
                continue
            cut = _cut_piece(poly, i, theta)
            if cut is None:
                continue
            ring_a, ring_b = cut
            d_ij = rotating_calipers_width(ring_a) + \
                rotating_calipers_width(ring_b)
            records.append({
                "reflex": i, "parallel_edge": j,
                "cut_angle": round(float(theta), 6), "width_sum": round(d_ij, 4),
            })
            if d_ij < best_sum - 1e-9:
                best_sum, best_i, best_angle = d_ij, i, theta
    return best_i, best_angle, (best_sum if best_i is not None else None), records


# ================================================================ §4.5 子区域合并
def _direction_key(angle: float) -> float:
    """把无向直线方向归一化到 [0, π)（θ 与 θ+π 视为同一方向）。"""
    t = angle % math.pi
    return t + math.pi if t < 0 else t


def _same_direction(a: float, b: float, tol: float = 1e-6) -> bool:
    """论文 §4.5：两个子区宽度方向（扫描方向）是否相同（平行）。"""
    delta = abs(_direction_key(a) - _direction_key(b))
    return min(delta, math.pi-delta) <= tol


def _vertex_index(poly: List[XY], point: XY, tol: float = 1e-7) -> int:
    """在环中按坐标（容差）查找顶点索引，找不到返回 -1。"""
    for k, p in enumerate(poly):
        if abs(p[0] - point[0]) <= tol and abs(p[1] - point[1]) <= tol:
            return k
    return -1


def _find_shared_full_edge(poly_a: List[XY], poly_b: List[XY]
                           ) -> Optional[Tuple[XY, XY]]:
    """若两片共享一条“完整边”，返回其端点；否则 None。

    完全相邻（Definition 4）：片 A 的一条边的两个端点，在片 B 中也互为
    相邻顶点（顺序可相反）。这区别于仅部分边重合。
    """
    na, nb = len(poly_a), len(poly_b)
    for ia in range(na):
        p, q = poly_a[ia], poly_a[(ia + 1) % na]
        jp = _vertex_index(poly_b, p)
        jq = _vertex_index(poly_b, q)
        if jp < 0 or jq < 0:
            continue
        if (jq == (jp + 1) % nb) or (jp == (jq + 1) % nb):
            return (p, q)
    return None


def _union_convex(poly_a: List[XY], poly_b: List[XY]) -> Optional[List[XY]]:
    """两片沿共享边求并，返回凸外环；并后非凸或几何失败返回 None。"""
    union = _ShPolygon(poly_a).buffer(0).union(_ShPolygon(poly_b).buffer(0))
    if union.geom_type != "Polygon":
        return None
    ring = ensure_ccw(clean_ring(
        [(float(x), float(y)) for x, y in union.exterior.coords[:-1]]))
    if reflex_indices(ring):
        return None
    return ring


def combine_subregions(pieces: List[List[XY]]
                       ) -> Tuple[List[List[XY]], int, List[dict]]:
    """论文 §4.5 子区域合并。

    反复扫描子区对，凡同时满足 ① 共享一条完整边（完全相邻）；
    ② 宽度方向相同；③ 合并后仍为凸 者即合并，直到无可合并对。
    :return: (合并后的凸子区列表, 合并次数, 合并记录)
    """
    pieces = [ensure_ccw(p) for p in pieces]
    dirs = [rotating_calipers_width_dir(p)[1] for p in pieces]
    records: List[dict] = []
    n_merged = 0
    while True:
        pair = None
        for a in range(len(pieces)):
            for b in range(a + 1, len(pieces)):
                edge = _find_shared_full_edge(pieces[a], pieces[b])
                if edge is None:
                    continue
                if not _same_direction(dirs[a], dirs[b]):
                    continue
                newpoly = _union_convex(pieces[a], pieces[b])
                if newpoly is None:
                    continue
                pair = (a, b, newpoly)
                break
            if pair is not None:
                break
        if pair is None:
            break
        a, b, newpoly = pair
        lo, hi = sorted((a, b))
        pieces.pop(hi)
        pieces.pop(lo)
        dirs.pop(hi)
        dirs.pop(lo)
        pieces.append(newpoly)
        dirs.append(rotating_calipers_width_dir(newpoly)[1])
        n_merged += 1
        records.append({"merged_indices": [a, b],
                        "n_vertices": len(newpoly)})
    return pieces, n_merged, records


# ================================================================ 贪心递归主流程
def enhanced_convex_decompose(vertices: List[XY],
                              params: Optional[Dict] = None,
                              max_pieces: int = 256
                              ) -> Tuple[List[List[XY]], Dict]:
    """论文增强精确单元分解（§4.3 贪心递归最小宽度和）。

    :param vertices: 任意凹/凸多边形顶点（米制坐标，闭合与否均可）
    :param params: 预留（论文该分解无额外可调参数）
    :param max_pieces: 结果数量安全上限（超限时报错，不输出部分结果）
    :return: (凸子区域 CCW 环列表, 优化信息字典)
    """
    ring = ensure_ccw(clean_ring(vertices))
    n_reflex_total = len(reflex_indices(ring))

    # 凸多边形：无需分割
    if n_reflex_total == 0:
        w = rotating_calipers_width(ring)
        return [ring], {
            "segmentation": "Enhanced-ECD(Li2011)",
            "n_reflex": 0, "n_subregions": 1,
            "width_sum": round(w, 4), "widths": [round(w, 4)],
            "n_bisector_fallback": 0, "n_cuts": 0,
            "chosen_cuts": [], "feasible": True,
        }

    result: List[List[XY]] = []
    chosen_cuts: List[Dict] = []
    n_bisector = 0
    work: List[List[XY]] = [ring]
    depth_guard = 0

    while work:
        depth_guard += 1
        if depth_guard > 10000:
            raise RuntimeError("Enhanced-ECD 达到切割次数上限，未输出不完整分割")
        poly = work.pop()
        reflex = reflex_indices(poly)
        if not reflex:
            result.append(poly)
            continue
        if len(result) + len(work) + 2 > max_pieces:
            raise RuntimeError("Enhanced-ECD 超过子区数量上限，请提高 max_pieces")

        i, theta, best_sum, records = _best_cut(poly)

        if i is not None and theta is not None:
            # 论文 Fig.8：在 D_ij 最小处把多边形切成 P1、P2
            cut = _cut_piece(poly, i, theta)
            if cut is None:
                # 理论上不会发生（_best_cut 已成功切过），保险起见走平分线
                i, theta = reflex[0], None
            else:
                # 记录本步实际采用的切割（从 records 中取最小宽度和者）
                rec = min(records, key=lambda r: r["width_sum"])
                chosen_cuts.append(rec)
                work.extend(cut)
                continue

        raise RuntimeError("Enhanced-ECD 没有成功执行论文规定的边平行切割；"
                           "请检查退化顶点或几何精度，不自动换成平分线算法")

    pieces = [ensure_ccw(p) for p in result]
    # §4.5：合并“宽度方向相同且完全相邻”的子区域，消除不必要的分割
    pieces, n_combined, combine_records = combine_subregions(pieces)
    widths = [rotating_calipers_width(p) for p in pieces]
    info = {
        "segmentation": "Enhanced-ECD(Li2011)",
        "n_reflex": n_reflex_total,
        "n_subregions": len(pieces),
        "width_sum": round(float(sum(widths)), 4),
        "widths": [round(float(x), 4) for x in widths],
        "n_bisector_fallback": n_bisector,
        "n_cuts": len(chosen_cuts),
        "chosen_cuts": chosen_cuts,
        "n_combined_subregions": n_combined,
        "combined_records": combine_records,
        "feasible": n_bisector == 0,
    }
    return pieces, info
