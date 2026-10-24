"""Additional convex partitions. Adaptation scope is returned with every result.

All geometry is translated/scaled before construction to protect UTM coordinates.
No convex hull may replace the task boundary, and no positive-area cell is dropped.
"""
import heapq
import math
from functools import lru_cache

import numpy as np
from shapely import affinity, union_all
from shapely.geometry import Polygon, LineString, Point
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

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
    return [_ring(p) for p in restored], dict(info, n_cells=len(parts),
        width_sum_m=sum(_width(p) for p in parts)*scale,
        geometry_policy='convex partition; exact ROI; no exterior coverage',
        implementation_version='2.9')


def _td(poly, angle):
    rotated = affinity.rotate(poly, -angle, origin=(0, 0))
    cuts = []
    for vertex in _ring(rotated):
        checkpoint('TD 顶点局部射线分解')
        for direction in ((0., -1.), (0., 1.)):
            end = _ray_end(rotated, vertex, direction)
            if end is not None:
                cuts.append(LineString([vertex, end]))
    cells = _cut_cells(rotated, cuts)
    return [affinity.rotate(p, angle, origin=(0, 0)) for p in cells]


def _ray_end(poly, vertex, direction):
    """First boundary hit of an inward ray; never cut a separate distant branch."""
    x, y = vertex
    dx, dy = direction
    length = math.hypot(dx, dy)
    dx, dy = dx/length, dy/length
    ray = LineString([vertex, (x+4*dx, y+4*dy)])
    hits = poly.boundary.intersection(ray)
    points = []
    pending = [hits]
    while pending:
        item = pending.pop()
        if item.is_empty:
            continue
        if item.geom_type == 'Point':
            points.append(item.coords[0])
        elif item.geom_type == 'LineString':
            points.extend((item.coords[0], item.coords[-1]))
        else:
            pending.extend(item.geoms)
    distances = [((a-x)*dx+(b-y)*dy, (a, b)) for a, b in points]
    distances = [v for v in distances if v[0] > 1e-12]
    if not distances:
        return None
    distance, end = min(distances)
    if not poly.contains(Point(x+dx*distance/2, y+dy*distance/2)):
        return None  # outward or coincident with a boundary edge
    return end


def _cut_cells(poly, cuts):
    # Snap-round the complete arrangement together so boundary hits and crossing
    # rays share nodes even when GEOS constructions differ at machine precision.
    network = union_all([poly.boundary, *cuts], grid_size=1e-12)
    return [_clean(p) for p in polygonize(network)
            if poly.covers(p.representative_point())]


def _reflex(poly):
    pts = _ring(poly)
    for i, b in enumerate(pts):
        a, c = pts[i-1], pts[(i+1) % len(pts)]
        if (b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]) < -1e-13:
            yield i, a, b, c


def _iee_cells(poly):
    """Nielsen 2019 §3.1: inward incident-edge rays stop at the first boundary."""
    cuts = []
    for _, a, b, c in _reflex(poly):
        for other in (a, c):
            checkpoint('IEE 凹顶点邻边延伸')
            end = _ray_end(poly, b, (b[0]-other[0], b[1]-other[1]))
            if end is not None:
                cuts.append(LineString([b, end]))
    cells = _cut_cells(poly, cuts)
    if any(not _convex(p) for p in cells):
        raise RuntimeError('IEE 延伸单元仍存在凹角，无法执行凸合并')
    return cells


def _merge_candidates(cells, max_size, max_candidates):
    """Nielsen 2019 Algorithm 1: balanced-size convex merge option pairs.

    This is the paper's approximation, not enumeration of every convex union.
    """
    n = len(cells)
    candidates = {1 << i: p for i, p in enumerate(cells)}
    levels = {1: list(candidates)}
    maximum = n if max_size == 0 else min(max_size, n)
    for size in range(2, maximum+1):
        levels[size] = []
        seen = set()
        left, right = size//2, (size+1)//2
        for a in levels.get(left, []):
            for b in levels.get(right, []):
                checkpoint('IEE 论文平衡组合候选')
                if a & b:
                    continue
                key = a | b
                if key in seen:
                    continue
                seen.add(key)
                merged = union_all([candidates[a], candidates[b]], grid_size=1e-12)
                if _convex(merged):
                    if len(candidates) >= max_candidates:
                        return candidates, True
                    candidates[key] = _clean(merged)
                    levels[size].append(key)
    return candidates, maximum < n


def _milp_merge(cells, params):
    from scipy.optimize import milp, Bounds, LinearConstraint
    from scipy.sparse import lil_matrix
    max_size = int(params['iee_max_merge_cells'])
    limit = int(params['iee_max_candidates'])
    seconds = float(params['iee_time_limit_s'])
    if max_size < 0 or limit < len(cells) or seconds <= 0:
        raise ValueError('IEE 合并规模须非负（0不限制），候选上限至少为基本单元数，时间须为正')
    candidates, limited = _merge_candidates(cells, max_size, limit)
    keys = list(candidates)
    matrix = lil_matrix((len(cells), len(keys)), dtype=float)
    for j, mask in enumerate(keys):
        for i in range(len(cells)):
            if mask >> i & 1:
                matrix[i, j] = 1
    widths = np.array([_width(candidates[k]) for k in keys])
    checkpoint('IEE 整数规划最小宽度和（可终止工作进程）', force=True)
    result = milp(widths, integrality=np.ones(len(keys)), bounds=Bounds(0, 1),
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
        'milp_message': result.message, 'milp_gap': float(result.mip_gap),
        'candidate_generation': 'Nielsen 2019 Algorithm 1 balanced approximation',
        'objective': 'sum_minimum_width', 'objective_value_normalized': float(result.fun),
        'global_optimality_claimed': False}


def _state_key(poly):
    pts = [tuple(round(c, 12) for c in xy) for xy in _ring(_clean(poly))]
    start = min(range(len(pts)), key=lambda i: pts[i])
    return tuple(pts[start:] + pts[:start])


def _width(poly):
    pts = np.array(_ring(poly))
    edge = np.roll(pts, -1, axis=0)-pts
    lengths = np.linalg.norm(edge, axis=1)
    normals = np.column_stack((-edge[:, 1], edge[:, 0]))/lengths[:, None]
    return float(np.min(np.ptp(pts @ normals.T, axis=0)))


def _angles(start, rotations):
    if not 1 <= rotations <= 180:
        raise ValueError('尝试方向数须在1～180之间')
    if not math.isfinite(start):
        raise ValueError('初始旋转角度须为有限数')
    return (start + np.arange(rotations)*180/rotations) % 180


def _better(cost, count, old_cost, old_count):
    return cost < old_cost-1e-12 or (abs(cost-old_cost) <= 1e-12 and count < old_count)


def _rgs(poly, rotations, max_states=50000):
    """Coombes 2020 Algorithm 1/2 search, using an exact ROI and width surrogate.

    Every reflex cut is evaluated AFTER recursively resolving its children.
    The paper's optional exterior hull coverage is excluded by the ROI policy.
    """
    if max_states < 1:
        raise ValueError('RGS 状态上限须为正')
    states = 0

    @lru_cache(None)
    def recurse(ring):
        nonlocal states
        checkpoint('RGS 比较各凹点递归后的宽度代价')
        states += 1
        if states > max_states:
            raise RuntimeError('RGS 达到状态上限，未完成本次搜索；请提高 rgs_max_states 或减少方向数')
        p = Polygon(ring)
        if _convex(p):
            return (p,), _width(p)
        best, score_best = None, math.inf
        for _, _, vertex, _ in _reflex(p):
            cuts = []
            for direction in ((0., -1.), (0., 1.)):
                end = _ray_end(p, vertex, direction)
                if end is not None:
                    cuts.append(LineString([vertex, end]))
            children = _cut_cells(p, cuts)
            if len(children) < 2:
                continue
            parts, score = [], 0.
            for child in children:
                result, value = recurse(_state_key(child))
                parts.extend(result)
                score += value
            if best is None or _better(score, len(parts), score_best, len(best)):
                best, score_best = tuple(parts), score
        if best is None:
            raise RuntimeError('RGS 当前方向无有效凹顶点切分，请调整方向数')
        return best, score_best

    best, score_best, angle_best = None, math.inf, 0
    for angle in _angles(0., rotations):
        rotated = affinity.rotate(poly, -float(angle), origin=(0, 0))
        parts, score = recurse(_state_key(rotated))
        if best is None or _better(score, len(parts), score_best, len(best)):
            best, score_best, angle_best = parts, score, float(angle)
    return [affinity.rotate(p, angle_best, origin=(0, 0)) for p in best], {'rotation_deg': angle_best,
        'rotation_count': rotations, 'states': states, 'memo_hits': recurse.cache_info().hits,
        'objective': 'sum_minimum_width', 'search_complete': True,
        'hull_coverage_enabled': False, 'wind_model_enabled': False,
        'implementation': 'Coombes 2020 recursive candidate comparison; minimum-width surrogate; exact ROI restriction',
        'global_optimality_claimed': False}


def _td_dp(cells, max_subsets=50000, max_states=100000):
    """Convex connected-subset options and bottom-up set-partition DP.

    Concave intermediate subsets are explored too: later neighbors can make the
    union convex. This avoids the old restriction to contiguous centroid order.
    """
    n = len(cells)
    if max_subsets < n or max_states < 1:
        raise ValueError('TD-DP 子集预算至少为基本单元数，DP状态预算须为正')
    adjacency = [sum(1 << j for j in range(n) if i != j and
                    cells[i].boundary.intersection(cells[j].boundary).length > 1e-12)
                 for i in range(n)]
    candidates = {1 << i: p for i, p in enumerate(cells)}
    discovered = dict(candidates)
    queue = list(discovered)
    domain = union_all(cells, grid_size=1e-12)
    limited = False
    for mask in queue:
        checkpoint('TD-DP 枚举邻接单元集合')
        neighbors = 0
        for i in range(n):
            if mask >> i & 1:
                neighbors |= adjacency[i]
        neighbors &= ~mask
        while neighbors:
            bit = neighbors & -neighbors
            neighbors ^= bit
            key = mask | bit
            if key in discovered:
                continue
            if len(discovered) >= max_subsets:
                limited = True
                break
            merged = union_all([discovered[mask], cells[bit.bit_length()-1]], grid_size=1e-12)
            discovered[key] = merged
            if _convex(merged):
                candidates[key] = _clean(merged)
                queue.append(key)
            elif merged.convex_hull.difference(domain).area <= 1e-13:
                # A convex superset must contain this hull. If that hull exits
                # the ROI, no addition of internal cells can make it feasible.
                queue.append(key)
        if limited:
            break
    # Every transition covers the lowest uncovered atom. This removes duplicate
    # permutations of blocks; ordering by covered atom count is topological.
    containing = [[] for _ in cells]
    for mask, shape in candidates.items():
        cost = _width(shape)
        for i in range(n):
            if mask >> i & 1:
                containing[i].append((mask, cost))
    full = (1 << n)-1
    dp, previous, agenda = {0: (0., 0)}, {}, [(0, 0)]
    while agenda:
        _, covered = heapq.heappop(agenda)
        checkpoint('TD-DP 集合状态动态规划')
        if covered == full:
            break
        atom = ((full ^ covered) & -(full ^ covered)).bit_length()-1
        cost, count = dp[covered]
        for option, value in containing[atom]:
            if covered & option:
                continue
            target = covered | option
            old = dp.get(target, (math.inf, n+1))
            if _better(cost+value, count+1, *old):
                if target not in dp:
                    if len(dp) >= max_states:
                        raise RuntimeError('TD-DP 达到DP状态上限，未完成求解；请提高 tddp_max_states')
                    heapq.heappush(agenda, (target.bit_count(), target))
                dp[target] = cost+value, count+1
                previous[target] = covered, option
    parts, current = [], full
    while current:
        current, option = previous[current]
        parts.append(candidates[option])
    return list(reversed(parts)), {
        'atomic_cells': n, 'connected_subsets_examined': len(discovered),
        'candidate_count': len(candidates), 'candidate_family_limited': limited,
        'dp_states': len(dp), 'optimal_within_candidates': True,
        'optimal_for_fixed_td': not limited, 'objective': 'sum_minimum_width',
        'external_cells_enabled': False, 'wind_model_enabled': False,
        'global_optimality_claimed': False}


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
    description = '从各顶点向上下首次边界发出局部射线，构造梯形单元；多方向按最小宽度和选优，不执行合并。'
    default_params = {'td_angle_deg': 0., 'td_rotations': 6}
    param_labels = {'td_angle_deg': '起始旋转角度 (°)', 'td_rotations': '尝试方向数（1为固定角度）'}

    def partition(self, poly, p):
        best, score_best, selected = None, math.inf, 0.
        rotations = int(p['td_rotations'])
        for angle in _angles(float(p['td_angle_deg']), rotations):
            parts = _td(poly, float(angle))
            score = sum(_width(q) for q in parts)
            if best is None or _better(score, len(parts), score_best, len(best)):
                best, score_best, selected = parts, score, float(angle)
        return best, {'rotation_deg': selected, 'rotation_count': rotations,
                      'objective': 'sum_minimum_width', 'construction': 'local first-hit vertex rays',
                      'wind_model_enabled': False, 'global_optimality_claimed': False}


class HMDecomposition(DecompositionMethod):
    label = 'Hertel–Mehlhorn 凸分解'
    description = '直接调用CGAL 6.0.1 approx_convex_partition_2：使用参考约束三角剖分、内部边遍历顺序和HM删边实现。'

    def partition(self, poly, p):
        from algorithms.cgal_partition import convex_partition
        parts, info = convex_partition(_ring(poly))
        return parts, dict(info, objective='HM convex partition', minimum_count_proven=False)


class IEEDecomposition(DecompositionMethod):
    label = 'IEE + IP 最小宽度合并'
    description = '凹点邻边向内延伸至首次边界，按Nielsen算法1平衡组合生成凸候选，用0/1整数规划最小化宽度和；候选近似和预算状态均记录。'
    default_params = {'iee_max_merge_cells': 0, 'iee_max_candidates': 10000, 'iee_time_limit_s': 10.}
    param_labels = {'iee_max_merge_cells': '单个凸候选的基本单元上限（0不限制）',
                    'iee_max_candidates': '整数规划候选数量上限', 'iee_time_limit_s': '整数规划时间上限 (s)'}

    def partition(self, poly, p):
        return _milp_merge(_iee_cells(poly), p)


class GreeneDecomposition(DecompositionMethod):
    label = 'Greene 最优凸分解'
    description = '直接调用CGAL 6.0.1 optimal_convex_partition_2，执行Greene多项式DP；无Steiner顶点，最少凸块；不再使用旧递归状态预算。'

    def partition(self, poly, p):
        from algorithms.cgal_partition import convex_partition
        parts, info = convex_partition(_ring(poly), optimal=True)
        return parts, dict(info, objective='minimum_convex_cell_count_without_Steiner_vertices',
                           minimum_count_proven=True, state_budget_hit=False)


class RGSDecomposition(DecompositionMethod):
    label = 'RGS 递归分解（宽度代价）'
    description = '按Coombes算法1逐凹点切分、递归求解后比较全部候选，并按算法2搜索方向；使用宽度代价且保持原边界，暂不启用外扩凸包或风模型。'
    default_params = {'rgs_rotations': 6, 'rgs_max_states': 50000}
    param_labels = {'rgs_rotations': '递归分解尝试方向数', 'rgs_max_states': '递归状态上限（超限明确报错）'}

    def partition(self, poly, p):
        return _rgs(poly, int(p['rgs_rotations']), int(p['rgs_max_states']))


class TDDPDecomposition(DecompositionMethod):
    label = 'TD + DP 邻接集合重组'
    description = '局部射线TD后枚举邻接单元集合，使用集合状态自底向上DP最小化宽度和；多方向搜索，记录候选限制；暂不使用外部可选单元或风模型。'
    default_params = {'td_angle_deg': 0., 'td_rotations': 6,
                      'tddp_max_subsets': 50000, 'tddp_max_states': 100000}
    param_labels = {'td_angle_deg': '起始旋转角度 (°)', 'td_rotations': '尝试方向数（1为固定角度）',
                    'tddp_max_subsets': '邻接子集枚举上限', 'tddp_max_states': 'DP状态上限（超限明确报错）'}

    def partition(self, poly, p):
        best, score_best, info_best = None, math.inf, None
        rotations = int(p['td_rotations'])
        complete = True
        for angle in _angles(float(p['td_angle_deg']), rotations):
            cells = _td(poly, float(angle))
            parts, info = _td_dp(cells, int(p['tddp_max_subsets']), int(p['tddp_max_states']))
            complete &= not info['candidate_family_limited']
            score = sum(_width(q) for q in parts)
            if best is None or _better(score, len(parts), score_best, len(best)):
                best, score_best = parts, score
                info_best = dict(info, rotation_deg=float(angle))
        return best, dict(info_best, rotation_count=rotations, all_rotation_candidates_complete=complete)
