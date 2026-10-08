# -*- coding: utf-8 -*-
"""子问题 3：E-GTSP 建模 + ANT-cycle 型 ACO 求解。

建模要素（对齐论文 Kato et al. 2025, §3.4 / Algorithm 2）：
- 节点：每子区域 4 种进出方案 → 4 节点；另加 1 起飞/返航点；
- 距离矩阵 D[i][j] 为 i 的出口到 j 的入口的直线飞行距离；
  同子区域内 4 节点间距离 = ∞（每组必须且仅选 1 节点 → E-GTSP）；
- 状态转移概率 p(i,j) = (τ_ij^α · η_ij^β) / Σ(...)，η_ij = 1/D(i,j)；
- 禁忌表按区域（子区域组）粒度记录，保证每组仅访问一次；
- 信息素更新（ANT-cycle）：所有蚂蚁完成本轮构建后，先挥发
  τ ← (1-ρ)·τ，再按 Δτ = Q/L_k 沉积，L_k 为第 k 只蚂蚁的全程距离。

论文同时实现了一个可调节、可关闭的“随机因子”（random factor），并指出
算法在“前约 100 次迭代具有很强的探索特征、约 150 次迭代后收敛”。β=20
使启发信息极度贪心，若把随机因子完全关闭（=0），蚁群会在第 0 代就全部
挤到最近邻贪心解上、信息素来不及发挥作用，表现为收敛曲线一条水平线、
且停在明显次优解（在本项目算例上转运距离比精确最优差约 44%）。

因此本实现按论文意图补齐并默认开启“前期探索 → 后期利用”机制：
1. 探索概率 exploration_prob 作为**初始**探索率，随迭代余弦衰减到 0；
2. 探索步采用 GRASP 受限候选表（RCL）：只在离当前点最近的若干个候选
   节点中均匀随机选取（池大小 = max(4, rcl_ratio×候选数)），既跳出
   最近邻贪心的局部盆、又不做低质量的纯随机；
3. 标准批量 ANT-cycle 更新（修正了原先“逐只在线沉积、轮末再统一挥发”
   导致当轮沉积被额外乘 (1-ρ) 而缩水的偏差）；
4. 全局最优精英沉积：搜索前期关闭、迭代 20% 后线性引入，把探索到的
   最优路径逐步强化，保证曲线后期平稳收敛；
5. 以确定性最近邻贪心解作为初始最优上界（热启动/兜底）：最终结果永远
   不会劣于最近邻贪心，小规模问题上探索无收益时自动退回贪心解；
6. τ0 设为 0 时自动取 Q/L_nn（与沉积量同量级），使信息素正反馈与
   η^β 在可比尺度上发挥作用，且对距离量纲自适应。
论文四参数 α=0.5, β=20, ρ=0.7, Q=1 保持不变。
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
    :param params: alpha, beta, rho, Q, max_iterations, exploration_prob,
                   rcl_ratio, elite_weight, elite_delay, tau0
    :param seed: 随机种子
    :return: (最优节点序列, 收敛历史[每轮最优全程距离], 统计信息)
    """
    alpha = float(params.get("alpha", 0.5))
    beta = float(params.get("beta", 20.0))
    rho = float(params.get("rho", 0.7))
    Q = float(params.get("Q", 1.0))
    max_iter = int(params.get("max_iterations", 500))
    exp_prob0 = float(params.get("exploration_prob", 0.5))  # 初始探索率（衰减到0）
    rcl_ratio = float(params.get("rcl_ratio", 0.2))         # RCL 候选池占比
    elite_w = float(params.get("elite_weight", 25.0))       # 全局最优精英沉积权重
    elite_delay = float(params.get("elite_delay", 0.2))     # 精英沉积启用的迭代占比
    tau0_cfg = float(params.get("tau0", 0.0))               # <=0 表示自动 Q/L_nn

    rng = np.random.RandomState(seed)

    n = len(nodes)
    if n < 2:
        raise ValueError("E-GTSP 节点数不足")

    # 组：subregion_id → 节点索引列表
    groups: Dict[int, List[int]] = {}
    for nd in nodes:
        groups.setdefault(nd.subregion_id, []).append(nd.index)
    n_groups = len(groups)

    cost = build_cost_matrix(nodes)
    # 归一化启发信息：η = Dmax / D，避免 β 幂次数值溢出（不改变候选间相对大小）
    finite = cost[np.isfinite(cost)]
    dmax = float(finite.max()) if finite.size else 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        eta = np.where(np.isfinite(cost), dmax / np.maximum(cost, 1e-9), 0.0)
    eta = np.clip(eta, 1e-12, 1e6)

    n_ants = max(4, n)  # 蚂蚁数量 = 节点总数（论文）
    group_of = np.array([nd.subregion_id for nd in nodes])

    def _tour_trans(tour: List[int]) -> float:
        """纯区域间转运里程（含从起飞点出发与最终返航）。"""
        trans = 0.0
        for k in range(len(tour) - 1):
            trans += cost[tour[k]][tour[k + 1]]
        trans += cost[tour[-1]][0]  # 返航
        return trans

    def _tour_cost(tour: List[int]) -> float:
        # 全程 = 区域间转运 + 该路线“实际选中方案”的牛耕内部覆盖里程。
        # 用实际选中节点的 internal_distance 求和（而非每组方案 0 的固定值），
        # 可使收敛曲线值与最终航点折线总距离严格自洽。
        inside = sum(nodes[j].internal_distance for j in tour if j != 0)
        return _tour_trans(tour) + inside

    def _tour_edges(tour: List[int]):
        """依次产出蚁路径上的有向边（含返航边）。"""
        for k in range(len(tour) - 1):
            yield tour[k], tour[k + 1]
        yield tour[-1], 0

    def _greedy_nearest_tour() -> List[int]:
        """确定性最近邻贪心解（用于 τ0 自动取值与最优上界兜底）。"""
        tour = [0]
        visited = {0}
        while len(visited) < n_groups:
            cur = tour[-1]
            cand = [j for j in range(1, n) if group_of[j] not in visited]
            j = min(cand, key=lambda x: cost[cur][x])
            tour.append(j)
            visited.add(int(group_of[j]))
        return tour

    def _build_tour(explore_prob: float) -> List[int]:
        """一只蚂蚁按 轮盘赌利用 / RCL 探索 构建完整可行解。"""
        tour = [0]
        visited = {0}
        while len(visited) < n_groups:
            cur = tour[-1]
            cand = [j for j in range(1, n) if group_of[j] not in visited]
            if rng.random_sample() < explore_prob:
                # GRASP 受限候选表：在最近的 top-k 个候选中均匀随机
                k = int(max(4, round(rcl_ratio * len(cand))))
                k = min(k, len(cand))
                pool = sorted(cand, key=lambda x: -eta[cur][x])[:k]
                j = int(pool[rng.randint(len(pool))])
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
        return tour

    # ---- 最近邻贪心热启动：初始最优上界 + τ0 自动取值 ----
    nn_tour = _greedy_nearest_tour()
    nn_cost = _tour_cost(nn_tour)
    best_tour: List[int] = list(nn_tour)
    best_full = nn_cost
    best_iter = 0  # 0 表示最优停留在贪心初值（未被蚁群超越）

    tau0 = tau0_cfg if tau0_cfg > 0 else Q / max(nn_cost, 1e-9)
    tau = np.full((n, n), tau0, dtype=np.float64)
    tau[~np.isfinite(cost)] = 0.0  # 同组/自身边永不使用

    # 精英沉积从 elite_delay 代开始、到 elite_ramp 代线性增至满幅
    d_elite = int(elite_delay * max_iter)
    d_full = int(max(0.6, elite_delay + 0.4) * max_iter)

    convergence: List[float] = []
    for it in range(max_iter):
        # 初始探索率 exp_prob0 随迭代余弦衰减到 0（前期探索、后期利用）
        explore_prob = exp_prob0 * 0.5 * (1.0 + math.cos(math.pi * it / max_iter))
        # 全局最优精英权重：前期关闭以免过早锁死，后期线性增强以稳定收敛
        if elite_w > 0.0:
            if it < d_elite:
                cur_elite_w = 0.0
            else:
                cur_elite_w = elite_w * min(1.0, (it - d_elite) /
                                           max(1, d_full - d_elite))
        else:
            cur_elite_w = 0.0

        # ---------- 全部蚂蚁构建完整解（Ant Movement） ----------
        tours: List[List[int]] = []
        tour_costs: List[float] = []
        for _ in range(n_ants):
            tour = _build_tour(explore_prob)
            cost_t = _tour_cost(tour)
            tours.append(tour)
            tour_costs.append(cost_t)
            if cost_t < best_full - 1e-9:
                best_full = cost_t
                best_tour = list(tour)
                best_iter = it

        # ---------- 标准批量 ANT-cycle：先挥发、再统一沉积 ----------
        tau *= (1.0 - rho)
        delta = np.zeros_like(tau)
        for tour, cost_t in zip(tours, tour_costs):
            deposit = Q / cost_t
            for u, v in _tour_edges(tour):
                if np.isfinite(cost[u][v]):
                    delta[u][v] += deposit
        # 全局最优精英额外沉积
        if cur_elite_w > 0.0 and best_tour is not None:
            deposit = cur_elite_w * Q / best_full
            for u, v in _tour_edges(best_tour):
                if np.isfinite(cost[u][v]):
                    delta[u][v] += deposit
        tau += delta

        convergence.append(best_full if np.isfinite(best_full) else 0.0)

    # 去掉首尾的起飞/返航点，得到实际访问节点序列
    visit = [v for v in best_tour if v != 0]
    best_trans = _tour_trans(best_tour)
    best_inside = sum(nodes[j].internal_distance for j in best_tour if j != 0)
    stats = {
        "n_nodes": n,
        "n_groups": n_groups,
        "n_ants": n_ants,
        "best_iteration": best_iter,
        "nearest_neighbor_distance": round(nn_cost, 3),
        "best_transition_distance": round(best_trans, 3),
        "internal_distance_total": round(best_inside, 3),
        "aco_params": {
            "alpha": alpha, "beta": beta, "rho": rho, "Q": Q,
            "max_iterations": max_iter,
            "exploration_prob": exp_prob0,
            "rcl_ratio": rcl_ratio,
            "elite_weight": elite_w,
            "elite_delay": elite_delay,
            "tau0": round(tau0, 9),
        },
    }
    return visit, convergence, stats
