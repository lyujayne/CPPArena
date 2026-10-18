# -*- coding: utf-8 -*-
"""第三种切割方式算法：增强精确单元分解 + 标准 ACO 区域访问顺序。

在基准 ACO-GTSP 三步法（凸分解 → 牛耕 → ACO 求解 E-GTSP）的框架下，仅把
子问题 1 的切割方式替换为 Li et al. (2011, Mechatronics 21:876–885) 的
**增强精确单元分解**（论文 §4：过凹顶点作某边平行线、贪心递归最小化各凸子区
宽度之和），子问题 2（牛耕扫描）与子问题 3（标准 ACO E-GTSP）完全沿用基准。

这样第三种"切割方式"作为唯一自变量，与 ① Bayazit（ACO-GTSP）、
② PSO-DCAS（PSO-FA3ACO）在"分解对比"窗口与完整路径实验中并列比较。
"""
from config.default_params import ALGORITHM_DEFAULTS
from algorithms.aco import ACOGTSPAlgorithm
from algorithms.aco.enhanced_decomp import enhanced_convex_decompose


class EnhancedECDACOAlgorithm(ACOGTSPAlgorithm):
    name = "Enhanced-ECD-ACO"
    display_name = "增强精确单元分解-ACO（组合对照）"
    description = ("Li et al. (2011, Mechatronics) 增强精确单元分解：叉积法识别凹点，"
                   "过凹顶点作多边形某条边的平行线，贪心递归最小化各凸子区宽度之和"
                   "（旋转卡壳宽度，§3.2）；各凸子区牛耕式扫描后由标准 ACO 求解"
                   "E-GTSP 区域访问顺序。切割方式为第三种、与基准共用 ACO 后端。")
    default_params = ALGORITHM_DEFAULTS["Enhanced-ECD-ACO"]
    deterministic = False   # 切割为确定性贪心枚举，ACO 仍受 seed 控制

    def decompose_region(self, vertices, params):
        """子问题 1：论文增强精确单元分解（§4.3 贪心递归最小宽度和）。"""
        pieces, info = enhanced_convex_decompose(vertices, params=params)
        return pieces, info


def register():
    from core.registry import get_registry
    return get_registry().register(EnhancedECDACOAlgorithm)
