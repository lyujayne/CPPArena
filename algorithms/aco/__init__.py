# -*- coding: utf-8 -*-
"""ACO-GTSP 基准算法（严格对齐论文三步法）。

子问题1：凹多边形贪心凸分解 → 若干凸子区域
子问题2：逐区域牛耕式路径生成 → 每区域 4 种进出点方案
子问题3：E-GTSP 建模 + ACO 求解 → 最优区域访问顺序

子问题 3 的求解器通过 solve_region_order() 钩子调用：基准使用标准
ANT-cycle 蚁群（aco_gtsp，对齐 Kato et al. 2025）；子类可重写该钩子
替换为论文 Wu et al. (2025) 的 FA3ACO（fa3aco_gtsp，分数阶转移 +
自适应蒸发率 + 3-opt），其余编排（分割、牛耕、建模、组装）完全复用。
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

    def decompose_region(self, vertices, params):
        """子问题 1——区域分割钩子（子类可重写以替换分割方式做对比）。

        :return: (凸子区域 CCW 环列表, 分割信息字典)
        基准算法使用 Bayazit 凸分解（poly_decomp 库移植）。
        """
        return convex_decompose(vertices), {"segmentation": "Bayazit(poly_decomp)"}

    def solve_region_order(self, nodes, params, seed):
        """子问题 3 求解器钩子（子类可重写以替换区域访问顺序优化算法）。

        基准：标准 ANT-cycle 蚁群求解 E-GTSP（aco_gtsp，Kato et al. 2025）。
        :return: (最优节点序列[不含起降点], 收敛历史, 统计字典)
        """
        return solve_aco_gtsp(nodes, params=params, seed=seed)

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
        region_convex_polys = {}
        for region in cpp_input.regions:
            convex_parts, seg_info = self.decompose_region(region.vertices, params)
            region_convex_polys[region.id] = convex_parts
            plans_by_sub = []
            for sub_idx, sub_pts in enumerate(convex_parts):
                variants = plan_region_variants(sub_pts, line_spacing)
                if not variants:
                    raise RuntimeError(f"区域「{region.name}」无法生成覆盖路径")
                plans_by_sub.append(variants)
            subregion_plans[region.id] = plans_by_sub
            subregion_counts[region.id] = len(plans_by_sub)
            info_item = {"region": region.name,
                         "n_subregions": len(plans_by_sub)}
            info_item.update(seg_info or {})
            decomp_info.append(info_item)

        # ---- 子问题 3：E-GTSP 建模 + ACO 求解 ----
        nodes: list = [GTSPNode(index=0, region_id=-1, subregion_id=0,
                                entry=launch, exit=launch,
                                internal_distance=0.0, path=[])]
        sub_id_counter = 1
        node_by_sub: dict = {}
        subregion_polys: dict = {}
        for region in cpp_input.regions:
            for sub_idx, variants in enumerate(subregion_plans[region.id]):
                subregion_polys[sub_id_counter] = region_convex_polys[region.id][sub_idx]
                for v in variants:
                    nd = GTSPNode(index=len(nodes), region_id=region.id,
                                  subregion_id=sub_id_counter,
                                  entry=v.entry, exit=v.exit,
                                  internal_distance=v.internal_distance,
                                  path=v.path)
                    nodes.append(nd)
                    node_by_sub.setdefault(sub_id_counter, []).append(nd)
                sub_id_counter += 1

        visit, convergence, stats = self.solve_region_order(
            nodes, params, seed)

        # ---- 组装全局结果 ----
        region_order = []
        internal_paths = []
        subregion_sequence = []
        chosen_variants = {}
        waypoints = [launch]
        seq_order = 0
        for nd_idx in visit:
            nd = nodes[nd_idx]
            if nd.region_id < 0:
                continue
            region_order.append(nd.region_id)
            internal_paths.append(nd.path)
            seq_order += 1
            poly = subregion_polys.get(nd.subregion_id)
            if poly is not None:
                subregion_sequence.append({
                    "order": seq_order,
                    "polygon": [[float(x), float(y)] for x, y in poly],
                })
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
            "algorithm": self.name,
            "decomposition": decomp_info,
            "n_subregions_total": sum(subregion_counts.values()),
            "subregion_counts": subregion_counts,
            "gtsp": stats,
            "chosen_subregions_per_region": {
                str(k): v for k, v in chosen_variants.items()},
            "note": ("α=0.5, β=20, ρ=0.7, Q=1 为论文穷举最优参数组合；"
                     "已按论文随机因子与 ANT-cycle 流程开启前期探索(RCL)、"
                     "余弦衰减与全局最优精英沉积，并以最近邻贪心解兜底。"),
        }
        return CPPResult(
            waypoints=waypoints,
            total_distance=float(total_distance),
            total_turns=int(total_turns),
            region_order=region_order,
            internal_paths=internal_paths,
            subregion_sequence=subregion_sequence,
            convergence=convergence,
            runtime=runtime,
            seed=seed,
            algorithm_name=self.name,
            metadata=metadata,
        )

    def get_param_spec(self):
        """参数面板中文标签与顺序（key, 中文标签, 类型, 默认值）。"""
        d = self.default_params
        return [
            ("alpha", "信息素权重 α", "float", float(d["alpha"])),
            ("beta", "距离权重 β", "float", float(d["beta"])),
            ("rho", "信息素挥发率 ρ", "float", float(d["rho"])),
            ("Q", "信息素沉积量 Q", "float", float(d["Q"])),
            ("max_iterations", "最大迭代次数", "int", int(d["max_iterations"])),
            ("exploration_prob", "初始探索率(余弦衰减,0=关闭)", "float",
             float(d["exploration_prob"])),
            ("rcl_ratio", "RCL受限候选池占比", "float", float(d["rcl_ratio"])),
            ("elite_weight", "全局最优精英沉积权重", "float", float(d["elite_weight"])),
            ("elite_delay", "精英沉积启用迭代占比", "float", float(d["elite_delay"])),
            ("tau0", "信息素初值(<=0自动)", "float", float(d["tau0"])),
        ]


def register():
    from core.registry import get_registry
    return get_registry().register(ACOGTSPAlgorithm)
