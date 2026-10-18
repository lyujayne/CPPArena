# -*- coding: utf-8 -*-
"""Wu 2025 PSO凸分解：每凹点一个切割角，以可行分割的最小宽度和为目标。
按Eq.4限制单次切割的凸性可行角锥；按Eq.13/14更新粒子。
原文未公开射线切割、角度约束求解和分割阶段预算，相关实现取值单独报告。
默认不热启动、不做碎片后处理；最终不可行则报错，不静默补切输出。"""
import math
from typing import Dict, List, Optional, Tuple

import numpy as np
from shapely.geometry import Polygon as _ShPolygon

from algorithms.aco.polygon_decomp import (
    EPS,
    XY,
    clean_ring,
    ensure_ccw,
    is_convex_ring,
    reflex_indices,
    signed_area,
)

# 残差凹点（粒子角度未满足凸性约束、需补切）的大罚值
RESIDUAL_PENALTY = 1.0e5
# 无法完成切割的不可行解罚值
INFEASIBLE_PENALTY = 1.0e9


# ================================================================ 凹点切割角上下界
def _angle(dx: float, dy: float) -> float:
    """方位角，归一化到 [0, 2π)。"""
    a = math.atan2(dy, dx)
    return a + 2.0 * math.pi if a < 0 else a


def reflex_wedge_bounds(pts: List[XY], i: int) -> Tuple[float, float]:
    """CCW 环上凹点 i 的内部楔形角区间 (lo, hi)（lo < hi，跨度 ∈ (π, 2π]）。

    下界/上界即凹点两条邻边（指向相邻顶点）相对 x 轴的方位角（论文 Fig.6
    的 d_min / d_max）；内部楔形是多边形内部所在的那个大扇形（凹点内角 >π）。
    """
    n = len(pts)
    v = pts[i]
    a_prev = _angle(pts[(i - 1) % n][0] - v[0], pts[(i - 1) % n][1] - v[1])
    a_next = _angle(pts[(i + 1) % n][0] - v[0], pts[(i + 1) % n][1] - v[1])
    # CCW 凹点：内部扇形从"指向下一顶点的边"逆时针转到"指向上一顶点的边"
    lo, hi = a_next, a_prev
    while hi <= lo:
        hi += 2.0 * math.pi
    if hi - lo < math.pi - EPS:
        # 兜底：取互补的大扇形（正常 CCW 凹点不会进入此分支）
        lo, hi = hi, lo + 2.0 * math.pi
    return lo, hi


# ================================================================ 射线求交与切分
def _ray_cast(poly: List[XY], origin: XY, angle: float
              ) -> Optional[Tuple[float, XY, int]]:
    """从 origin 沿 angle 方向投射射线，返回与 poly 边界的最近交点。

    :return: (参数 t, 交点 Q, 被击中的边索引 j)；无交点返回 None。
    """
    dx, dy = math.cos(angle), math.sin(angle)
    ox, oy = origin
    best: Optional[Tuple[float, XY, int]] = None
    n = len(poly)
    for j in range(n):
        a = poly[j]
        b = poly[(j + 1) % n]
        # 跳过与凹点相连的两条邻边（t=0 自交）
        if (abs(a[0] - ox) < EPS and abs(a[1] - oy) < EPS) or \
           (abs(b[0] - ox) < EPS and abs(b[1] - oy) < EPS):
            continue
        ex, ey = b[0] - a[0], b[1] - a[1]
        denom = dx * ey - dy * ex          # cross(d, e)
        if abs(denom) < 1e-15:
            continue
        ax, ay = a[0] - ox, a[1] - oy
        t = (ax * ey - ay * ex) / denom    # cross(a-V, e)/cross(d, e)
        u = (ax * dy - ay * dx) / denom    # cross(a-V, d)/cross(d, e)
        if t > 1e-7 and -1e-9 <= u <= 1.0 + 1e-9:
            u = min(1.0, max(0.0, u))
            q = (a[0] + u * ex, a[1] + u * ey)
            if best is None or t < best[0]:
                best = (t, q, j)
    return best


def _find_vertex(poly: List[XY], v: XY) -> int:
    """在环中按坐标查找顶点索引，找不到返回 -1。"""
    for k, p in enumerate(poly):
        if abs(p[0] - v[0]) < 1e-7 and abs(p[1] - v[1]) < 1e-7:
            return k
    return -1


def _cut_piece(poly: List[XY], i: int, angle: float
               ) -> Optional[Tuple[List[XY], List[XY]]]:
    """沿凹点 i、方向 angle 的射线把 CCW 环切成两个 CCW 子环。

    击中边 j（v_j→v_{j+1}）于 Q 时：
      环 A = v_i, v_{i+1}, …, v_j, Q
      环 B = v_i, Q, v_{j+1}, …, v_{i-1}
    """
    hit = _ray_cast(poly, poly[i], angle)
    if hit is None:
        return None
    _, q, j = hit
    n = len(poly)
    ring_a: List[XY] = []
    k = i
    while True:
        ring_a.append(poly[k])
        if k == j:
            break
        k = (k + 1) % n
    ring_a.append(q)
    ring_b: List[XY] = [poly[i], q]
    k = (j + 1) % n
    while k != i:
        ring_b.append(poly[k])
        k = (k + 1) % n
    try:
        ring_a = ensure_ccw(clean_ring(ring_a))
        ring_b = ensure_ccw(clean_ring(ring_b))
    except ValueError:
        return None
    if len(ring_a) < 3 or len(ring_b) < 3 or \
            abs(signed_area(ring_a)) < 1e-9 or abs(signed_area(ring_b)) < 1e-9:
        return None
    return ring_a, ring_b


# ================================================================ 旋转卡壳宽度
def rotating_calipers_width(pts: List[XY]) -> float:
    """凸环 O(n) 对跖点旋转卡壳宽度；凹的递归中间片先取凸包。"""
    return rotating_calipers_width_dir(pts)[0]


def rotating_calipers_width_dir(pts: List[XY]) -> Tuple[float, float]:
    """凸多边形（最小宽度, 宽度方向）。

    宽度方向即取得最小宽度时支撑线（平行于对应边）的方位角，也就是牛耕
    扫描航线方向。用于论文 §4.5 判定两个子区“宽度方向相同”。
    :return: (width, direction)，direction ∈ [0, 2π)，为无向直线方向
    """
    pts = ensure_ccw(clean_ring(pts))
    if reflex_indices(pts):
        hull = _ShPolygon(pts).convex_hull
        pts = list(hull.exterior.coords[:-1])
        pts = ensure_ccw(pts)
    n = len(pts)
    best = float("inf")
    best_dir = 0.0
    def cross_distance(i, k):
        a, b, q = pts[i], pts[(i+1) % n], pts[k % n]
        return abs((b[0]-a[0])*(q[1]-a[1])-(b[1]-a[1])*(q[0]-a[0]))
    # 初始对跖点先扫描一次；不能从相邻点开始，否则首边多个共线
    # 顶点造成等值平台时会停在距离0处。
    j = max(range(n), key=lambda k: cross_distance(0, k))
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        ln = math.hypot(ex, ey)
        if ln < 1e-15:
            continue
        # 对跖点沿边顺序单调前进，所有边合计不超过两圈。
        while cross_distance(i, j+1) > cross_distance(i, j) + 1e-12:
            j = (j+1) % n
        w = cross_distance(i, j) / ln
        if w < best:
            best = w
            best_dir = math.atan2(ey, ex)
    if not math.isfinite(best) or best <= 1e-12:
        raise ValueError("多边形宽度退化，无法分解或扫描")
    return float(best), float(best_dir % math.pi)


# ================================================================ 施加一组切割角
def apply_directed_cuts(vertices: List[XY],
                        angles: List[float],
                        reflex_idx: List[int]
                        ) -> Tuple[Optional[List[List[XY]]], int, int]:
    """按各凹点的切割方向角依次切割，返回 (子片列表, 补切数, 越界夹取数)。

    切割后若仍残留凹点（粒子角度不满足凸性约束），用凹角平分线补切至全凸。
    射线无法求交等几何失败时返回 (None, 0, 越界数)。
    """
    ring = ensure_ccw(clean_ring(vertices))
    reflex_pts = [ring[i] for i in reflex_idx]
    pieces: List[List[XY]] = [ring]
    n_clamp = 0

    for v, ang in zip(reflex_pts, angles):
        # 找到仍以 v 为凹点的子片（前序切割可能已把该凹点消解）
        target = None
        for pidx, p in enumerate(pieces):
            li = _find_vertex(p, v)
            if li >= 0 and li in reflex_indices(p):
                target = (pidx, p, li)
                break
        if target is None:
            continue
        pidx, piece, li = target
        lo, hi = reflex_wedge_bounds(piece, li)
        # 角度归一化到该楔形的等价区间内
        a = ang
        while a < lo - EPS:
            a += 2.0 * math.pi
        while a > hi + EPS:
            a -= 2.0 * math.pi
        if a < lo or a > hi:
            a = min(hi, max(lo, a))
            n_clamp += 1
        cut = _cut_piece(piece, li, a)
        if cut is None:
            return None, 0, n_clamp
        a_ring, b_ring = cut
        pieces.pop(pidx)
        pieces.append(a_ring)
        pieces.append(b_ring)

    # 凸性约束(Eq.4)兜底：残留凹点用内角平分线补切
    n_extra = 0
    work = list(pieces)
    result: List[List[XY]] = []
    guard = 0
    while work:
        guard += 1
        if guard > 10000:
            return None, n_extra, n_clamp
        p = work.pop()
        rid = reflex_indices(p)
        if not rid:
            result.append(p)
            continue
        i = rid[0]
        lo, hi = reflex_wedge_bounds(p, i)
        cut = _cut_piece(p, i, (lo + hi) / 2.0)
        if cut is None:
            return None, n_extra, n_clamp
        n_extra += 1
        work.extend(cut)
    return result, n_extra, n_clamp


def bisector_decompose(vertices: List[XY], max_pieces: int = 256
                       ) -> Optional[List[List[XY]]]:
    """确定性凹角平分线凸分解（可行解热启动与最终兜底）。

    平分线把凹点内角 α∈(π,2π) 分为两个 α/2∈(π/2,π) 的角，凹点在两个
    子片中同时变为凸点；不产生新凹点，故必在有限步内终止且全部为凸。
    """
    ring = ensure_ccw(clean_ring(vertices))
    if not reflex_indices(ring):
        return [ring]
    work = [ring]
    result: List[List[XY]] = []
    while work:
        p = work.pop()
        rid = reflex_indices(p)
        if not rid:
            result.append(p)
            continue
        if len(result) + len(work) + 2 > max_pieces:
            result.append(p)
            continue
        i = rid[0]
        lo, hi = reflex_wedge_bounds(p, i)
        cut = _cut_piece(p, i, (lo + hi) / 2.0)
        if cut is None:
            return None
        work.extend(cut)
    return [ensure_ccw(p) for p in result]


# ================================================================ 退化碎块合并
def merge_slivers(pieces: List[List[XY]], min_width: float,
                  min_area: float) -> Tuple[List[List[XY]], int]:
    """合并近退化碎块（宽度/面积低于阈值，如切割线擦过顶点产生的针尖三角）。

    碎块与其共享边界最长的邻片求并：并为凸多边形则直接替换；若并后非凸，
    用内角平分线重新凸分解。合并不改变覆盖范围（并集面积守恒），仅消除
    无法容纳扫描航线的退化子区，保证下游牛耕路径一定可生成。
    :return: (合并后的子片列表, 合并掉的碎块数)
    """
    pieces = [list(p) for p in pieces]
    merged_count = 0
    guard = 0
    while guard < 10000:
        guard += 1
        si = None
        for k, p in enumerate(pieces):
            if rotating_calipers_width(p) < min_width or abs(signed_area(p)) < min_area:
                si = k
                break
        if si is None:
            break
        sliver = pieces[si]
        gs = _ShPolygon(sliver).buffer(0)
        # 找共享边界最长的邻片
        best_j, best_shared = None, 0.0
        for j, p in enumerate(pieces):
            if j == si:
                continue
            shared = gs.boundary.intersection(_ShPolygon(p).buffer(0).boundary).length
            if shared > best_shared:
                best_shared, best_j = shared, j
        if best_j is None:
            break  # 找不到邻片（理论上不会发生），保留该块
        union = gs.union(_ShPolygon(pieces[best_j]).buffer(0))
        if union.geom_type != "Polygon":
            break
        ring = ensure_ccw(clean_ring([(float(x), float(y))
                                      for x, y in union.exterior.coords[:-1]]))
        # 从列表中移除碎块与邻片
        others = [p for k, p in enumerate(pieces) if k not in (si, best_j)]
        if not reflex_indices(ring):
            others.append(ring)
        else:
            re_parts = bisector_decompose(ring)
            if re_parts is None:
                break
            others.extend(re_parts)
        pieces = others
        merged_count += 1
    return [ensure_ccw(p) for p in pieces], merged_count


# ================================================================ 适应度
def _evaluate(vertices: List[XY], angles: List[float],
              reflex_idx: List[int]) -> Tuple[float, Optional[List[List[XY]]], int, int]:
    """论文 Eq.8 适应度：可行时为 Σ 旋转卡壳宽度；不可行施加大罚值。"""
    pieces, n_extra, n_clamp = apply_directed_cuts(vertices, angles, reflex_idx)
    if pieces is None:
        return INFEASIBLE_PENALTY, None, 0, n_clamp
    width_sum = 0.0
    for p in pieces:
        w = rotating_calipers_width(p)
        if not math.isfinite(w):
            return INFEASIBLE_PENALTY, None, n_extra, n_clamp
        width_sum += w
    # Eq.8 是可行域内的宽度和；修复结果不冒充该粒子原角度的可行解。
    if n_extra or n_clamp:
        return INFEASIBLE_PENALTY + width_sum, pieces, n_extra, n_clamp
    return width_sum, pieces, n_extra, n_clamp


# ================================================================ PSO 主流程（Algorithm 2）
def pso_convex_decompose(vertices: List[XY], params: Optional[Dict] = None,
                         seed: int = 42
                         ) -> Tuple[List[List[XY]], Dict]:
    """论文 PSO 动态凹区域分割（Algorithm 2）。

    :param vertices: 任意凹/凸多边形顶点（米制坐标，闭合与否均可）
    :param params: pso_swarm_size / pso_iterations / pso_w_max / pso_w_min /
                   pso_c1 / pso_c2
    :param seed: 随机种子（保证可复现）
    :return: (凸子区域 CCW 环列表, 优化信息字典)
    """
    params = params or {}
    swarm = int(params.get("pso_swarm_size", 40))
    max_iter = int(params.get("pso_iterations", 120))
    w_max = float(params.get("pso_w_max", 0.9))     # 论文 Table 1
    w_min = float(params.get("pso_w_min", 0.2))     # 论文 Table 1
    c1 = float(params.get("pso_c1", 2.0))           # 论文 Table 1
    c2 = float(params.get("pso_c2", 2.0))           # 论文 Table 1
    vmax_ratio = float(params.get("pso_vmax_ratio", 0.15))
    warm_start = int(bool(params.get("pso_warm_start", 0)))
    do_merge = int(bool(params.get("pso_merge_slivers", 0)))
    sliver_ratio = float(params.get("pso_sliver_diag_ratio", 0.001))
    if swarm < 1 or max_iter < 0 or min(w_max, w_min, c1, c2, vmax_ratio, sliver_ratio) < 0 or w_min > w_max:
        raise ValueError("PSO种群必须为正、迭代非负，惯性/学习/速度界参数无效")

    ring = ensure_ccw(clean_ring(vertices))
    reflex_idx = reflex_indices(ring)
    n_ref = len(reflex_idx)

    # 凸多边形：无需分割
    if n_ref == 0:
        w = rotating_calipers_width(ring)
        return [ring], {
            "segmentation": "PSO-DCAS",
            "n_reflex": 0, "n_subregions": 1,
            "width_sum": round(w, 4), "widths": [round(w, 4)],
            "pso_iterations": 0, "swarm_size": swarm,
            "best_iteration": 0, "n_extra_cuts": 0, "feasible": True,
            "pso_convergence": [round(w, 4)], "cut_angles": [],
        }

    rng = np.random.RandomState(seed)
    bounds = [reflex_wedge_bounds(ring, i) for i in reflex_idx]
    # Eq.4 凸性约束：一次切割两侧角度均 <= pi 的可行锥。
    # 论文未给出该约束的数值处理，这里限制定义域而不对结果补切。
    lo = np.array([b-math.pi for a, b in bounds])
    hi = np.array([a+math.pi for a, b in bounds])
    span = hi - lo
    vmax = vmax_ratio * span

    # ---- Step 3-4：初始种群（warm_start=1 时第 0 号粒子为凹角平分线可行解）----
    bisect = (lo + hi) / 2.0
    positions = rng.uniform(lo, hi, size=(max(1, swarm), n_ref))
    if warm_start:
        positions[0] = bisect
    velocities = rng.uniform(-vmax, vmax, size=positions.shape)

    # 初值（Eq.8）
    fits = np.array([_evaluate(ring, list(positions[k]), reflex_idx)[0]
                     for k in range(positions.shape[0])])
    pbest = positions.copy()
    pbest_fit = fits.copy()
    g_idx = int(np.argmin(pbest_fit))
    gbest = pbest[g_idx].copy()
    gbest_fit = float(pbest_fit[g_idx])
    # 原文没给出可行种群生成细节；随机种群全不可行时明确报错，
    # 允许显式启用平分线初值，而不是静默换分割方法。
    best_iter = 0
    convergence = [gbest_fit]

    # ---- Step 5-6：Eq.13 / Eq.14 速度位置更新 ----
    for it in range(max_iter):
        w = w_max - (w_max - w_min) * (it / max(1, max_iter - 1))
        r1 = rng.uniform(0.0, 1.0, size=positions.shape)
        r2 = rng.uniform(0.0, 1.0, size=positions.shape)
        velocities = (w * velocities
                      + c1 * r1 * (pbest - positions)
                      + c2 * r2 * (gbest - positions))
        velocities = np.clip(velocities, -vmax, vmax)
        positions = positions + velocities
        positions = np.clip(positions, lo, hi)

        fits = np.array([_evaluate(ring, list(positions[k]), reflex_idx)[0]
                         for k in range(positions.shape[0])])
        improved = fits < pbest_fit
        pbest[improved] = positions[improved]
        pbest_fit[improved] = fits[improved]
        gi = int(np.argmin(pbest_fit))
        if pbest_fit[gi] < gbest_fit - 1e-9:
            gbest_fit = float(pbest_fit[gi])
            gbest = pbest[gi].copy()
            best_iter = it + 1
        convergence.append(gbest_fit)

    # ---- 用 gbest 角度组执行最终分割 ----
    pieces, n_extra, n_clamp = apply_directed_cuts(ring, list(gbest), reflex_idx)
    if pieces is None or n_extra or n_clamp:
        raise RuntimeError("PSO 未找到满足 Eq.4–8 的原角度可行分割；请增大种群/迭代，"
                           "或显式启用 pso_warm_start=1（工程可行初值）")

    # ---- 后处理：合并切割线擦过顶点/近共线边产生的退化碎块（可关闭）----
    n_merged = 0
    if do_merge:
        diag = math.hypot(max(p[0] for p in ring) - min(p[0] for p in ring),
                          max(p[1] for p in ring) - min(p[1] for p in ring))
        min_width = sliver_ratio * diag      # 宽度小于对角线该比例者视为碎块
        min_area = 0.5 * min_width ** 2
        pieces, n_merged = merge_slivers(pieces, min_width, min_area)

    widths = [rotating_calipers_width(p) for p in pieces]
    info = {
        "segmentation": "PSO-DCAS",
        "n_reflex": n_ref,
        "n_subregions": len(pieces),
        "width_sum": round(float(sum(widths)), 4),
        "widths": [round(float(x), 4) for x in widths],
        "pso_iterations": max_iter,
        "fitness_evaluations": positions.shape[0] * (max_iter + 1),
        "swarm_size": positions.shape[0],
        "best_iteration": best_iter,
        "n_extra_cuts": n_extra,
        "n_merged_slivers": n_merged,
        "n_angle_clamps": n_clamp,
        "feasible": n_extra == 0,
        "pso_convergence": [round(float(c), 4) for c in convergence],
        "cut_angles": [round(float(a), 6) for a in gbest],
    }
    return [ensure_ccw(p) for p in pieces], info
