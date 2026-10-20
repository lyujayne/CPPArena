"""Additional convex partitions. Adaptation scope is returned with every result.

All geometry is translated/scaled before construction to protect UTM coordinates.
No convex hull may replace the task boundary, and no positive-area cell is dropped.
"""
import math
from functools import lru_cache

import numpy as np
from shapely import affinity, set_precision
from shapely.geometry import Polygon, LineString, Point, box
from shapely.geometry.polygon import orient
from shapely.ops import split, unary_union

from core.execution_control import checkpoint


def _ring(poly):
    return list(orient(poly, sign=1).exterior.coords[:-1])


def _convex(poly):
    return (poly.geom_type == 'Polygon' and not poly.interiors and poly.is_valid
            and poly.area > 0 and poly.convex_hull.area - poly.area <= max(1e-13, poly.area*1e-10))


def _polygons(geometry):
    if geometry.geom_type == 'Polygon':
        return [geometry] if geometry.area > 0 else []
    return [p for item in getattr(geometry, 'geoms', ()) for p in _polygons(item)]


def _clean(poly):
    pts = _ring(poly)
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for i, b in enumerate(pts):
            a, c = pts[i-1], pts[(i+1) % len(pts)]
            cross = (b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])
            if abs(cross) <= 1e-13 and (b[0]-a[0])*(c[0]-b[0])+(b[1]-a[1])*(c[1]-b[1]) >= 0:
                pts.pop(i)
                changed = True
                break
    return Polygon(pts)


def _prepare(vertices):
    original = Polygon(vertices)
    if not original.is_valid or original.area <= 0 or original.interiors:
        raise ValueError('分割输入须为无孔、无自交且面积为正的简单多边形')
    x0, y0, x1, y1 = original.bounds
    scale = max(x1-x0, y1-y0)
    local = affinity.scale(affinity.translate(original, -x0, -y0), 1/scale, 1/scale, origin=(0, 0))
    return original, _clean(local), (x0, y0, scale)


def _finish(parts, original, transform, info):
    x0, y0, scale = transform
    restored = [affinity.translate(affinity.scale(p, scale, scale, origin=(0, 0)), x0, y0) for p in parts]
    union = unary_union(restored)
    tol = max(1e-6, original.area*1e-9)
    if (not restored or any(not _convex(p) for p in parts)
            or any(not p.is_valid or p.area <= 0 for p in restored)
            or union.symmetric_difference(original).area > tol
            or sum(p.area for p in restored)-union.area > tol):
        raise RuntimeError('新增分割算法未满足凸性、原区域完整覆盖及无重叠约束')
    return [_ring(p) for p in restored], dict(info, n_cells=len(parts))


def _td(poly, angle):
    rotated = affinity.rotate(poly, -angle, origin=(0, 0))
    xs = sorted(set(x for x, _ in rotated.exterior.coords[:-1]))
    _, ymin, _, ymax = rotated.bounds
    cells = []
    for a, b in zip(xs, xs[1:]):
        checkpoint('TD 梯形扫描分解')
        cells.extend(_polygons(rotated.intersection(box(a, ymin-1, b, ymax+1))))
    return [affinity.rotate(p, angle, origin=(0, 0)) for p in cells]


def _triangulate(poly):
    """Ear clipping, using only the polygon's vertices (unconstrained Delaunay is unsuitable)."""
    pts = _ring(_clean(poly))
    triangles = []
    while len(pts) > 3:
        checkpoint('HM 耳切三角剖分')
        for i, b in enumerate(pts):
            a, c = pts[i-1], pts[(i+1) % len(pts)]
            cross = (b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])
            if cross <= 1e-14:
                continue
            triangle = Polygon([a, b, c])
            others = [p for j, p in enumerate(pts) if j not in {i, (i-1) % len(pts), (i+1) % len(pts)}]
            if any(triangle.covers(Point(p)) for p in others) or not poly.covers(triangle):
                continue
            triangles.append(triangle)
            pts.pop(i)
            break
        else:
            raise RuntimeError('耳切剖分失败，请检查极短边或接近重合的顶点')
    triangles.append(Polygon(pts))
    return triangles


def _hm(poly):
    parts = _triangulate(poly)
    while True:
        checkpoint('HM 删除非必要内部对角线')
        choices = []
        for i, a in enumerate(parts):
            for j in range(i+1, len(parts)):
                b = parts[j]
                common = a.boundary.intersection(b.boundary).length
                if common <= 1e-12:
                    continue
                merged = a.union(b)
                if _convex(merged):
                    choices.append((-common, i, j, _clean(merged)))
        if not choices:
            return parts
        _, i, j, merged = min(choices, key=lambda v: v[:3])
        parts[i] = merged
        parts.pop(j)


def _iee_cells(poly):
    """Extend the supporting lines of the two incident edges at each reflex vertex.

    This is an arrangement variant of IEE, not a claimed reproduction of one paper.
    Extending through the whole polygon can create extra candidate cells.
    """
    pts = _ring(poly)
    cells = [poly]
    for i, b in enumerate(pts):
        a, c = pts[i-1], pts[(i+1) % len(pts)]
        if (b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]) >= -1e-13:
            continue
        for other in (a, c):
            checkpoint('IEE 凹顶点邻边延伸')
            dx, dy = b[0]-other[0], b[1]-other[1]
            length = math.hypot(dx, dy)
            dx, dy = dx/length*4, dy/length*4
            cutter = LineString([(b[0]-dx, b[1]-dy), (b[0]+dx, b[1]+dy)])
            # Repeated supporting lines otherwise manufacture roundoff slivers
            # that collapse after translation back to UTM. Snap at 1e-12 of
            # the task extent; final area/overlap checks still use the original.
            cells = [part for cell in cells
                     for part in _polygons(set_precision(split(cell, cutter), 1e-12))]
    # All reflex incident supporting lines should resolve reflex angles. Refuse
    # unexpected non-convex output rather than silently substitute Bayazit.
    if any(not _convex(p) for p in cells):
        raise RuntimeError('IEE 延伸单元仍存在凹角，无法执行凸合并')
    return cells


def _merge_candidates(cells, max_size, max_candidates):
    """Connected convex unions; every atomic cell remains an available candidate."""
    n = len(cells)
    adjacency = [{j for j in range(n) if i != j and cells[i].boundary.intersection(cells[j].boundary).length > 1e-12}
                 for i in range(n)]
    candidates = {1 << i: p for i, p in enumerate(cells)}
    layer = list(candidates)
    truncated = False
    for size in range(2, min(max_size, n)+1):
        new = []
        seen = set()
        for mask in layer:
            checkpoint('生成整数规划凸合并候选')
            neighbors = set().union(*(adjacency[i] for i in range(n) if mask >> i & 1))
            for j in sorted(neighbors):
                key = mask | (1 << j)
                if key == mask or key in candidates or key in seen:
                    continue
                seen.add(key)
                merged = candidates[mask].union(cells[j])
                if _convex(merged):
                    if len(candidates) >= max_candidates:
                        return candidates, True
                    candidates[key] = _clean(merged)
                    new.append(key)
        layer = new
        if not layer:
            break
    if max_size < n:
        truncated = True  # size-limited candidate family, not global optimality
    return candidates, truncated


def _milp_merge(cells, params):
    from scipy.optimize import milp, Bounds, LinearConstraint
    from scipy.sparse import lil_matrix
    max_size = int(params['iee_max_merge_cells'])
    limit = int(params['iee_max_candidates'])
    seconds = float(params['iee_time_limit_s'])
    if max_size < 1 or limit < len(cells) or seconds <= 0:
        raise ValueError('IEE 候选上限至少为原始单元数，合并规模和时间须为正')
    candidates, limited = _merge_candidates(cells, max_size, limit)
    keys = list(candidates)
    matrix = lil_matrix((len(cells), len(keys)), dtype=float)
    for j, mask in enumerate(keys):
        for i in range(len(cells)):
            if mask >> i & 1:
                matrix[i, j] = 1
    checkpoint('整数规划选择凸块（可用终止按钮结束工作进程）', force=True)
    result = milp(np.ones(len(keys)), integrality=np.ones(len(keys)), bounds=Bounds(0, 1),
                  constraints=LinearConstraint(matrix.tocsc(), 1, 1),
                  options={'time_limit': seconds, 'mip_rel_gap': 0.})
    checkpoint()
    if result.x is None:
        raise RuntimeError('IEE 整数规划未产生可行解：' + result.message)
    chosen = [j for j, value in enumerate(result.x) if value > .5]
    if not np.allclose(matrix[:, chosen].sum(axis=1), 1):
        raise RuntimeError('IEE 整数规划结果未恰好覆盖每个基本单元一次')
    return [candidates[keys[j]] for j in chosen], {
        'atomic_cells': len(cells), 'candidate_count': len(keys), 'candidate_family_limited': limited,
        'optimal_within_candidates': result.status == 0, 'milp_status': int(result.status),
        'milp_message': result.message, 'objective': 'min_convex_cell_count_in_candidate_family'}


def _greene(poly, budget):
    """Minimum-count recurrence over valid vertex diagonals; bounded state search.

    Same no-Steiner objective as Greene, but not his polynomial recurrence.
    A state-budget hit returns a valid HM incumbent and is explicitly recorded.
    """
    if budget < 1:
        raise ValueError('Greene 搜索状态预算须为正')
    used, hit = 0, False

    def key(p):
        pts = _ring(_clean(p))
        start = min(range(len(pts)), key=lambda i: pts[i])
        return tuple(pts[start:] + pts[:start])

    @lru_cache(None)
    def search(ring):
        nonlocal used, hit
        checkpoint('Greene 最少凸块递归搜索')
        p = Polygon(ring)
        if _convex(p):
            return (p,)
        incumbent = tuple(_hm(p))
        if used >= budget:
            hit = True
            return incumbent
        used += 1
        n = len(ring)
        for i in range(n):
            for j in range(i+2, n):
                if used >= budget:
                    hit = True
                    return incumbent
                if i == 0 and j == n-1:
                    continue
                line = LineString([ring[i], ring[j]])
                if not p.covers(line) or not p.contains(line.interpolate(.5, normalized=True)):
                    continue
                a = Polygon(ring[i:j+1])
                b = Polygon(ring[j:] + ring[:i+1])
                if a.area <= 1e-14 or b.area <= 1e-14 or not a.is_valid or not b.is_valid:
                    continue
                candidate = search(key(a)) + search(key(b))
                if len(candidate) < len(incumbent):
                    incumbent = candidate
                if len(incumbent) == 2:
                    return incumbent  # a non-convex polygon needs at least two
        return incumbent

    parts = list(search(key(poly)))
    return parts, {'states': used, 'state_budget_hit': hit, 'minimum_count_proven': not hit,
                   'objective': 'minimum_convex_cell_count_without_Steiner_vertices'}


def _width(poly):
    pts = np.array(_ring(poly))
    edge = np.roll(pts, -1, axis=0)-pts
    lengths = np.linalg.norm(edge, axis=1)
    normals = np.column_stack((-edge[:, 1], edge[:, 0]))/lengths[:, None]
    return float(np.min(np.ptp(pts @ normals.T, axis=0)))


def _rgs(poly, rotations):
    if not 1 <= rotations <= 180:
        raise ValueError('RGS 尝试方向数须在1～180之间')

    def recurse(p):
        checkpoint('RGS 凹顶点递归贪心切分')
        if _convex(p):
            return [p]
        pts = _ring(p)
        choices = []
        for i, b in enumerate(pts):
            a, c = pts[i-1], pts[(i+1) % len(pts)]
            if (b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]) >= -1e-13:
                continue
            parts = _polygons(split(p, LineString([(b[0], -4), (b[0], 4)])))
            if len(parts) > 1:
                # Hulls only score candidate cuts. They never replace output cells.
                score = sum(_width(q.convex_hull) for q in parts)
                choices.append((score, i, parts))
        if not choices:
            raise RuntimeError('RGS 当前方向无有效凹顶点切分，请调整方向数')
        return [part for q in min(choices, key=lambda v: v[:2])[2] for part in recurse(_clean(q))]

    best, score_best, angle_best = None, math.inf, 0
    for angle in np.linspace(0, 180, rotations, endpoint=False):
        rotated = affinity.rotate(poly, -float(angle), origin=(0, 0))
        parts = recurse(rotated)
        score = sum(_width(p) for p in parts)
        if score < score_best-1e-12:
            best, score_best, angle_best = parts, score, float(angle)
    return [affinity.rotate(p, angle_best, origin=(0, 0)) for p in best], {'rotation_deg': angle_best,
        'objective': 'sum_minimum_width', 'implementation': 'reflex vertical splits; greedy hull-width score; exact boundary retained'}


def _td_dp(cells):
    """Interval DP over deterministic sweep order, permitting only convex unions."""
    cells = sorted(cells, key=lambda p: (p.centroid.x, p.centroid.y))
    n = len(cells)
    dp, previous, blocks = [0] + [math.inf]*n, {}, {}
    for end in range(1, n+1):
        merged = None
        for start in range(end-1, -1, -1):
            checkpoint('TD-DP 连续凸单元重组')
            merged = cells[start] if merged is None else merged.union(cells[start])
            if _convex(merged) and dp[start]+1 < dp[end]:
                dp[end], previous[end], blocks[end] = dp[start]+1, start, _clean(merged)
    result, end = [], n
    while end:
        result.append(blocks[end])
        end = previous[end]
    return list(reversed(result))


class DecompositionMethod:
    independent_component_params = True
    default_params = {}
    param_labels = {}

    def get_param_spec(self):
        return [(k, self.param_labels[k], 'int' if isinstance(v, int) else 'float', v)
                for k, v in self.default_params.items()]

    def decompose_region(self, vertices, params):
        params = dict(self.default_params, **params)
        original, poly, transform = _prepare(vertices)
        parts, info = self.partition(poly, params)
        info.update(segmentation=self.label, implementation_scope=self.description)
        return _finish(parts, original, transform, info)


class TDDecomposition(DecompositionMethod):
    label = 'TD 梯形分解'
    description = '按全部顶点的扫描横坐标切成梯形或三角形；角度可调，不执行合并。'
    default_params = {'td_angle_deg': 0.}
    param_labels = {'td_angle_deg': '梯形分解旋转角度 (°)'}

    def partition(self, poly, p):
        return _td(poly, float(p['td_angle_deg'])), {'rotation_deg': float(p['td_angle_deg'])}


class HMDecomposition(DecompositionMethod):
    label = 'Hertel–Mehlhorn 凸分解'
    description = '耳切三角剖分后删除合并后仍凸的内部对角线，采用最长共享边优先的确定性顺序。'

    def partition(self, poly, p):
        return _hm(poly), {'implementation': 'ear triangulation + removal of inessential diagonals'}


class IEEDecomposition(DecompositionMethod):
    label = 'IEE + 整数规划合并（思路）'
    description = '凹顶点邻边支撑线延伸形成基本凸单元，用0/1整数规划最少块合并；最优性仅限已生成的凸合并候选。'
    default_params = {'iee_max_merge_cells': 8, 'iee_max_candidates': 5000, 'iee_time_limit_s': 10.}
    param_labels = {'iee_max_merge_cells': '单个凸合并候选的基本单元上限',
                    'iee_max_candidates': '整数规划候选数量上限', 'iee_time_limit_s': '整数规划时间上限 (s)'}

    def partition(self, poly, p):
        return _milp_merge(_iee_cells(poly), p)


class GreeneDecomposition(DecompositionMethod):
    label = 'Greene 最少块凸分解（思路）'
    description = '以最少凸块为目标枚举可见顶点对角线并记忆化递归；非Greene原文多项式实现。预算用尽保留有效解并记录，只有搜索完整才声明最优。'
    default_params = {'greene_state_budget': 3000}
    param_labels = {'greene_state_budget': '最少块搜索状态预算'}

    def partition(self, poly, p):
        return _greene(poly, int(p['greene_state_budget']))


class RGSDecomposition(DecompositionMethod):
    label = 'RGS 递归贪心分解（思路）'
    description = '多方向尝试，在凹顶点作垂直切分，按宽度和贪心选择并递归。保持任务边界，不使用原文可外扩的凸包替代，也不建模风场。'
    default_params = {'rgs_rotations': 6}
    param_labels = {'rgs_rotations': '递归贪心尝试方向数'}

    def partition(self, poly, p):
        return _rgs(poly, int(p['rgs_rotations']))


class TDDPDecomposition(DecompositionMethod):
    label = 'TD + DP 重组（思路）'
    description = '梯形分解后按扫描坐标排序，以动态规划最少块重组连续、合并后仍凸的单元；仅保证此连续序列约束下最优。'
    default_params = {'td_angle_deg': 0.}
    param_labels = {'td_angle_deg': '梯形分解旋转角度 (°)'}

    def partition(self, poly, p):
        cells = _td(poly, float(p['td_angle_deg']))
        rotated = [affinity.rotate(q, -float(p['td_angle_deg']), origin=(0, 0)) for q in cells]
        merged = _td_dp(rotated)
        return [affinity.rotate(q, float(p['td_angle_deg']), origin=(0, 0)) for q in merged], {
            'atomic_cells': len(cells), 'objective': 'min_convex_cells_in_contiguous_sweep_order'}
