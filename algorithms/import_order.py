# -*- coding: utf-8 -*-
"""导入顺序基线算法：按用户导入区域顺序依次访问（等价 Mission Planner 行为）。"""
import time
from typing import List

from core.base_algorithm import BaseCPPAlgorithm, CPPInput, CPPResult
from config.default_params import ALGORITHM_DEFAULTS
from algorithms.common import plan_all_regions, best_connection, assemble
from compare.metrics import count_turns


class ImportOrderAlgorithm(BaseCPPAlgorithm):
    name = "导入顺序"
    display_name = "导入顺序（Mission Planner 对照）"
    description = ("确定性对照算法：按用户导入区域顺序依次访问，"
                   "等价 Mission Planner 默认行为，作为论文对照基线。")
    default_params = ALGORITHM_DEFAULTS["导入顺序"]
    deterministic = True

    def solve(self, cpp_input: CPPInput, **params) -> CPPResult:
        t0 = time.perf_counter()
        seed = int(params.get("seed", 42))
        regions = cpp_input.regions
        launch = cpp_input.launch_point
        line_spacing = cpp_input.camera.line_spacing

        plans = plan_all_regions(regions, line_spacing)
        region_order: List[int] = [r.id for r in regions]
        chosen = {}
        internal_paths: List[List] = []
        pos = launch
        for rid in region_order:
            plan, _ = best_connection(pos, plans[rid])
            chosen[rid] = plan
            pos = plan.exit

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
            metadata={"algorithm": "导入顺序",
                      "mission_planner_equivalent": True,
                      "n_regions": len(regions)},
        )


def register():
    from core.registry import get_registry
    return get_registry().register(ImportOrderAlgorithm)
