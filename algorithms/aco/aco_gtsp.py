# -*- coding: utf-8 -*-
"""子问题 3：E-GTSP 建模 + ANT-cycle 型 ACO 求解。

建模要素（对齐论文）：
- 节点：每子区域 4 种进出方案 → 4 节点；另加 1 起飞/返航点；
- 节点总数 = 区域数 × 4 + 1；
- 距离矩阵 D[i][j] 为 i 的出口到 j 的入口的直线飞行距离；
  同区域内 4 节点间距离 = ∞（每组必须且仅选 1 节点 → E-GTSP）；
- 状态转移概率 p(i,j) = (τ_ij^α · η_ij^β) / Σ(...)，η_ij = 1/D(i,j)；
- 禁忌表按区域粒度记录，保证每区域仅访问一次；
- 信息素更新：挥发 τ = (1-ρ)·τ；沉积 Δτ = Q/L_k。
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

XY = Tuple[float, float]
INF = float("inf")


@dataclass
class GTSPNode:
    """E-GTSP 中的一个节点 = 某子区域的某一种覆盖方案。"""
    index: int
    region_id: int          # 所属原始区域
    subregion_id: int       # 所属子区域（组：每组恰选 1 节点）
    entry: XY
    exit: XY
    internal_distance: float
    path: List[XY] = field(default_factory=list)


def build_cost_matrix(nodes: List[GTSPNode]) -> np.ndarray:
    """构建转移成本矩阵。cost[i][j] = dist(exit_i, entry_j)。"""
    n = len(nodes)
    cost = np.full((n, n), INF, dtype=np.float64)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if nodes[i].subregion_id == nodes[j].subregion_id and i != 0 and j != 0:
                continue  # 同组节点互不切换（∞）
            d = math.hypot(nodes[i].exit[0] - nodes[j].entry[0],
                           nodes[i].exit[1] - nodes[j].entry[1])
            cost[i][j] = d if d > 1e-12 else 1e-9
    return cost


def solve_aco_gtsp(nodes: List[GTSPNode],
                   params: Dict,
                   seed: int = 42) -> Tuple[List[int], List[float], Dict]:
    """ANT-cycle 型 ACO 求解 E-GTSP。

    :param nodes: 节点列表（index 0 为起飞/返航点，组号 0）
    :param params: alpha, beta, rho, Q, max_iterations, exploration_prob, tau0
    :param seed: 随机种子
    :return: (最优节点序列, 收敛历史[每轮最优全程距离], 统计信息)
    """
    alpha = float(params.get("alpha", 0.5))
    beta = float(params.get("beta", 20.0))
    rho = float(params.get("rho", 0.7))
    Q = float(params.get("Q", 1.0))
    max_iter = int(params.get("max_iterations", 500))
    exp_prob = float(params.get("exploration_prob", 0.0))
    tau0 = float(params.get("tau0", 1.0))

    rng = np.random.RandomState(seed)

    n = len(nodes)
    if n < 2:
        raise ValueError("E-GTSP 节点数不足")

    # 组：subregion_id → 节点索引列表
    groups: Dict[int, List[int]] = {}
    for nd in nodes:
        groups.setdefault(nd.subregion_id, []).append(nd.index)

    cost = build_cost_matrix(nodes)
    # 归一化启发信息：η = Dmax / D，避免 β 幂次数值溢出
    finite = cost[np.isfinite(cost)]
    dmax = float(finite.max()) if finite.size else 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        eta = np.where(np.isfinite(cost), dmax / np.maximum(cost, 1e-9), 0.0)
    eta = np.clip(eta, 1e-12, 1e6)

    tau = np.full((n, n), tau0, dtype=np.float64)
    tau[~np.isfinite(cost)] = 0.0  # 同组/自身边永不使用

    internal_total = sum(nd.internal_distance for nd in nodes if nd.index != 0)
    n_ants = max(4, n)  # 蚂蚁数量 = 节点总数（论文）
    group_of = np.array([nd.subregion_id for nd in nodes])
    n_groups = len(groups)

    best_tour: Optional[List[int]] = None
    best_full = INF
    convergence: List[float] = []
    best_iter = -1

    def _tour_cost(tour: List[int]) -> float:
        trans = 0.0
        for k in range(len(tour) - 1):
            trans += cost[tour[k]][tour[k + 1]]
        trans += cost[tour[-1]][0]  # 返航
        return trans + internal_total

    def _tour_edges(tour: List[int]):
        """依次产出蚁路径上的有向边（含返航边）。"""
        for k in range(len(tour) - 1):
            yield tour[k], tour[k + 1]
        yield tour[-1], 0

    for it in range(max_iter):
        # ---------- 蚂蚁构建解 ----------
        for _ in range(n_ants):
            tour = [0]
            visited = {0}
            while len(visited) < n_groups:
                cur = tour[-1]
                cand = [j for j in range(1, n) if group_of[j] not in visited]
                if rng.random_sample() < exp_prob:
                    j = int(cand[rng.randint(len(cand))])
                else:
                    cand_arr = np.array(cand, dtype=int)
                    p = (tau[cur][cand_arr] ** alpha) * (eta[cur][cand_arr] ** beta)
                    s = p.sum()
                    if s <= 0 or not np.isfinite(s):
                        j = int(cand[rng.randint(len(cand))])
                    else:
                        p = p / s
                        j = int(rng.choice(cand_arr, p=p))
                tour.append(j)
                visited.add(int(group_of[j]))
            cost_t = _tour_cost(tour)
            if cost_t < best_full:
                best_full = cost_t
                best_tour = list(tour)
                best_iter = it
            # ---------- 信息素沉积（ANT-cycle） ----------
            deposit = Q / cost_t
            for u, v in _tour_edges(tour):
                if np.isfinite(cost[u][v]):
                    tau[u][v] += deposit
        # ---------- 信息素挥发 ----------
        tau *= (1.0 - rho)
        convergence.append(best_full if np.isfinite(best_full) else 0.0)

    if best_tour is None:
        raise RuntimeError("ACO 未能构建可行解")

    # 去掉首尾的起飞/返航点，得到实际访问节点序列
    visit = [v for v in best_tour if v != 0]
    stats = {
        "n_nodes": n,
        "n_groups": n_groups,
        "n_ants": n_ants,
        "best_iteration": best_iter,
        "best_transition_distance": round(best_full - internal_total, 3),
        "internal_distance_total": round(internal_total, 3),
        "aco_params": {
            "alpha": alpha, "beta": beta, "rho": rho, "Q": Q,
            "max_iterations": max_iter, "exploration_prob": exp_prob,
        },
    }
    return visit, convergence, stats
