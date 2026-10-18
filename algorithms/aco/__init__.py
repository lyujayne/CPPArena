# -*- coding: utf-8 -*-
"""覆盖规划统一编排：凸分解、足迹完整性验证、四方案覆盖、区域连接和任务航点组装。
Kato 为闭环任务目标；Li 为邻接图开放连接目标，起降航段不参与其优化。"""
import random
import time

import numpy as np

from core.base_algorithm import BaseCPPAlgorithm, CPPInput, CPPResult
from config.default_params import ALGORITHM_DEFAULTS

from algorithms.aco.polygon_decomp import convex_decompose
from algorithms.aco.boustrophedon import (plan_region_variants, RegionCoverPlan,
                                        coverage_geometry, choose_sweep_direction)
from algorithms.aco.aco_gtsp import GTSPNode, solve_aco_gtsp, validate_visit


class ACOGTSPAlgorithm(BaseCPPAlgorithm):
    name = "ACO-GTSP"
    display_name = "ACO-GTSP（论文基准）"
    description = ("蚁群优化求解等约束广义旅行商问题（E-GTSP）的覆盖路径规划，"
                   "按基准论文三步法：凹多边形贪心凸分解 → 各凸子区域牛耕式"
                   "内部路径（每区域 4 种进出点方案）→ ACO 优化区域访问顺序。")
    default_params = ALGORITHM_DEFAULTS["ACO-GTSP"]
    deterministic = False

    def decompose_region(self, vertices, params):
        """子问题 1——区域分割钩子（子类可重写以替换分割方式做对比）。

        :return: (凸子区域 CCW 环列表, 分割信息字典)
        基准算法使用 Bayazit 凸分解（poly_decomp 库移植）。
        """
        seed = int((params or {}).get("seed", 42))
        return convex_decompose(vertices, seed=seed), {"segmentation": "Bayazit(poly_decomp)"}

    def solve_region_order(self, nodes, params, seed):
        """子问题 3 求解器钩子（子类可重写以替换区域访问顺序优化算法）。

        基准：Kato 常数Q沉积蚁群求解 E-GTSP（aco_gtsp，Kato et al. 2025）。
        :return: (最优节点序列[不含起降点], 收敛历史, 统计字典)
        """
        return solve_aco_gtsp(nodes, params=params, seed=seed)

    def plan_subregion(self, vertices, line_spacing):
        return plan_region_variants(vertices, line_spacing)

    def solve(self, cpp_input: CPPInput, **params) -> CPPResult:
        params = dict(self.default_params, **params)
        if not cpp_input.regions or len({r.id for r in cpp_input.regions}) != len(cpp_input.regions):
            raise ValueError("至少需要一个区域，且区域编号必须唯一")
        t0 = time.perf_counter()
        seed = int(params.get("seed", 42))
        random.seed(seed)
        np.random.seed(seed)

        cam = cpp_input.camera
        line_spacing = cam.line_spacing
        launch = cpp_input.launch_point
        from config.default_params import compute_camera
        camera_info = compute_camera(cam.as_dict())
        from shapely.geometry import Polygon
        coverage_records = []

        # ---- 子问题 1+2：逐区域分解 + 生成 4 种内部方案 ----
        subregion_plans: dict = {}   # region_id -> list[list[RegionCoverPlan]]
        subregion_counts = {}
        decomp_info = []
        region_convex_polys = {}
        for region in cpp_input.regions:
            convex_parts, seg_info = self.decompose_region(region.vertices, params)
            from shapely.ops import unary_union
            original = Polygon(region.vertices)
            part_polys = [Polygon(p) for p in convex_parts]
            if not original.is_valid or not part_polys or any(not p.is_valid for p in part_polys):
                raise ValueError(f"区域「{region.name}」或分割结果不是有效多边形")
            union = unary_union(part_polys)
            tolerance = max(1e-6, original.area*1e-9)
            if (union.symmetric_difference(original).area > tolerance or
                    sum(p.area for p in part_polys)-union.area > tolerance):
                raise RuntimeError(f"区域「{region.name}」分割不满足完整覆盖/无重叠约束")
            region_convex_polys[region.id] = convex_parts
            plans_by_sub = []
            for sub_idx, sub_pts in enumerate(convex_parts):
                variants = self.plan_subregion(sub_pts, line_spacing)
                if not variants:
                    raise RuntimeError(f"区域「{region.name}」无法生成覆盖路径")
                plans_by_sub.append(variants)
                direction = choose_sweep_direction(sub_pts)
                covered = coverage_geometry(variants[0], direction,
                    camera_info['coverage_w'], camera_info['coverage_h'])
                poly = Polygon(sub_pts)
                missed = poly.difference(covered).area
                if missed > max(1e-6, poly.area*1e-9):
                    raise RuntimeError(f"区域「{region.name}」的扫描足迹仍有未覆盖面积 {missed:.6f} m²")
                coverage_records.append({"region": region.id, "subregion_index": sub_idx,
                    "area": poly.area, "uncovered_area": missed,
                    "scan_lines": len(variants[0].scan_segments),
                    "sweep_reversals": variants[0].turns})
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
                                  path=v.path, polygon=subregion_polys[sub_id_counter],
                                  variant_id=v.variant_id)
                    nodes.append(nd)
                    node_by_sub.setdefault(sub_id_counter, []).append(nd)
                sub_id_counter += 1

        visit, convergence, stats = self.solve_region_order(
            nodes, params, seed)
        validate_visit(nodes, visit)

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
            "implementation_revision": "paper-alignment-2026-10-18",
            "algorithm": self.name,
            "decomposition": decomp_info,
            "n_subregions_total": sum(subregion_counts.values()),
            "subregion_counts": subregion_counts,
            "gtsp": stats,
            "chosen_subregions_per_region": {
                str(k): v for k, v in chosen_variants.items()},
            "coverage": {"model": "continuous nadir rectangular footprints on scan legs",
                "covered_ratio": 1-sum(r['uncovered_area'] for r in coverage_records)/sum(r['area'] for r in coverage_records),
                "subregions": coverage_records,
                "boundary_handling": "band projection envelope; endpoints may leave polygon; no NFZ assumed",
                "execution_requirement": "camera yaw aligned with sweep; continuous capture or trigger interval <= footprint length"},
            "turn_metrics": {"heading_changes_over_5deg": int(total_turns),
                "sweep_reversals": sum(r['sweep_reversals'] for r in coverage_records),
                "li_eq17_scan_count": sum(r['scan_lines'] for r in coverage_records)},
            "mission_distance": float(total_distance),
            "note": "论文来源、目标函数与无法严格复现的部分见 gtsp.implementation_assumptions；几何拐点与换行次数分别记录。",
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
            ("exploration_prob", "全候选随机探索概率(论文未给值)", "float",
             float(d["exploration_prob"])),
            ("tau0", "信息素初值(论文未给值)", "float", float(d["tau0"])),
        ]


def register():
    from core.registry import get_registry
    return get_registry().register(ACOGTSPAlgorithm)
