# -*- coding: utf-8 -*-
"""Wu 2025 FA3ACO framework with an explicitly identified memory rule.

fractional_mode=1: author's public fractionalIntegral.m (temporal pheromone
memory), plus paper Eq.18 evaporation and Algorithm 3 complete 3-opt.
fractional_mode=0: literal signed Eq.16 coefficients; history indices interpreted
as previous visited nodes to each candidate. Negative probabilities raise; no
silent clipping, replacement of Gamma(-mu), or claim of exact reproduction.
Reference commit: wu457120325/FA3ACO b9579cc203d1b0588f79a6391bee834c05a06f2e.
"""
import itertools
import math
import numpy as np
from algorithms.aco.aco_gtsp import (build_cost_matrix, transition_probabilities,
                                    tour_distance, validate_visit)


def gruenwald_letnikov_coeffs(mu, n):
    """Literal Eq.16: Gamma(k-mu)/(Gamma(-mu)*Gamma(k+1))."""
    if not 0 < mu < 1:
        raise ValueError("分数阶阶数必须满足 0 < mu < 1")
    out = np.empty(n)
    coeff = -mu
    for k in range(1, n+1):
        out[k-1] = coeff
        coeff *= (k-mu)/(k+1)
    return out


def fractional_pheromone_integral(history, order):
    """Author fractionalIntegral.m, chronological past pheromone matrices."""
    if not 0 < order < 1:
        raise ValueError("分数阶阶数必须在 (0,1)")
    if len(history) == 0:
        return 0.0
    weights = np.arange(len(history), 0, -1, dtype=float)**(order-1)
    return np.tensordot(weights, np.asarray(history), axes=(0, 0))/math.gamma(order)


def evaporation_rate(iteration, rho_min, rho_max, decay_k):
    """Paper Eq.18, iteration is the actual zero-based integer, not t/T."""
    return rho_min + (rho_max-rho_min)*math.exp(-decay_k*iteration)


def build_reverse_node_map(nodes):
    rev = {0: 0}
    for a in nodes[1:]:
        matches = [b for b in nodes[1:] if b.subregion_id == a.subregion_id
                   and np.allclose(a.entry, b.exit, rtol=0, atol=1e-7)
                   and np.allclose(a.exit, b.entry, rtol=0, atol=1e-7)
                   and (not a.path or np.allclose(a.path, list(reversed(b.path)), rtol=0, atol=1e-7))]
        if not matches:
            raise ValueError("局部搜索找不到同子区的真实反向覆盖方案")
        rev[a.index] = matches[0].index
    return rev


def three_opt_tour(internal, cost, rev_map, inside_of, cache):
    """Full closed-cycle 3-opt. Fix depot 0, never fix its next node.

    Three cuts create segments A,B,C (C contains depot). Keep C's orientation,
    enumerate A/B order and both orientations: all eight reconnections. Segment
    costs include every directed internal edge and variant's internal distance.
    """
    key = tuple(internal)
    if key in cache:
        seq, gain = cache[key]
        return list(seq), gain, gain > 1e-9, True
    s = [0] + list(internal)
    def actual(route):
        return float(sum(inside_of(x) for x in route)
                     + sum(cost[a, b] for a, b in zip(route, route[1:]+route[:1])))
    original = actual(s)
    N = len(s)
    while N >= 3:
        doubled = s+s
        forward_inside = np.concatenate(([0.], np.cumsum([inside_of(x) for x in doubled])))
        reverse_inside = np.concatenate(([0.], np.cumsum([inside_of(rev_map[x]) for x in doubled])))
        forward_edges = np.concatenate(([0.], np.cumsum([cost[a, b] for a, b in zip(doubled, doubled[1:])])))
        reverse_edges = np.concatenate(([0.], np.cumsum([cost[rev_map[b], rev_map[a]] for a, b in zip(doubled, doubled[1:])])))
        def segment(lo, hi, reverse=False):
            ip, ep = (reverse_inside, reverse_edges) if reverse else (forward_inside, forward_edges)
            value = ip[hi]-ip[lo] + ep[hi-1]-ep[lo]
            head, tail = doubled[lo], doubled[hi-1]
            if reverse:
                head, tail = rev_map[tail], rev_map[head]
            return (head, tail, float(value), lo, hi, reverse)
        def score(parts):
            return sum(x[2] for x in parts)+sum(cost[a[1], b[0]] for a, b in zip(parts, parts[1:]+parts[:1]))
        best_cost, best_parts = actual(s), None
        for i, j, k in itertools.combinations(range(N), 3):
            C = segment(k+1, N+i+1)
            for ra, rb in itertools.product((False, True), repeat=2):
                A, B = segment(i+1, j+1, ra), segment(j+1, k+1, rb)
                for parts in ([C, A, B], [C, B, A]):
                    value = score(parts)
                    if value < best_cost-1e-9:
                        best_cost, best_parts = value, parts
        if best_parts is None:
            break
        candidate = []
        for _, _, _, lo, hi, reverse in best_parts:
            seg = doubled[lo:hi]
            candidate.extend([rev_map[x] for x in reversed(seg)] if reverse else seg)
        z = candidate.index(0)
        candidate = candidate[z:]+candidate[:z]
        if actual(candidate) >= actual(s)-1e-9:
            raise RuntimeError("3-opt 增量评估与完整有向路径成本不一致")
        s = candidate
    gain = original-actual(s)
    cache[key] = (tuple(s[1:]), gain)
    return s[1:], gain, gain > 1e-9, False


def solve_fa3aco_gtsp(nodes, params, seed=42):
    alpha, beta = float(params.get("alpha", 1)), float(params.get("beta", 5))
    Q = float(params.get("Q", 1))
    iterations, ants = int(params.get("max_iterations", 500)), int(params.get("ants_count", 80))
    order = float(params.get("mu", .5))
    memory_strength = float(params.get("memory_strength", .1))
    fractional = bool(params.get("fractional_order", 1))
    mode = int(params.get("fractional_mode", 1))
    adaptive = bool(params.get("adaptive_rho", 1))
    rmin, rmax = float(params.get("rho_min", .05)), float(params.get("rho_max", .9))
    decay, fixed = float(params.get("rho_decay_k", .006)), float(params.get("rho_fixed", .5))
    local = bool(params.get("use_three_opt", 1))
    tau0 = float(params.get("tau0", 1))
    if iterations < 1 or ants < 1 or tau0 <= 0 or Q <= 0 or min(alpha, beta, memory_strength, decay) < 0:
        raise ValueError("FA3ACO 参数无效")
    if not 0 < order < 1 or not 0 <= rmin <= rmax <= 1 or not 0 <= fixed <= 1 or mode not in (0, 1):
        raise ValueError("阶数、挥发率或分数阶模式无效")
    cost = build_cost_matrix(nodes)
    group_of = np.asarray([n.subregion_id for n in nodes])
    G, n = len(set(group_of)), len(nodes)
    if G < 2:
        raise ValueError("至少需要一个子区")
    rng = np.random.RandomState(seed)
    tau = np.where(np.isfinite(cost), tau0, 0.)
    history, convergence, cache = [], [], {}
    rev = build_reverse_node_map(nodes) if local else None
    coeffs = gruenwald_letnikov_coeffs(order, G)
    best, best_value, best_it = None, math.inf, -1
    improvements = hits = 0
    rho_start = rho_end = None
    for it in range(iterations):
        rho = evaporation_rate(it, rmin, rmax, decay) if adaptive else fixed
        if it == 0:
            rho_start = rho
        rho_end = rho
        effective = tau
        if fractional and mode == 1 and history:
            effective = tau + memory_strength*fractional_pheromone_integral(history, order)
        tours = []
        for _ in range(ants):
            start = int(rng.randint(n))
            route, visited = [start], {int(group_of[start])}
            while len(visited) < G:
                cand = np.flatnonzero(~np.isin(group_of, list(visited)))
                cur = route[-1]
                prob = transition_probabilities(effective[cur, cand], cost[cur, cand], alpha, beta)
                if fractional and mode == 0 and len(route) > 1:
                    for k, h in enumerate(reversed(route[:-1]), 1):
                        prob += coeffs[k-1]*transition_probabilities(tau[h, cand], cost[h, cand], alpha, beta)
                    if np.any(prob < -1e-12) or not np.isfinite(prob.sum()) or prob.sum() <= 0:
                        raise ValueError("Wu Eq.16 原式产生负转移概率；原文未给出合法化规则。"
                                         "fractional_mode=1 可选择作者公开的历史信息素积分实现，"
                                         "fractional_order=0 可关闭分数阶项。")
                    prob = np.maximum(prob, 0)  # 仅清除 [-1e-12,0) 浮点误差
                    prob /= prob.sum()
                nxt = int(rng.choice(cand, p=prob))
                route.append(nxt)
                visited.add(int(group_of[nxt]))
            z = route.index(0)
            internal = (route[z:]+route[:z])[1:]
            if local:
                internal, gain, improved, hit = three_opt_tour(internal, cost, rev,
                     lambda x: nodes[x].internal_distance, cache)
                improvements += int(improved)
                hits += int(hit)
            value = tour_distance(nodes, cost, internal)
            tours.append((internal, value))
            if value < best_value:
                best, best_value, best_it = list(internal), value, it
        tau *= 1-rho
        for internal, value in tours:
            route = [0]+internal
            for a, b in zip(route, route[1:]+route[:1]):
                tau[a, b] += Q/max(value, 1e-12)
        if fractional and mode == 1:
            history.append(tau.copy())
        convergence.append(best_value)
    validate_visit(nodes, best)
    inside = sum(nodes[j].internal_distance for j in best)
    return best, convergence, {
        "solver": "Wu2025-framework", "n_nodes": n, "n_groups": G, "n_ants": ants,
        "best_iteration": best_it, "best_transition_distance": best_value-inside,
        "internal_distance_total": inside, "objective": "mission_total_distance",
        "objective_value": best_value,
        "fractional_rule": "author_temporal_pheromone_integral" if mode else "paper_eq16_signed_history_interpretation",
        "reference_commit": "b9579cc203d1b0588f79a6391bee834c05a06f2e",
        "implementation_assumptions": [
            "Published Eq.16 and author's MATLAB algorithm differ; no claim of exact reproduction.",
            "Author integral kernel combined with paper Eq.18 and per-ant full 3-opt.",
            "ANT-cycle deposit Q/L is an implementation choice for unspecified increment in Eq.17.",
            "Four coverage variants adapt paper TSP to directional GTSP."],
        "three_opt": {"enabled": local, "improved_tours": improvements, "cache_hits": hits},
        "rho_start": rho_start, "rho_end": rho_end,
        "fa3aco_params": {"alpha": alpha, "beta": beta, "Q": Q, "mu": order,
            "memory_strength": memory_strength, "fractional_order": fractional,
            "fractional_mode": mode, "adaptive_rho": adaptive, "rho_decay_k": decay,
            "max_iterations": iterations, "ants_count": ants, "tau0": tau0},
    }
