# -*- coding: utf-8 -*-
"""插件示例：水平扫描覆盖算法。

将本文件放入 algorithms/plugins/ 目录即被平台自动识别并参与比较，
无需修改平台核心代码。复制本文件并修改类名/name 即可注册新算法。
"""
import time

from core.base_algorithm import BaseCPPAlgorithm, CPPInput, CPPResult
from algorithms.common import plan_all_regions, best_connection, assemble
from compare.metrics import count_turns


class HorizontalScanPluginAlgorithm(BaseCPPAlgorithm):
    name = "水平扫描 (插件示例)"
    display_name = "水平扫描（插件示例）"
    description = ("扩展算法示例：固定水平方向做牛耕式扫描（不按论文最优方向），"
                   "演示插件机制——复制本文件即可注册新算法参与比较。")
    default_params = {"seed": 42}
    deterministic = True

    def solve(self, cpp_input: CPPInput, **params) -> CPPResult:
        import numpy as np
        t0 = time.perf_counter()
        seed = int(params.get("seed", 42))
        regions = cpp_input.regions
        launch = cpp_input.launch_point
        line_spacing = cpp_input.camera.line_spacing
        fixed_dir = np.array([1.0, 0.0])  # 固定水平方向

        plans = plan_all_regions(regions, line_spacing, fixed_direction=fixed_dir)
        region_order = [r.id for r in regions]
        chosen = {}
        internal_paths = []
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
            metadata={"algorithm": self.name, "plugin": True,
                      "direction": "horizontal"},
        )
