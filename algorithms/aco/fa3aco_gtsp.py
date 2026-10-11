# -*- coding: utf-8 -*-
"""子问题 3（论文完整版）：FA3ACO 求解 E-GTSP 区域访问顺序。

复刻论文：Wenxing Wu et al. (2025) "An efficient coverage path planning
method for UAV in complex concave regions", Scientific Reports 15:37227,
DOI 10.1038/s41598-025-20978-8，§4 "Shortest path solving algorithm" 与
Algorithm 3（3-opt）/ Algorithm 4（FA3ACO）。

相对标准 ANT-cycle 蚁群（同目录 aco_gtsp.py，对齐 Kato et al. 2025），
本模块实现论文 FA3ACO 的三项核心改进：

1. **分数阶状态转移（Fractional-order，Eq.16）**：以 Grünwald–Letnikov
   分数阶差分把"历史节点的转移概率"纳入下一城市选择：
       p_ij(t) = (1/T)·[ p_ij(t) + Σ_{k=1}^{N-1} c_k · p_{(i-k),(i+k+1)}(t) ]
       c_k = Γ(k-μ) / ( Γ(1-μ)·Γ(k+1) ),  0 < μ < 1
   工程口径（与分数阶蚁群 FOACO 原始实现一致）：蚂蚁当前位于 cur、已走节点
   序列 hist 时，候选 j 的得分 = 即时倾向 τ_cj^α·η_cj^β 再加权各历史节点
   h（k 步前）到 j 的倾向 τ_hj^α·η_hj^β，系数 c_k ~ k^{-(μ+1)} 非线性衰减，
   最后 1/T 归一化轮盘赌。μ→0 退化为标准一阶转移（可用 fractional_order
   开关完全关闭，对应论文 Table 2 的消融对比）。

2. **自适应信息素蒸发率（Eq.18）**：
       ρ(t) = ρ_min + (ρ_max − ρ_min)·e^{−k·t}
   搜索前期 ρ 大（快速蒸发、强探索），后期 ρ 小（保留优质路径、强利用）；
   沉积仍为 ANT-cycle 形式 τ←(1−ρ)τ + Σ_ant Q/L（Eq.17），L 取该蚂蚁
   **经 3-opt 优化后**的全程里程（否则信息素学不到局部优化成果）。
   adaptive_rho=False 时退化为固定蒸发率 ρ_fixed。

3. **3-opt 局部搜索（Algorithm 3，8 种断边重连）**：每只蚂蚁构建完路径后
   枚举三条断边、穷举全部 8 种段重组（保持/反转/交换三个路径段），取最短，
   迭代至无改进。在 E-GTSP 上反转一个路径段时，段内每个子区改走其"反向
   进出方案"节点（同组 4 变体中 entry/exit 互换者，几何上即同一条牛耕航线
   反向遍历）；由距离对称性，段内转运里程在反转/交换下保持不变，故每种
   重组只需比较 4 条受影响连接边，评估为 O(1)。use_three_opt=False 可关闭
   （对应论文中无 3-opt 的消融组）。

接口与 aco_gtsp.solve_aco_gtsp 完全一致：(nodes, params, seed) →
(最优节点序列[不含起降点], 收敛历史, 统计字典)，可直接替换下游求解器。
"""
import math
from typing import Dict, List, Tuple

import numpy as np

from algorithms.aco.aco_gtsp import GTSPNode, build_cost_matrix

XY = Tuple[float, float]
INF = float("inf")
_COORD_EPS = 1e-6


# ================================================================ 分数阶系数
def gruenwald_letnikov_coeffs(mu: float, n: int) -> np.ndarray:
    """Grünwald–Letnikov 分数阶差分系数 c_k（论文 Eq.16）。

    c_k = Γ(k-μ) / (Γ(1-μ)·Γ(k+1)), k = 1..n；用对数 Γ 计算防溢出。
    μ∈(0,1) 时 c_k>0 且随 k 呈 k^{-(μ+1)} 衰减（近期记忆主导）。
    """
    out = np.empty(n, dtype=np.float64)
    lg1 = math.lgamma(1.0 - mu)
    for k in range(1, n + 1):
        out[k - 1] = math.exp(math.lgamma(k - mu) - lg1 - math.lgamma(k + 1))
    return out


# ================================================================ 反向方案映射
def build_reverse_node_map(nodes: List[GTSPNode]) -> Dict[int, int]:
    """为每个覆盖方案节点找"反向进出方案"节点（同子区、entry/exit 互换）。

    牛耕 4 变体 (asc/desc × 首段正反) 恰为两对反向路径：0↔3、1↔2；
    这里不依赖变体编号，而用几何坐标匹配，避免上游未传 variant_id 时失配。
    起降点(index 0)映射到自身。
    """
    rev: Dict[int, int] = {0: 0}
    groups: Dict[int, List[int]] = {}
    for nd in nodes:
        groups.setdefault(nd.subregion_id, []).append(nd.index)
    for gid, idxs in groups.items():
        if gid == 0:
            continue
        for a in idxs:
            na = nodes[a]
            mate = None
            for b in idxs:
                if b == a:
                    continue
                nb = nodes[b]
                if (math.hypot(na.entry[0] - nb.exit[0], na.entry[1] - nb.exit[1]) < _COORD_EPS
                        and math.hypot(na.exit[0] - nb.entry[0],
                                       na.exit[1] - nb.entry[1]) < _COORD_EPS):
                    mate = b
                    break
            if mate is None:
                # 兜底：同组按变体编号配对（0↔3, 1↔2），再不行配对自身
                vid = getattr(na, "variant_id", 0)
                want = {0: 3, 1: 2, 2: 1, 3: 0}.get(vid, a)
                mate = next((b for b in idxs
                             if b != a and getattr(nodes[b], "variant_id", 0) == want), a)
            rev[a] = mate
    return rev


# ================================================================ 3-opt（Algorithm 3）
def three_opt_tour(internal: List[int],
                   cost: np.ndarray,
                   rev_map: Dict[int, int],
                   inside_of,
                   cache: Dict[Tuple[int, ...], Tuple[Tuple[int, ...], float]]
                   ) -> Tuple[List[int], float, bool, bool]:
    """对一条 E-GTSP 路径（不含起降点 0 的内部节点序列）做 3-opt 至局部最优。

    评估口径与求解器 full_cost 严格一致：转运连接边 + 各节点牛耕内部里程。
    段反转时节点换反向方案，其内部里程以反向方案节点的实际值计入（同组四
    变体几何上为同一条航线，里程应相等，此处仍按实际节点值求和，杜绝浮点
    微差导致"优化后反而变长"）。段内成本用前缀和 O(1) 取得。

    :param inside_of: 函数 node_index -> 该节点方案的牛耕内部里程
    :return: (优化后内部节点序列, 总里程改进量, 是否有改进, 是否命中缓存)
    """
    key = tuple(internal)
    cached = cache.get(key)
    if cached is not None:
        seq, gain = cached
        return list(seq), gain, gain > 1e-9, True

    s = list(internal)
    m = len(s)
    total_gain = 0.0

    def rev_seg(seg: List[int]) -> List[int]:
        """段反转：时序倒序，每个节点换反向方案节点。"""
        return [rev_map[x] for x in reversed(seg)]

    if m >= 4:
        while True:
            # 内部里程前缀和（正向 / 反向方案），随 s 更新重建
            P = [0.0] * (m + 1)
            rP = [0.0] * (m + 1)
            for q in range(m):
                P[q + 1] = P[q] + inside_of(s[q])
                rP[q + 1] = rP[q] + inside_of(rev_map[s[q]])

            def seg_inside(lo: int, hi: int, rev: bool) -> float:
                """s[lo:hi] 段的内部里程（rev=True 为反转方案）。"""
                return (rP[hi] - rP[lo]) if rev else (P[hi] - P[lo])

            best_gain = 1e-9
            best_rebuild = None  # (i, 拼接后的尾部序列)
            # 切点：切边 s[i]→s[i+1]、s[j]→s[j+1]、s[k]→(s[k+1]或返航0)
            for i in range(-1, m - 3):
                pf = 0 if i < 0 else s[i]
                a0 = i + 1
                for j in range(i + 1, m - 2):
                    b0 = j + 1
                    for k in range(j + 1, m):
                        c0 = k + 1
                        # 段：(节点序列, 内部里程)；A=s[a0:b0], B=s[b0:c0], C=s[c0:m]
                        A, B, C = s[a0:b0], s[b0:c0], s[c0:m]
                        parts = [
                            ([A, B, C],
                             [seg_inside(a0, b0, False),
                              seg_inside(b0, c0, False),
                              seg_inside(c0, m, False)]),
                            ([A, B, rev_seg(C)],
                             [seg_inside(a0, b0, False),
                              seg_inside(b0, c0, False),
                              seg_inside(c0, m, True)]),
                            ([A, rev_seg(B), C],
                             [seg_inside(a0, b0, False),
                              seg_inside(b0, c0, True),
                              seg_inside(c0, m, False)]),
                            ([A, rev_seg(B), rev_seg(C)],
                             [seg_inside(a0, b0, False),
                              seg_inside(b0, c0, True),
                              seg_inside(c0, m, True)]),
                            ([A, C, B],
                             [seg_inside(a0, b0, False),
                              seg_inside(c0, m, False),
                              seg_inside(b0, c0, False)]),
                            ([A, C, rev_seg(B)],
                             [seg_inside(a0, b0, False),
                              seg_inside(c0, m, False),
                              seg_inside(b0, c0, True)]),
                            ([A, rev_seg(C), B],
                             [seg_inside(a0, b0, False),
                              seg_inside(c0, m, True),
                              seg_inside(b0, c0, False)]),
                            ([A, rev_seg(C), rev_seg(B)],
                             [seg_inside(a0, b0, False),
                              seg_inside(c0, m, True),
                              seg_inside(b0, c0, True)]),
                        ]

                        def tail_cost(seqs, inss):
                            seqs2 = [(q, d) for q, d in zip(seqs, inss) if q]
                            c = sum(d for _, d in seqs2)
                            c += cost[pf][seqs2[0][0][0]]
                            for (x, _), (y, _) in zip(seqs2, seqs2[1:]):
                                c += cost[x[-1]][y[0]]
                            c += cost[seqs2[-1][0][-1]][0]
                            return c

                        base = tail_cost(parts[0][0], parts[0][1])
                        for seqs, inss in parts[1:]:
                            gain = base - tail_cost(seqs, inss)
                            if gain > best_gain:
                                best_gain = gain
                                best_rebuild = (i, [q for q in seqs if q])
            if best_rebuild is None:
                break
            i, tail = best_rebuild
            s = s[:i + 1] + [x for seg in tail for x in seg]
            total_gain += best_gain

    cache[key] = (tuple(s), total_gain)
    return s, total_gain, total_gain > 1e-9, False


# ================================================================ FA3ACO 主流程
def solve_fa3aco_gtsp(nodes: List[GTSPNode],
                      params: Dict,
                      seed: int = 42
                      ) -> Tuple[List[int], List[float], Dict]:
    """FA3ACO（论文 Algorithm 4）求解 E-GTSP。

    :param nodes: 节点列表（index 0 为起飞/返航点，组号 0；其余每子区 4 节点）
    :param params: alpha, beta, Q, max_iterations, ants_count, mu,
                   fractional_order, rho_min, rho_max, rho_decay_k,
                   adaptive_rho, rho_fixed, use_three_opt, tau0
    :param seed: 随机种子
    :return: (最优节点序列[不含起降点], 收敛历史[每轮最优全程距离], 统计)
    """
    alpha = float(params.get("alpha", 1.0))           # 论文 Eq.15（未给值，取经典 1）
    # 论文未给 FA3ACO 自身 β；CPP 场景子区进出点距离比远大于 TSPLIB 城市点距比，
    # β=2/3 会使轮盘赌首代即近似确定性贪心（信息素无从发挥），取 β=1 保证全局
    # 采样多样性，组序列优化交给 3-opt 强力局部搜索（论文 Fig.8 的快速下降机制）。
    beta = float(params.get("beta", 1.0))
    Q = float(params.get("Q", 1.0))
    max_iter = int(params.get("max_iterations", 500)) # 论文 §5.1：500 代
    n_ants = int(params.get("ants_count", 20))        # 论文 §5.1：蚂蚁 20

    mu = float(params.get("mu", 0.5))                 # 分数阶阶数 μ∈(0,1)，论文 Eq.16
    fractional_order = bool(params.get("fractional_order", True))
    rho_min = float(params.get("rho_min", 0.05))      # 论文 Eq.18（未给值，取常用区间）
    rho_max = float(params.get("rho_max", 0.9))       # 初期高蒸发强探索（Eq.18 设计意图）
    rho_decay_k = float(params.get("rho_decay_k", 3.0))  # e^{-k·t/T}，T=max_iter
    adaptive_rho = bool(params.get("adaptive_rho", True))
    rho_fixed = float(params.get("rho_fixed", 0.1))
    use_three_opt = bool(params.get("use_three_opt", True))
    tau0_cfg = float(params.get("tau0", 0.0))

    rng = np.random.RandomState(seed)

    n = len(nodes)
    if n < 2:
        raise ValueError("E-GTSP 节点数不足")

    groups: Dict[int, List[int]] = {}
    for nd in nodes:
        groups.setdefault(nd.subregion_id, []).append(nd.index)
    n_groups = len(groups)
    group_of = np.array([nd.subregion_id for nd in nodes])

    cost = build_cost_matrix(nodes)
    finite = cost[np.isfinite(cost)]
    dmax = float(finite.max()) if finite.size else 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        eta = np.where(np.isfinite(cost), dmax / np.maximum(cost, 1e-9), 0.0)
    eta = np.clip(eta, 1e-12, 1e6)

    rev_map = build_reverse_node_map(nodes)
    fo_coeffs = gruenwald_letnikov_coeffs(
        mu, max(1, n_groups - 1)) if fractional_order else None
    opt_cache: Dict[Tuple[int, ...], Tuple[Tuple[int, ...], float]] = {}

    # ------------------------------------------------------------ 成本与贪心初值
    def trans_cost(tour: List[int]) -> float:
        """转运里程（含出发、返航），tour 含起降点 0。"""
        c = 0.0
        for a, b in zip(tour[:-1], tour[1:]):
            c += cost[a][b]
        c += cost[tour[-1]][0]
        return c

    def full_cost(internal: List[int]) -> float:
        """全程 = 转运 + 实际选中方案的牛耕内部覆盖里程。"""
        inside = sum(nodes[j].internal_distance for j in internal)
        tour = [0] + internal
        return trans_cost(tour) + inside

    def greedy_nearest() -> List[int]:
        """确定性最近邻可行解（τ0 自动取值与最优上界/兜底）。"""
        tour = [0]
        visited = {0}
        while len(visited) < n_groups:
            cur = tour[-1]
            cand = [j for j in range(1, n) if group_of[j] not in visited]
            j = min(cand, key=lambda x: cost[cur][x])
            tour.append(j)
            visited.add(int(group_of[j]))
        return tour[1:]

    def local_optimize(internal: List[int]):
        """3-opt 开关包装，返回 (内部序列, 转运改进量, 命中缓存)。"""
        if not use_three_opt:
            return internal, 0.0, False
        seq, gain, _improved, hit = three_opt_tour(
            internal, cost, rev_map,
            inside_of=lambda idx: nodes[idx].internal_distance,
            cache=opt_cache)
        return seq, gain, hit

    # ---- 最近邻热启动，并同样过一次 3-opt 作为初始最优上界 ----
    nn_internal = greedy_nearest()
    nn_raw_full = full_cost(nn_internal)
    nn_opt, _, _ = local_optimize(nn_internal)
    best_internal = list(nn_opt)
    best_full = full_cost(best_internal)
    best_iter = 0

    tau0 = tau0_cfg if tau0_cfg > 0 else Q / max(nn_raw_full, 1e-9)
    tau = np.full((n, n), tau0, dtype=np.float64)
    tau[~np.isfinite(cost)] = 0.0

    # ------------------------------------------------------------ 单只蚂蚁构建
    def build_tour() -> List[int]:
        """按论文 Eq.16 分数阶状态转移概率构建完整可行解。"""
        hist = [0]                       # 已访问节点（含当前，hist[-1] 为当前）
        visited = {0}
        while len(visited) < n_groups:
            cur = hist[-1]
            cand = np.array([j for j in range(1, n)
                             if group_of[j] not in visited], dtype=int)
            eta_pow = eta[cur, cand] ** beta
            scores = (tau[cur, cand] ** alpha) * eta_pow
            if fractional_order and len(hist) >= 2:
                # 历史节点转移倾向加权和（Eq.16 的 Grünwald–Letnikov 和式）
                for k in range(1, len(hist)):
                    h = hist[-(k + 1)]   # k 步前所在节点
                    scores = scores + fo_coeffs[k - 1] * (tau[h, cand] ** alpha) \
                        * (eta[h, cand] ** beta)
            s = float(scores.sum())
            if s <= 0.0 or not math.isfinite(s):
                j = int(cand[rng.randint(len(cand))])
            else:
                p = scores / s
                j = int(rng.choice(cand, p=p))
            hist.append(j)
            visited.add(int(group_of[j]))
        return hist

    # ------------------------------------------------------------ 主迭代（Algorithm 4）
    convergence: List[float] = []
    n_improved_tours = 0
    cache_hits = 0
    rho_start = rho_end = None

    for it in range(max_iter):
        # Eq.18 自适应蒸发率（t 归一化到 [0,1]，与最大迭代数无关）
        if adaptive_rho:
            tt = it / max(1, max_iter - 1)
            rho = rho_min + (rho_max - rho_min) * math.exp(-rho_decay_k * tt)
        else:
            rho = rho_fixed
        if it == 0:
            rho_start = rho
        rho_end = rho

        tours_internal: List[List[int]] = []
        tour_full_costs: List[float] = []
        for _ in range(n_ants):
            internal = build_tour()[1:]
            internal, gain, hit = local_optimize(internal)
            if hit:
                cache_hits += 1
            if gain > 1e-9:
                n_improved_tours += 1
            fc = full_cost(internal)
            tours_internal.append(internal)
            tour_full_costs.append(fc)
            if fc < best_full - 1e-9:
                best_full = fc
                best_internal = list(internal)
                best_iter = it

        # ANT-cycle：先按 ρ(t) 挥发（Eq.17/18），再按优化后里程统一沉积
        tau *= (1.0 - rho)
        delta = np.zeros_like(tau)
        for internal, fc in zip(tours_internal, tour_full_costs):
            deposit = Q / max(fc, 1e-9)
            seq = [0] + internal
            for u, v in zip(seq[:-1], seq[1:]):
                if np.isfinite(cost[u][v]):
                    delta[u][v] += deposit
            if np.isfinite(cost[seq[-1]][0]):
                delta[seq[-1]][0] += deposit
        tau += delta

        convergence.append(best_full if np.isfinite(best_full) else 0.0)

    # ---- 结果统计 ----
    best_tour = [0] + best_internal
    best_trans = trans_cost(best_tour)
    best_inside = sum(nodes[j].internal_distance for j in best_internal)
    stats = {
        "n_nodes": n,
        "n_groups": n_groups,
        "n_ants": n_ants,
        "best_iteration": best_iter,
        "nearest_neighbor_distance": round(nn_raw_full, 3),
        "nn_three_opt_distance": round(full_cost(nn_opt), 3),
        "best_transition_distance": round(best_trans, 3),
        "internal_distance_total": round(best_inside, 3),
        "three_opt": {
            "enabled": use_three_opt,
            "improved_tours": n_improved_tours,
            "cache_hits": cache_hits,
            # 最终最优解相对原始最近邻解的总缩短（含蚁群+3-opt 的净收益）
            "gain_over_nearest": round(float(nn_raw_full - best_full), 3),
        },
        "fa3aco_params": {
            "alpha": alpha, "beta": beta, "Q": Q,
            "max_iterations": max_iter, "ants_count": n_ants,
            "fractional_order": fractional_order, "mu": mu,
            "adaptive_rho": adaptive_rho,
            "rho_min": rho_min, "rho_max": rho_max,
            "rho_decay_k": rho_decay_k, "rho_fixed": rho_fixed,
            "use_three_opt": use_three_opt,
            "tau0": round(tau0, 9),
        },
        "rho_start": round(float(rho_start), 5) if rho_start is not None else None,
        "rho_end": round(float(rho_end), 5) if rho_end is not None else None,
    }
    return best_internal, convergence, stats
