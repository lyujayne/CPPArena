# -*- coding: utf-8 -*-
"""论文完整算法：PSO-FA3ACO（Wu et al. 2025, Scientific Reports）。

论文：Wenxing Wu, Zhigang Wang, Lianhai Lin, Xin Chang, Liqin Tian,
"An efficient coverage path planning method for UAV in complex concave
regions", Scientific Reports 15:37227, DOI 10.1038/s41598-025-20978-8。

两阶段完整复刻（论文 Algorithm 1 的 PSO-FA3ACO 总体框架）：
- **子问题 1 区域分割（§3.1 / Algorithm 2，PSO-DCAS）**：叉积法识别凹点
  （Eq.1-2），每个凹点一个切割方向角粒子维度，以各凸子区**旋转卡壳最小
  宽度之和** min Σw(R_i)（Eq.3/8）为适应度，粒子群（Eq.13/14，w:0.9→0.2、
  c1=c2=2）全局优化切割方向；实现见 pso_decomp.py。
- **子问题 2 区域内覆盖（§3.3）**：各凸子区按最小宽度方向做牛耕式往复
  扫描，每个子区生成 4 种进出点方案；实现沿用 boustrophedon.py（与基准
  相同，论文对区域内扫描的描述与该实现等价）。
- **子问题 3 区域间访问顺序（§4 / Algorithm 3-4，FA3ACO）**：E-GTSP
  建模（每子区 4 个进出方案节点、组内互斥、起降点），由**分数阶蚁群**
  求解——分数阶状态转移（Eq.16，Grünwald–Letnikov 历史记忆）、自适应
  信息素蒸发率 ρ(t)=ρ_min+(ρ_max−ρ_min)e^{−kt}（Eq.18）、逐蚂蚁 3-opt
  局部搜索（Algorithm 3 的 8 种断边重连）；实现见 fa3aco_gtsp.py。

与基准 ACO-GTSP（Bayazit 凸分解 + 标准 ANT-cycle 蚁群，对齐 Kato
et al. 2025）形成完整对比：分割方式与区域间求解器均按 Wu et al. (2025)
替换。三个消融开关 fractional_order / adaptive_rho / use_three_opt
可逐项关闭，复现论文 Table 2 中 ACO、3opt-ACO、fractional-ACO、
Hybrid-ACO、FA3ACO 的消融对比。
"""
from config.default_params import ALGORITHM_DEFAULTS
from algorithms.aco import ACOGTSPAlgorithm
from algorithms.aco.pso_decomp import pso_convex_decompose
from algorithms.aco.fa3aco_gtsp import solve_fa3aco_gtsp


class PSOFA3ACOAlgorithm(ACOGTSPAlgorithm):
    name = "PSO-FA3ACO"
    display_name = "PSO-FA3ACO（文献完整算法）"
    description = ("Wu et al. (2025, Scientific Reports) 完整两阶段算法：粒子群动态"
                   "凹区域分割（PSO-DCAS，叉积法识别凹点、旋转卡壳最小宽度之和为"
                   "适应度）→ 各凸子区牛耕式扫描（4 种进出点方案）→ FA3ACO 分数阶"
                   "蚁群优化区域访问顺序（分数阶状态转移 Eq.16 + 自适应信息素蒸发率"
                   "Eq.18 + 3-opt 局部搜索 Algorithm 3）。")
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
        ]
        fa_spec = [
            ("ants_count", "蚁群蚂蚁数 m", "int", int(d["ants_count"])),
            ("max_iterations", "蚁群最大迭代次数", "int", int(d["max_iterations"])),
            ("alpha", "信息素权重 α", "float", float(d["alpha"])),
            ("beta", "距离权重 β", "float", float(d["beta"])),
            ("Q", "信息素沉积量 Q", "float", float(d["Q"])),
            ("fractional_order", "分数阶状态转移(Eq.16)", "int",
             int(bool(d["fractional_order"]))),
            ("mu", "分数阶阶数 μ∈(0,1)", "float", float(d["mu"])),
            ("adaptive_rho", "自适应蒸发率(Eq.18)", "int",
             int(bool(d["adaptive_rho"]))),
            ("rho_max", "蒸发率上限 ρ_max(初期)", "float", float(d["rho_max"])),
            ("rho_min", "蒸发率下限 ρ_min(后期)", "float", float(d["rho_min"])),
            ("rho_decay_k", "蒸发衰减系数 k", "float", float(d["rho_decay_k"])),
            ("rho_fixed", "固定蒸发率(关闭自适应时)", "float", float(d["rho_fixed"])),
            ("use_three_opt", "3-opt 局部搜索(Alg.3)", "int",
             int(bool(d["use_three_opt"]))),
            ("tau0", "信息素初值(<=0自动)", "float", float(d["tau0"])),
        ]
        return pso_spec + fa_spec


def register():
    from core.registry import get_registry
    return get_registry().register(PSOFA3ACOAlgorithm)
