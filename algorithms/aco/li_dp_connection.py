# -*- coding: utf-8 -*-
"""Li 2011 §5 Eq.32/34: adjacency-restricted open traversal.

Choose starting/ending subregions, visit each once. DP tracks the actual coverage
variant so incoming and outgoing endpoints remain coupled. External launch and
return legs are assembled by the application and excluded from this objective.
The application constructs boundary joints on the two width support lines and
connects them to executable scans. Pairing follows the actual scan parity;
the paper's nturn naming is ambiguous. No silent heuristic fallback.
"""
import math
import time
import numpy as np
from core.execution_control import checkpoint
from shapely.geometry import Polygon
from algorithms.aco.aco_gtsp import build_cost_matrix, validate_visit

MAX_DP_GROUPS = 16


def li_adjacency_cost(nodes, restrict=True):
    groups = {}
    polygons = {}
    for node in nodes[1:]:
        groups.setdefault(node.subregion_id, []).append(node.index)
        if node.polygon:
            polygons[node.subregion_id] = Polygon(node.polygon)
    if set(groups) != set(polygons):
        raise ValueError("Li Eq.32 需要每个子区的多边形，以验证邻接关系")
    cost = build_cost_matrix(nodes)
    adjacent = {}
    for a in groups:
        for b in groups:
            if a == b:
                continue
            # 仅数值容差：原多边形切割产生的共享顶点可能相差约 1e-12 m。
            adjacent[a, b] = polygons[a].distance(polygons[b]) <= 1e-7
            if restrict and not adjacent[a, b]:
                cost[np.ix_(groups[a], groups[b])] = math.inf
    cost[0, :] = cost[:, 0] = math.inf
    return cost, groups, adjacent


def solve_li_dp_connection(nodes, params, seed=42):
    start_time = time.perf_counter()
    mode = int(params.get('li_adjacency_mode', 1))
    if mode not in (0, 1):
        raise ValueError('DP 转场约束只能为 0（通用转场）或 1（严格论文邻接）')
    strict = mode == 1
    cost, groups, adjacent = li_adjacency_cost(nodes, restrict=strict)
    gids = sorted(groups)
    G, n = len(gids), len(nodes)
    if not G:
        raise ValueError("Li-DP 至少需要一个子区")
    max_groups = int(params.get("dp_max_groups", MAX_DP_GROUPS))
    if G > max_groups:
        raise ValueError(f"Li 精确 DP 有 {G} 个子区，超过上限 {max_groups}；"
                         "状态规模指数增长。请提高上限或选择其他算法；不自动返回近似或漏覆盖路径。")
    start = int(params.get("li_start_group", 0)) or None
    end = int(params.get("li_end_group", 0)) or None
    if ((start is not None and start not in groups) or
            (end is not None and end not in groups) or
            (G > 1 and start is not None and start == end)):
        raise ValueError("Li 开放遍历起终子区编号无效，多个子区时起终点必须不同")
    if strict and G > 1:
        reached, pending = set(), [gids[0]]
        while pending:
            group = pending.pop()
            if group in reached:
                continue
            reached.add(group)
            pending.extend(g for g in gids if adjacent.get((group, g), False) and g not in reached)
        leaves = [g for g in gids if sum(adjacent.get((g, h), False) for h in gids) == 1]
        if len(reached) != G:
            raise ValueError('严格邻接 DP：子区图不连通，不存在覆盖全部子区的邻接遍历；调整起终编号无济于事。'
                             '若允许地块间转场，请将“转场约束”设为 0；严格模式不会自动放宽约束。')
        if len(leaves) > 2:
            raise ValueError(f'严格邻接 DP：图中有 {len(leaves)} 个叶子子区 {leaves}，不存在每区恰好一次的开放遍历。'
                             '若允许跨子区转场，请将“转场约束”设为 0。')
    if G >= 25 or (1 << G)*n > 32_000_000:
        raise ValueError(f'精确 DP 的 {G} 个子区需要过大的状态表；请减少分割数量或使用 ACO/FA3ACO。')
    bits = {g: 1 << i for i, g in enumerate(gids)}
    full = (1 << G)-1
    dp = np.full((1 << G, n), math.inf)
    parent = {}
    for group in ([start] if start is not None else gids):
        if G > 1 and group == end:
            continue
        for v in groups[group]:
            dp[bits[group], v] = 0.
    for mask in range(1 << G):
        if mask % 64 == 0:
            checkpoint("精确DP状态", mask, 1 << G)
        for last in np.flatnonzero(np.isfinite(dp[mask])):
            for g in gids:
                if mask & bits[g] or (g == end and (mask | bits[g]) != full):
                    continue
                if strict and not adjacent.get((nodes[last].subregion_id, g), False):
                    continue
                new = mask | bits[g]
                for v in groups[g]:
                    value = dp[mask, last]+cost[last, v]
                    if value < dp[new, v]:
                        dp[new, v] = value
                        parent[new, v] = int(last)
    endings = groups[end] if end is not None else [v for g in gids for v in groups[g]]
    last = min(endings, key=lambda v: dp[full, v])
    best = float(dp[full, last])
    if not math.isfinite(best):
        raise ValueError("Li 邻接图在指定起终子区之间不存在每区恰好一次的遍历；"
                         "起终编号为0表示自动选择，但不保证图存在遍历。可检查起终编号，或显式选择转场约束0。"
                         "程序未自动放宽邻接约束或跳过子区。")
    mask, seq = full, []
    while True:
        seq.append(last)
        prev = parent.get((mask, last))
        if prev is None:
            break
        mask &= ~bits[nodes[last].subregion_id]
        last = prev
    seq.reverse()
    validate_visit(nodes, seq)
    inside = sum(nodes[j].internal_distance for j in seq)
    return seq, [best], {
        "solver": "Li2011-DP(adjacency, open, Eq.32/34)" if strict else 'Open-DP(free transfers, Li-style boundary joints)', "exact": True,
        "connection_mode": 'strict_adjacency' if strict else 'free_transfers',
        "paper_extension": None if strict else '允许非邻接子区直接转场；这是通用开放DP扩展，不是论文Eq.32邻接约束。',
        "nonadjacent_transfers": sum(not adjacent.get((nodes[a].subregion_id, nodes[b].subregion_id), False) for a, b in zip(seq, seq[1:])),
        "n_nodes": n, "n_groups": G,
        "start_group": nodes[seq[0]].subregion_id, "end_group": nodes[seq[-1]].subregion_id,
        "endpoint_selection": "user-fixed" if start and end else "DP selects unspecified endpoint(s)",
        "objective": "open_inter_region_distance", "objective_value": best,
        "best_transition_distance": best, "internal_distance_total": inside,
        "launch_return_in_objective": False,
        "implementation_assumptions": [
            "Boundary joints on width support lines (Eq.29/30); pairing follows actual scan parity, paper nturn naming is ambiguous.",
            "Variant-index DP makes entry/exit coupling explicit; paper Eq.34 omits that state."],
        "dp": {"max_groups_threshold": max_groups, "state_cells": (1 << G)*n,
               "runtime_sec": time.perf_counter()-start_time},
    }
