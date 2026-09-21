# -*- coding: utf-8 -*-
"""贪心最近邻基线算法：按「距当前位置最近的未访问区域」确定访问顺序。

内部覆盖沿用统一的牛耕式方案（与 ACO 相同的凸分解与相机口径），
仅在区域访问顺序上使用贪心启发，保证比较公平。
"""
import math
import time
from typing import List

from core.base_algorithm import BaseCPPAlgorithm, CPPInput, CPPResult
from config.default_params import ALGORITHM_DEFAULTS
from algorithms.common import plan_all_regions, best_connection, assemble
from compare.metrics import count_turns


class GreedyNearestAlgorithm(BaseCPPAlgorithm):
    name = "贪心最近邻"
    display_name = "贪心最近邻（对照基线）"
    description = ("确定性对照算法：从起飞点出发，每次选择距当前位置最近的"
                   "未访问区域，并以入口点最近的方式进入该区域。")
    default_params = ALGORITHM_DEFAULTS["贪心最近邻"]
    deterministic = True

    def solve(self, cpp_input: CPPInput, **params) -> CPPResult:
        t0 = time.perf_counter()
        seed = int(params.get("seed", 42))
        regions = cpp_input.regions
        launch = cpp_input.launch_point
        line_spacing = cpp_input.camera.line_spacing

        plans = plan_all_regions(regions, line_spacing)

        unvisited = {r.id for r in regions}
        region_order: List[int] = []
        chosen = {}
        internal_paths: List[List] = []
        pos = launch

        while unvisited:
            best_rid, best_plan, best_d = None, None, float("inf")
            for r in regions:
                if r.id not in unvisited:
                    continue
                plan, d = best_connection(pos, plans[r.id])
                if d < best_d - 1e-12:
                    best_rid, best_plan, best_d = r.id, plan, d
            chosen[best_rid] = best_plan
            region_order.append(best_rid)
            unvisited.discard(best_rid)
            pos = best_plan.exit

        waypoints, total_distance = assemble(launch, region_order, chosen, internal_paths)
        runtime = time.perf_counter() - t0
        return CPPResult(
            waypoints=waypoints,
            total_distance=float(total_distance),
            total_turns=int(count_turns(waypoints)),
            region_order=region_order,
            internal_paths=internal_paths,
            convergence=[],
            runtime=runtime,
            seed=seed,
            algorithm_name=self.name,
            metadata={"algorithm": "贪心最近邻", "heuristic": "最近邻",
                      "n_regions": len(regions)},
        )


def register():
    from core.registry import get_registry
    return get_registry().register(GreedyNearestAlgorithm)
