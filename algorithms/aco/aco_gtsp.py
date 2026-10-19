# -*- coding: utf-8 -*-
"""Kato 2025 §3.4：随机起点、全未访问节点探索、常数 Q 沉积。

不加入论文未规定的 RCL、余弦探索、精英强化或最近邻初值。
随机概率及初始信息素原文未给具体值，保留为明确的实现参数。
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
import numpy as np
from core.execution_control import checkpoint

XY = Tuple[float, float]
INF = float("inf")

@dataclass
class GTSPNode:
    index: int
    region_id: int
    subregion_id: int
    entry: XY
    exit: XY
    internal_distance: float
    path: List[XY] = field(default_factory=list)
    polygon: List[XY] = field(default_factory=list)
    variant_id: int = 0


def build_cost_matrix(nodes: List[GTSPNode]) -> np.ndarray:
    cost = np.full((len(nodes), len(nodes)), INF, dtype=float)
    for i, a in enumerate(nodes):
        for j, b in enumerate(nodes):
            if i == j or a.subregion_id == b.subregion_id:
                continue
            cost[i, j] = math.hypot(a.exit[0]-b.entry[0], a.exit[1]-b.entry[1])
    return cost


def transition_probabilities(tau, distances, alpha, beta):
    """Log-space roulette weights, including legal zero-length connections."""
    tau = np.asarray(tau, dtype=float)
    distances = np.asarray(distances, dtype=float)
    if np.any(~np.isfinite(distances)) or np.any(tau < 0):
        raise ValueError("状态转移包含不可行边或负信息素")
    logs = transition_log_scores(tau, distances, alpha, beta)
    return probabilities_from_logs(logs)


def transition_log_scores(tau, distances, alpha, beta):
    # Forbidden edges stay masked even when beta=0 (0*log(inf) is NaN).
    with np.errstate(invalid='ignore'):
        scores = alpha*np.log(np.maximum(tau, 1e-300)) - beta*np.log(np.maximum(distances, 1e-12))
    return np.where(np.isfinite(distances), scores, -np.inf)


def probabilities_from_logs(logs):
    weights = np.exp(logs - logs.max())
    return weights/weights.sum()


def tour_distance(nodes, cost, internal):
    seq = [0] + list(internal)
    if len(seq) == 1:
        return 0.0
    trans = sum(cost[a, b] for a, b in zip(seq, seq[1:])) + cost[seq[-1], 0]
    return float(trans + sum(nodes[j].internal_distance for j in internal))


def validate_visit(nodes, visit):
    expected = {n.subregion_id for n in nodes if n.subregion_id != 0}
    selected = [nodes[j].subregion_id for j in visit]
    if len(selected) != len(expected) or set(selected) != expected:
        raise RuntimeError("求解器未恰好访问每个子区一次，拒绝组装遗漏覆盖的路径")


def solve_aco_gtsp(nodes: List[GTSPNode], params: Dict, seed: int = 42):
    alpha = float(params.get("alpha", .5))
    beta = float(params.get("beta", 20))
    rho = float(params.get("rho", .7))
    Q = float(params.get("Q", 1))
    iterations = int(params.get("max_iterations", 500))
    random_prob = float(params.get("exploration_prob", .1))
    tau0 = float(params.get("tau0", 1))
    if min(alpha, beta) < 0 or not 0 <= rho <= 1 or Q <= 0 or iterations < 1:
        raise ValueError("ACO 参数无效")
    if not 0 <= random_prob <= 1 or tau0 <= 0 or len(nodes) < 2:
        raise ValueError("探索概率应在 [0,1]，信息素初值应为正，且至少有一个子区")
    rng = np.random.RandomState(seed)
    cost = build_cost_matrix(nodes)
    group_of = np.array([n.subregion_id for n in nodes])
    G = len(set(group_of))
    same_group = group_of[:, None] == group_of[None, :]
    tau = np.where(np.isfinite(cost), tau0, 0.0)
    best, best_cost, best_iteration = None, math.inf, -1
    convergence = []
    for it in range(iterations):
        checkpoint("ACO迭代", it+1, iterations)
        log_scores = transition_log_scores(tau, cost, alpha, beta)
        tours = []
        # 节点数只蚂蚁，每轮随机排列，使每个节点恰有一个起始蚂蚁。
        for start in rng.permutation(len(nodes)):
            route = [int(start)]
            available = ~same_group[start].copy()
            for _ in range(G-1):
                cand = np.flatnonzero(available)
                cur = route[-1]
                if rng.random_sample() < random_prob:
                    nxt = int(rng.choice(cand))
                else:
                    prob = probabilities_from_logs(log_scores[cur, cand])
                    nxt = int(rng.choice(cand, p=prob))
                route.append(nxt)
                available[same_group[nxt]] = False
            # 循环路径旋转到起飞点；保留随机起点构建的完整闭环。
            z = route.index(0)
            route = route[z:] + route[:z]
            visit = route[1:]
            length = tour_distance(nodes, cost, visit)
            tours.append(route)
            if length < best_cost:
                best, best_cost, best_iteration = visit, length, it
        tau *= 1-rho
        for route in tours:
            for a, b in zip(route, route[1:] + route[:1]):
                tau[a, b] += Q
        convergence.append(best_cost)
    validate_visit(nodes, best)
    inside = sum(nodes[j].internal_distance for j in best)
    return best, convergence, {
        "solver": "Kato2025-ACO", "n_nodes": len(nodes), "n_groups": G,
        "n_ants": len(nodes), "best_iteration": best_iteration,
        "best_transition_distance": float(best_cost-inside),
        "internal_distance_total": float(inside),
        "objective": "mission_total_distance", "objective_value": best_cost,
        "paper_alignment": "random-node starts; uniform unvisited exploration; constant-Q deposition",
        "implementation_assumptions": ["random probability and initial pheromone unspecified by paper"],
        "aco_params": {"alpha": alpha, "beta": beta, "rho": rho, "Q": Q,
                       "max_iterations": iterations, "exploration_prob": random_prob, "tau0": tau0},
    }
