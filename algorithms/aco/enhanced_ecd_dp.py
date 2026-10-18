# -*- coding: utf-8 -*-
"""Li 2011 增强分割、宽度支撑线边界连接点、邻接图开放遍历DP。
起终子区可指定；起降航段只计入执行任务里程；超过精确规模上限报错。
Eq.31的nturn记法与实际条带数的区别在 PAPER_ALIGNMENT.md 说明。"""
from config.default_params import ALGORITHM_DEFAULTS
from algorithms.aco import ACOGTSPAlgorithm
from algorithms.aco.enhanced_decomp import enhanced_convex_decompose
from algorithms.aco.li_dp_connection import solve_li_dp_connection
from algorithms.aco.boustrophedon import plan_region_variants


class EnhancedECDDPAlgorithm(ACOGTSPAlgorithm):
    name = "Enhanced-ECD-DP"
    display_name = "增强精确单元分解-DP（Li 邻接开放遍历）"
    description = ("Li 2011增强分割及邻接图开放遍历DP：仅相邻子区可连接，"
                   "可指定起始和结束子区，采用宽度支撑线上的边界连接点。"
                   "起降航段不参与论文连接目标；超上限或不存在遍历时明确报错。")
    default_params = ALGORITHM_DEFAULTS["Enhanced-ECD-DP"]
    deterministic = True   # 分解与 DP 连接均为确定性

    def decompose_region(self, vertices, params):
        """子问题 1：论文增强精确单元分解（§4.3 贪心递归最小宽度和 + §4.5 合并）。"""
        pieces, info = enhanced_convex_decompose(vertices, params=params)
        return pieces, info

    def solve_region_order(self, nodes, params, seed):
        """子问题 3：论文 §5 加权无向图最小遍历 DP（Eq.34）。"""
        return solve_li_dp_connection(nodes, params=params, seed=seed)

    def plan_subregion(self, vertices, line_spacing):
        return plan_region_variants(vertices, line_spacing, boundary_joints=True)

    def get_param_spec(self):
        """参数面板：该精确算法无随机参数，仅暴露 DP 兜底阈值。"""
        d = self.default_params
        return [
            ("dp_max_groups", "精确DP子区上限(超过报错)", "int",
             int(d["dp_max_groups"])),
            ("li_start_group", "起始子区编号(0=自动选择)", "int", int(d["li_start_group"])),
            ("li_end_group", "结束子区编号(0=自动选择)", "int", int(d["li_end_group"])),
        ]


def register():
    from core.registry import get_registry
    return get_registry().register(EnhancedECDDPAlgorithm)
