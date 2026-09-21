# -*- coding: utf-8 -*-
"""ACO-GTSP 基准算法（严格对齐论文三步法）。

子问题1：凹多边形贪心凸分解 → 若干凸子区域
子问题2：逐区域牛耕式路径生成 → 每区域 4 种进出点方案
子问题3：E-GTSP 建模 + ACO 求解 → 最优区域访问顺序
"""
import random
import time

import numpy as np

from core.base_algorithm import BaseCPPAlgorithm, CPPInput, CPPResult
from config.default_params import ALGORITHM_DEFAULTS

from algorithms.aco.polygon_decomp import convex_decompose
from algorithms.aco.boustrophedon import plan_region_variants, RegionCoverPlan
from algorithms.aco.aco_gtsp import GTSPNode, solve_aco_gtsp


class ACOGTSPAlgorithm(BaseCPPAlgorithm):
    name = "ACO-GTSP"
    display_name = "ACO-GTSP（论文基准）"
    description = ("蚁群优化求解等约束广义旅行商问题（E-GTSP）的覆盖路径规划，"
                   "严格对齐基准论文三步法：凹多边形贪心凸分解 → 各凸子区域牛耕式"
                   "内部路径（每区域 4 种进出点方案）→ ACO 优化区域访问顺序。")
    default_params = ALGORITHM_DEFAULTS["ACO-GTSP"]
    deterministic = False

    def solve(self, cpp_input: CPPInput, **params) -> CPPResult:
        t0 = time.perf_counter()
        seed = int(params.get("seed", 42))
        random.seed(seed)
        np.random.seed(seed)

        cam = cpp_input.camera
        line_spacing = cam.line_spacing
        launch = cpp_input.launch_point

        # ---- 子问题 1+2：逐区域分解 + 生成 4 种内部方案 ----
        subregion_plans: dict = {}   # region_id -> list[list[RegionCoverPlan]]
        subregion_counts = {}
        decomp_info = []
        for region in cpp_input.regions:
            convex_parts = convex_decompose(region.vertices)
            plans_by_sub = []
            for sub_idx, sub_pts in enumerate(convex_parts):
                variants = plan_region_variants(sub_pts, line_spacing)
                if not variants:
                    raise RuntimeError(f"区域「{region.name}」无法生成覆盖路径")
                plans_by_sub.append(variants)
            subregion_plans[region.id] = plans_by_sub
            subregion_counts[region.id] = len(plans_by_sub)
            decomp_info.append({"region": region.name,
                                "n_subregions": len(plans_by_sub)})

        # ---- 子问题 3：E-GTSP 建模 + ACO 求解 ----
        nodes: list = [GTSPNode(index=0, region_id=-1, subregion_id=0,
                                entry=launch, exit=launch,
                                internal_distance=0.0, path=[])]
        sub_id_counter = 1
        node_by_sub: dict = {}
        for region in cpp_input.regions:
            for variants in subregion_plans[region.id]:
                for v in variants:
                    nd = GTSPNode(index=len(nodes), region_id=region.id,
                                  subregion_id=sub_id_counter,
                                  entry=v.entry, exit=v.exit,
                                  internal_distance=v.internal_distance,
                                  path=v.path)
                    nodes.append(nd)
                    node_by_sub.setdefault(sub_id_counter, []).append(nd)
                sub_id_counter += 1

        visit, convergence, stats = solve_aco_gtsp(
            nodes, params=params, seed=seed)

        # ---- 组装全局结果 ----
        region_order = []
        internal_paths = []
        chosen_variants = {}
        waypoints = [launch]
        for nd_idx in visit:
            nd = nodes[nd_idx]
            if nd.region_id < 0:
                continue
            region_order.append(nd.region_id)
            internal_paths.append(nd.path)
            chosen_variants.setdefault(nd.region_id, []).append(nd.subregion_id)
            if waypoints and waypoints[-1] != nd.path[0]:
                waypoints.append(nd.path[0])
            waypoints.extend(nd.path[1:])
        waypoints.append(launch)

        total_distance = sum(
            np.hypot(waypoints[k + 1][0] - waypoints[k][0],
                     waypoints[k + 1][1] - waypoints[k][1])
            for k in range(len(waypoints) - 1))
        # 转弯次数（几何口径，由 metrics 统一定义）
        from compare.metrics import count_turns
        total_turns = count_turns(waypoints)

        runtime = time.perf_counter() - t0
        metadata = {
            "algorithm": "ACO-GTSP",
            "decomposition": decomp_info,
            "n_subregions_total": sum(subregion_counts.values()),
            "subregion_counts": subregion_counts,
            "gtsp": stats,
            "chosen_subregions_per_region": {
                str(k): v for k, v in chosen_variants.items()},
            "note": "α=0.5, β=20, ρ=0.7, Q=1 为论文穷举最优参数组合",
        }
        return CPPResult(
            waypoints=waypoints,
            total_distance=float(total_distance),
            total_turns=int(total_turns),
            region_order=region_order,
            internal_paths=internal_paths,
            convergence=convergence,
            runtime=runtime,
            seed=seed,
            algorithm_name=self.name,
            metadata=metadata,
        )


def register():
    from core.registry import get_registry
    return get_registry().register(ACOGTSPAlgorithm)
