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
from core.execution_control import checkpoint
from algorithms.aco.aco_gtsp import (build_cost_matrix,
                                    tour_distance, validate_visit, transition_log_scores,
                                    probabilities_from_logs)


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


def _cut_blocks(size):
    # Bound scratch arrays even for unusually large decompositions.
    from itertools import islice
    triples = itertools.combinations(range(size), 3)
    while True:
        block = list(islice(triples, 4096))
        if not block:
            return
        yield np.asarray(block, dtype=np.intp)


def three_opt_tour(internal, cost, rev_map, inside_of, cache):
    """Same complete 8-way closed 3-opt neighborhood, evaluated in NumPy blocks.

    Every directed segment edge and internal coverage cost remains included.
    Blocking bounds memory, releases the GIL during arithmetic, and permits cancel.
    """
    key = tuple(internal)
    if key in cache:
        seq, gain = cache[key]
        return list(seq), gain, gain > 1e-9, True
    s = [0]+list(internal)
    N = len(s)
    inside = np.asarray([inside_of(i) for i in range(len(cost))])
    reverse = np.asarray([rev_map.get(i, i) for i in range(len(cost))], dtype=np.intp)
    def actual(route):
        t = np.asarray(route, dtype=np.intp)
        return float(inside[t].sum()+cost[t, np.roll(t, -1)].sum())
    original = actual(s)
    while N >= 3:
        checkpoint()
        known = cache.get(tuple(s[1:]))
        if known is not None:
            s = [0]+list(known[0])
            break
        doubled = np.asarray(s+s, dtype=np.intp)
        reversed_nodes = reverse[doubled]
        fi = np.r_[0., np.cumsum(inside[doubled])]
        ri = np.r_[0., np.cumsum(inside[reversed_nodes])]
        fe = np.r_[0., np.cumsum(cost[doubled[:-1], doubled[1:]])]
        re = np.r_[0., np.cumsum(cost[reversed_nodes[1:], reversed_nodes[:-1]])]
        best_cost, best_move = actual(s), None
        for cuts in _cut_blocks(N):
            checkpoint()
            i, j, k = cuts.T
            def segment(lo, hi, rev=False):
                ip, ep = (ri, re) if rev else (fi, fe)
                value = ip[hi]-ip[lo]+ep[hi-1]-ep[lo]
                head, tail = doubled[lo], doubled[hi-1]
                if rev:
                    head, tail = reverse[tail], reverse[head]
                return head, tail, value
            C = segment(k+1, N+i+1)
            AA = [segment(i+1, j+1), segment(i+1, j+1, True)]
            BB = [segment(j+1, k+1), segment(j+1, k+1, True)]
            scores = np.empty((len(cuts), 8))
            column = 0
            for ra, rb in itertools.product((0, 1), repeat=2):
                A, B = AA[ra], BB[rb]
                base = C[2]+A[2]+B[2]
                scores[:, column] = base+cost[C[1], A[0]]+cost[A[1], B[0]]+cost[B[1], C[0]]
                scores[:, column+1] = base+cost[C[1], B[0]]+cost[B[1], A[0]]+cost[A[1], C[0]]
                column += 2
            flat = int(np.argmin(scores))
            row, variant = divmod(flat, 8)
            value = float(scores[row, variant])
            if value < best_cost-1e-9:
                best_cost = value
                best_move = (*map(int, cuts[row]), variant//4, (variant//2)%2, variant%2)
        if best_move is None:
            break
        i, j, k, ra, rb, swap = best_move
        A, B, C = s[i+1:j+1], s[j+1:k+1], s[k+1:]+s[:i+1]
        if ra:
            A = [rev_map[x] for x in reversed(A)]
        if rb:
            B = [rev_map[x] for x in reversed(B)]
        candidate = C+(B+A if swap else A+B)
        z = candidate.index(0)
        candidate = candidate[z:]+candidate[:z]
        if actual(candidate) >= actual(s)-1e-9:
            raise RuntimeError('3-opt增量评估与完整有向路径成本不一致')
        s = candidate
    gain = original-actual(s)
    if len(cache) >= 50000:
        cache.clear()
    cache[key] = (tuple(s[1:]), gain)
    cache[tuple(s[1:])] = (tuple(s[1:]), 0.)
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
    # A view of preallocated history avoids copying all previous matrices every iteration.
    history = np.empty((iterations, n, n)) if fractional and mode == 1 else None
    convergence, cache = [], {}
    same_group = group_of[:, None] == group_of[None, :]
    rev = build_reverse_node_map(nodes) if local else None
    coeffs = gruenwald_letnikov_coeffs(order, G)
    best, best_value, best_it = None, math.inf, -1
    improvements = hits = 0
    rho_start = rho_end = None
    for it in range(iterations):
        checkpoint("FA3ACO迭代", it+1, iterations, force=(it == 0))
        rho = evaporation_rate(it, rmin, rmax, decay) if adaptive else fixed
        if it == 0:
            rho_start = rho
        rho_end = rho
        effective = tau
        if fractional and mode == 1 and it:
            effective = tau + memory_strength*fractional_pheromone_integral(history[:it], order)
        log_scores = transition_log_scores(effective, cost, alpha, beta)
        tours = []
        for ant in range(ants):
            checkpoint(f"FA3ACO 第{it+1}/{iterations}代：构建/3-opt蚂蚁", ant+1, ants)
            start = int(rng.randint(n))
            route = [start]
            available = ~same_group[start].copy()
            for _ in range(G-1):
                cand = np.flatnonzero(available)
                cur = route[-1]
                prob = probabilities_from_logs(log_scores[cur, cand])
                if fractional and mode == 0 and len(route) > 1:
                    for k, h in enumerate(reversed(route[:-1]), 1):
                        prob += coeffs[k-1]*probabilities_from_logs(log_scores[h, cand])
                    if np.any(prob < -1e-12) or not np.isfinite(prob.sum()) or prob.sum() <= 0:
                        raise ValueError("Wu Eq.16 原式产生负转移概率；原文未给出合法化规则。"
                                         "fractional_mode=1 可选择作者公开的历史信息素积分实现，"
                                         "fractional_order=0 可关闭分数阶项。")
                    prob = np.maximum(prob, 0)  # 仅清除 [-1e-12,0) 浮点误差
                    prob /= prob.sum()
                nxt = int(rng.choice(cand, p=prob))
                route.append(nxt)
                available[same_group[nxt]] = False
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
            history[it] = tau
        convergence.append(best_value)
    checkpoint("FA3ACO迭代完成", iterations, iterations, force=True)
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
