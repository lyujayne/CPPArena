# -*- coding: utf-8 -*-
"""Wu 2025 两阶段框架：PSO最小宽度和分割、牛耕覆盖、FA3ACO。
论文Eq.16与作者公开代码不一致，当前默认作者历史信息素积分核；
挥发率和逐蚂蚁完整3-opt按论文实现。不是未经限定的“完整复刻”。
见 PAPER_ALIGNMENT.md 及算法metadata中的具体假设。"""
from config.default_params import ALGORITHM_DEFAULTS
from algorithms.aco import ACOGTSPAlgorithm
from algorithms.aco.pso_decomp import pso_convex_decompose
from algorithms.aco.fa3aco_gtsp import solve_fa3aco_gtsp


class PSOFA3ACOAlgorithm(ACOGTSPAlgorithm):
    name = "PSO-FA3ACO"
    display_name = "PSO-FA3ACO（论文框架/作者记忆核）"
    description = ("Wu论文PSO分割与FA3ACO框架；默认使用作者公开历史信息素积分，"
                   "按论文实现自适应挥发和完整3-opt。原式核验模式遇负概率会报错，"
                   "具体差异见PAPER_ALIGNMENT.md。")
    default_params = ALGORITHM_DEFAULTS["PSO-FA3ACO"]
    deterministic = False

    def decompose_region(self, vertices, params):
        """子问题 1：论文 PSO-DCAS 粒子群动态凹区域分割。"""
        seed = int((params or {}).get("seed", 42))
        pieces, info = pso_convex_decompose(vertices, params=params, seed=seed)
        return pieces, info

    def solve_region_order(self, nodes, params, seed):
        """子问题 3：论文 FA3ACO（分数阶转移 + 自适应蒸发 + 3-opt）。"""
        return solve_fa3aco_gtsp(nodes, params=params, seed=seed)

    def get_param_spec(self):
        """参数面板：PSO 分割参数在前，FA3ACO 求解器参数在后。"""
        d = self.default_params
        pso_spec = [
            ("pso_swarm_size", "PSO 种群规模 M", "int", int(d["pso_swarm_size"])),
            ("pso_iterations", "PSO 最大迭代次数", "int", int(d["pso_iterations"])),
            ("pso_w_max", "惯性权重上限 w_max", "float", float(d["pso_w_max"])),
            ("pso_w_min", "惯性权重下限 w_min", "float", float(d["pso_w_min"])),
            ("pso_c1", "个体学习因子 c1", "float", float(d["pso_c1"])),
            ("pso_c2", "群体学习因子 c2", "float", float(d["pso_c2"])),
            ("pso_vmax_ratio", "速度上限比例(×角度跨度)", "float",
             float(d["pso_vmax_ratio"])),
            ("pso_warm_start", "平分线热启动(1开/0关)", "int",
             int(bool(d["pso_warm_start"]))),
            ("pso_merge_slivers", "合并退化碎块(1开/0关)", "int",
             int(bool(d["pso_merge_slivers"]))),
            ("pso_sliver_diag_ratio", "碎块阈值(×对角线)", "float",
             float(d["pso_sliver_diag_ratio"])),
        ]
        fa_spec = [
            ("ants_count", "蚁群蚂蚁数 m", "int", int(d["ants_count"])),
            ("max_iterations", "蚁群最大迭代次数", "int", int(d["max_iterations"])),
            ("alpha", "信息素权重 α", "float", float(d["alpha"])),
            ("beta", "距离权重 β", "float", float(d["beta"])),
            ("Q", "信息素沉积量 Q", "float", float(d["Q"])),
            ("fractional_order", "启用分数阶记忆", "int",
             int(bool(d["fractional_order"]))),
            ("fractional_mode", "分数阶模式(1作者积分/0原式核验)", "int", int(d["fractional_mode"])),
            ("memory_strength", "作者积分记忆强度", "float", float(d["memory_strength"])),
            ("mu", "分数阶阶数 μ∈(0,1)", "float", float(d["mu"])),
            ("adaptive_rho", "自适应蒸发率(Eq.18)", "int",
             int(bool(d["adaptive_rho"]))),
            ("rho_max", "蒸发率上限 ρ_max(初期)", "float", float(d["rho_max"])),
            ("rho_min", "蒸发率下限 ρ_min(后期)", "float", float(d["rho_min"])),
            ("rho_decay_k", "蒸发衰减系数 k", "float", float(d["rho_decay_k"])),
            ("rho_fixed", "固定蒸发率(关闭自适应时)", "float", float(d["rho_fixed"])),
            ("use_three_opt", "3-opt 局部搜索(Alg.3)", "int",
             int(bool(d["use_three_opt"]))),
            ("tau0", "信息素初值(正数)", "float", float(d["tau0"])),
        ]
        return pso_spec + fa_spec


def register():
    from core.registry import get_registry
    return get_registry().register(PSOFA3ACOAlgorithm)
