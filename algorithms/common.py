# -*- coding: utf-8 -*-
"""公共算法工具：区域覆盖方案生成与路径组装（各基线算法共用）。"""
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from algorithms.aco.boustrophedon import plan_region_variants, RegionCoverPlan
from algorithms.aco.polygon_decomp import convex_decompose


def decompose_region_with(algo_name: str, vertices, params: dict = None):
    """按指定算法的子问题 1 分割方式对单个多边形做凸分解（供分解预览/对比复用）。

    算法类实现了 decompose_region(vertices, params) -> (凸子区列表, 信息dict)
    即调用之（ACO-GTSP=Bayazit，PSO-FA3ACO=PSO-DCAS）；未实现该钩子的算法
    回退到 Bayazit 凸分解。
    """
    from core.registry import get_registry
    cls = get_registry().get(algo_name)
    if cls is not None and hasattr(cls, "decompose_region"):
        p = dict(getattr(cls, "default_params", {}) or {})
        if params:
            p.update(params)
        try:
            return cls().decompose_region(vertices, p)
        except Exception:
            pass
    return convex_decompose(vertices), {"segmentation": "Bayazit(poly_decomp)"}


def plan_all_regions(regions, line_spacing: float,
                     fixed_direction=None) -> Dict[int, List[List[RegionCoverPlan]]]:
    """为每个区域的每个凸子区域生成 4 种覆盖方案。"""
    out = {}
    for region in regions:
        convex_parts = convex_decompose(region.vertices)
        plans_by_sub = []
        for sub_pts in convex_parts:
            variants = plan_region_variants(sub_pts, line_spacing,
                                            sweep_dir=fixed_direction)
            if not variants:
                raise RuntimeError(f"区域「{region.name}」无法生成覆盖路径")
            plans_by_sub.append(variants)
        out[region.id] = plans_by_sub
    return out


def best_connection(current: Tuple[float, float],
                    plans_by_sub: List[List[RegionCoverPlan]]
                    ) -> Tuple[RegionCoverPlan, float]:
    """选择入口点距当前位置最近的方案（公平口径：内部距离与转弯次数与 ACO 一致）。"""
    best_plan, best_d = None, float("inf")
    for variants in plans_by_sub:
        for v in variants:
            d = math.hypot(current[0] - v.entry[0], current[1] - v.entry[1])
            if d < best_d - 1e-12:
                best_d, best_plan = d, v
    return best_plan, best_d


def assemble(launch, region_order, chosen: Dict[int, RegionCoverPlan],
             internal_paths) -> Tuple[List[Tuple[float, float]], float]:
    """组装全局航点与总距离。"""
    waypoints = [launch]
    total = 0.0
    pos = launch
    for rid in region_order:
        plan = chosen[rid]
        if waypoints[-1] != plan.entry:
            total += math.hypot(pos[0] - plan.entry[0], pos[1] - plan.entry[1])
            waypoints.append(plan.entry)
        total += plan.internal_distance
        waypoints.extend(plan.path[1:])
        pos = plan.exit
        internal_paths.append(plan.path)
    total += math.hypot(pos[0] - launch[0], pos[1] - launch[1])
    waypoints.append(launch)
    return waypoints, total
