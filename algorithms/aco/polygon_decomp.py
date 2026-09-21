# -*- coding: utf-8 -*-
"""子问题 1：凹多边形凸分解（复刻论文 Kato et al. 2025 所用算法）。

论文 3.2 节（"Subproblem 1 – polygon decomposition"）明确说明分解使用
Python 库 "poly_decomp"（PyPI: poly_decomp 0.0.1），该库为 Mark Bayazit
凸分解算法（poly-decomp.js, https://github.com/schteppe/poly-decomp.js）
的移植，论文图 4 引用的来源即 https://mpen.ca/406/bayazit/。

本模块的 convex_decompose() 是对该库 polygonQuickDecomp() 的忠实 Python3
移植，算法流程与论文 3.2 节描述逐条对应：
1. 从多边形某个顶点开始遍历，找到第一个凹顶点（reflex，内角 > 180°）；
2. 将该凹顶点的两条邻边延长，与多边形其他边求交，得到 lower/upper 两个
   交点，二者落在同一条"对边"上（楔形开口区，论文图 4a）；
3. 若楔形区内没有其他多边形顶点 → 在对边中点新建一个顶点，凹顶点连接到
   该新点（论文图 4b，Bayazit 的特征操作：允许造新点）；
4. 若楔形区内有其他顶点 → 选择其中距离凹顶点最近的顶点连接（论文图 4c）；
5. 沿连线把环切成两个子环，递归分解，直至全部为凸。

与项目原实现（枚举全部可见对角线 + 全局贪心评分）相比，本实现与论文所用
库完全一致：可"新建顶点"、只在凹顶点局部楔形区内选择连接点、无三角剖分
兜底（算法本身保证收敛，仅以递归层数上限保护）。
"""
import math
from typing import List, Tuple

XY = Tuple[float, float]
EPS = 1e-9


# ---------------------------------------------------------------- 基础几何
def signed_area(pts: List[XY]) -> float:
    """鞋带公式有向面积（正 = CCW）。"""
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def ensure_ccw(pts: List[XY]) -> List[XY]:
    pts = list(pts)
    if signed_area(pts) < 0:
        pts.reverse()
    return pts


def clean_ring(pts: List[XY]) -> List[XY]:
    """去除连续重复点，返回无重复闭合点的环（首尾不相同）。"""
    out = []
    for p in pts:
        if not out or (abs(p[0] - out[-1][0]) > EPS or abs(p[1] - out[-1][1]) > EPS):
            out.append((float(p[0]), float(p[1])))
    # 去除尾点与首点重复
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) < EPS and abs(out[0][1] - out[-1][1]) < EPS:
        out.pop()
    if len(out) < 3:
        raise ValueError("多边形顶点不足 3 个")
    return out


def _cross(o: XY, a: XY, b: XY) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def reflex_indices(pts: List[XY]) -> List[int]:
    """CCW 环上的凹顶点索引（右转，cross < -EPS）。"""
    n = len(pts)
    idx = []
    for i in range(n):
        prev = pts[(i - 1) % n]
        cur = pts[i]
        nxt = pts[(i + 1) % n]
        if _cross(prev, cur, nxt) < -EPS:
            idx.append(i)
    return idx


def is_convex_ring(pts: List[XY]) -> bool:
    return len(reflex_indices(pts)) == 0


# ---------------------------------------------------------------- Bayazit 算法（poly_decomp 库移植）
def _triangle_area(a: XY, b: XY, c: XY) -> float:
    """三角形有向面积（CCW 为正），同 poly_decomp.triangleArea。"""
    return ((b[0] - a[0]) * (c[1] - a[1])) - ((c[0] - a[0]) * (b[1] - a[1]))


def _is_left(a: XY, b: XY, c: XY) -> bool:
    return _triangle_area(a, b, c) > 0


def _is_left_on(a: XY, b: XY, c: XY) -> bool:
    return _triangle_area(a, b, c) >= 0


def _is_right(a: XY, b: XY, c: XY) -> bool:
    return _triangle_area(a, b, c) < 0


def _is_right_on(a: XY, b: XY, c: XY) -> bool:
    return _triangle_area(a, b, c) <= 0


def _sqdist(a: XY, b: XY) -> float:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    return dx * dx + dy * dy


def _at(poly: List[XY], i: int) -> XY:
    """循环取顶点（负索引 / 越界均回绕），同 poly_decomp.polygonAt。"""
    return poly[i % len(poly)]


def _is_reflex(poly: List[XY], i: int) -> bool:
    """CCW 环上顶点 i 是否为凹顶点（右转），同 polygonIsReflex。"""
    return _is_right(_at(poly, i - 1), _at(poly, i), _at(poly, i + 1))


def _append(polygon: List[XY], poly: List[XY], start: int, end: int) -> None:
    """把 poly[start:end] 追加到 polygon（end 不包含），同 polygonAppend。"""
    for k in range(start, end):
        polygon.append(poly[k])


def _line_intersection(p1: XY, p2: XY, q1: XY, q2: XY) -> XY:
    """求直线 (p1,p2) 与 (q1,q2) 的交点；平行时返回 (0,0)（与库一致）。"""
    a1 = p2[1] - p1[1]
    b1 = p1[0] - p2[0]
    c1 = a1 * p1[0] + b1 * p1[1]
    a2 = q2[1] - q1[1]
    b2 = q1[0] - q2[0]
    c2 = a2 * q1[0] + b2 * q1[1]
    det = a1 * b2 - a2 * b1
    if det == 0:  # 平行
        return (0.0, 0.0)
    return ((b2 * c1 - b1 * c2) / det, (a1 * c2 - a2 * c1) / det)


def _quick_decomp(poly: List[XY], result: List[List[XY]],
                  reflex_vertices: List[XY], steiner_points: List[XY],
                  maxlevel: int, level: int, max_pieces: int
                  ) -> List[List[XY]]:
    """Bayazit 快速凸分解（poly_decomp.polygonQuickDecomp 的 Python3 移植）。

    :param poly: CCW 多边形环
    :param result: 输出收集器（凸子环列表，递归共享）
    :param reflex_vertices: 已发现的凹顶点记录（与库一致，仅记录）
    :param steiner_points: 新建顶点记录（Case 1 的对边中点，与库一致）
    :param maxlevel: 最大递归层数（库默认 100），防止不收敛时无限递归
    :param level: 当前递归层数
    :param max_pieces: 结果数量安全上限（超出时剩余子环原样输出）
    """
    if len(poly) < 3:
        return result
    level += 1
    if level > maxlevel:
        return result
    for i in range(len(poly)):
        if not _is_reflex(poly, i):
            continue
        reflex_vertices.append(poly[i])
        upper_int = (0.0, 0.0)
        lower_int = (0.0, 0.0)
        upper_dist = float("inf")
        lower_dist = float("inf")
        upper_index = 0
        lower_index = 0

        # 延长凹顶点 i 的两条邻边，与多边形各边求交，保留最近交点
        for j in range(len(poly)):
            # 边 (i-1 → i) 延长线与边 (j, j-1) 求交（论文图 4a）
            if (_is_left(_at(poly, i - 1), _at(poly, i), _at(poly, j))
                    and _is_right_on(_at(poly, i - 1), _at(poly, i), _at(poly, j - 1))):
                p = _line_intersection(_at(poly, i - 1), _at(poly, i),
                                       _at(poly, j), _at(poly, j - 1))
                if _is_right(_at(poly, i + 1), _at(poly, i), p):
                    d = _sqdist(poly[i], p)
                    if d < lower_dist:
                        lower_dist = d
                        lower_int = p
                        lower_index = j
            # 边 (i+1 → i) 延长线与边 (j, j+1) 求交
            if (_is_left(_at(poly, i + 1), _at(poly, i), _at(poly, j + 1))
                    and _is_right_on(_at(poly, i + 1), _at(poly, i), _at(poly, j))):
                p = _line_intersection(_at(poly, i + 1), _at(poly, i),
                                       _at(poly, j), _at(poly, j + 1))
                if _is_left(_at(poly, i - 1), _at(poly, i), p):
                    d = _sqdist(poly[i], p)
                    if d < upper_dist:
                        upper_dist = d
                        upper_int = p
                        upper_index = j

        lower_poly: List[XY] = []
        upper_poly: List[XY] = []

        # Case 1：楔形区内没有其他顶点 → 在对边中点新建顶点并连接（论文图 4b）
        if lower_index == (upper_index + 1) % len(poly):
            mid = ((lower_int[0] + upper_int[0]) / 2.0,
                   (lower_int[1] + upper_int[1]) / 2.0)
            steiner_points.append(mid)
            if i < upper_index:
                _append(lower_poly, poly, i, upper_index + 1)
                lower_poly.append(mid)
                upper_poly.append(mid)
                if lower_index != 0:
                    _append(upper_poly, poly, lower_index, len(poly))
                _append(upper_poly, poly, 0, i + 1)
            else:
                if i != 0:
                    _append(lower_poly, poly, i, len(poly))
                _append(lower_poly, poly, 0, upper_index + 1)
                lower_poly.append(mid)
                upper_poly.append(mid)
                _append(upper_poly, poly, lower_index, i + 1)
        else:
            # Case 2：楔形区内有顶点 → 连接距离最近的顶点（论文图 4c）
            if lower_index > upper_index:
                upper_index += len(poly)
            closest_dist = float("inf")
            if upper_index < lower_index:
                # 库原样的保护分支（正常流程不会进入）
                return result
            closest_index = 0
            for j in range(lower_index, upper_index + 1):
                if (_is_left_on(_at(poly, i - 1), _at(poly, i), _at(poly, j))
                        and _is_right_on(_at(poly, i + 1), _at(poly, i), _at(poly, j))):
                    d = _sqdist(_at(poly, i), _at(poly, j))
                    if d < closest_dist:
                        closest_dist = d
                        closest_index = j % len(poly)
            if i < closest_index:
                _append(lower_poly, poly, i, closest_index + 1)
                if closest_index != 0:
                    _append(upper_poly, poly, closest_index, len(poly))
                _append(upper_poly, poly, 0, i + 1)
            else:
                if i != 0:
                    _append(lower_poly, poly, i, len(poly))
                _append(lower_poly, poly, 0, closest_index + 1)
                _append(upper_poly, poly, closest_index, i + 1)

        # 结果数量安全上限：超限则剩余子环原样输出（与原实现行为一致）
        if len(result) + 2 > max_pieces:
            result.append(poly)
            return result

        # 先分解较小的子环（与库一致，减少递归深度）
        if len(lower_poly) < len(upper_poly):
            _quick_decomp(lower_poly, result, reflex_vertices, steiner_points,
                          maxlevel, level, max_pieces)
            _quick_decomp(upper_poly, result, reflex_vertices, steiner_points,
                          maxlevel, level, max_pieces)
        else:
            _quick_decomp(upper_poly, result, reflex_vertices, steiner_points,
                          maxlevel, level, max_pieces)
            _quick_decomp(lower_poly, result, reflex_vertices, steiner_points,
                          maxlevel, level, max_pieces)
        return result

    result.append(poly)
    return result


def convex_decompose(vertices: List[XY], max_pieces: int = 64) -> List[List[XY]]:
    """凹多边形凸分解（复刻论文所用 poly_decomp 库的 Bayazit 算法）。

    :param vertices: 任意凹/凸多边形顶点（XY 米制坐标，闭合或不闭合均可）
    :param max_pieces: 结果数量安全上限（论文算法本身无此限制；超限时
        剩余子环原样输出，可能含凹块——与原实现行为一致）
    :return: 凸子区域顶点列表（每个子区域为 CCW 环）
    """
    pts = ensure_ccw(clean_ring(vertices))
    result: List[List[XY]] = []
    _quick_decomp(pts, result, [], [],
                  maxlevel=100, level=0, max_pieces=max_pieces)
    return [ensure_ccw(p) for p in result]
