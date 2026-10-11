# -*- coding: utf-8 -*-
"""内置算法包：导入即完成内置算法注册。

保留两个内置算法用于对比：
- ACO-GTSP：Kato et al. (2025) 基准（Bayazit 凸分解 + 牛耕 + 标准蚁群 E-GTSP）；
- PSO-FA3ACO：Wu et al. (2025) 完整两阶段算法（PSO-DCAS 粒子群凹区域分割
  + 牛耕 + FA3ACO 分数阶蚁群：分数阶状态转移 / 自适应蒸发率 / 3-opt）。
贪心最近邻 / 导入顺序两个对照基线及水平扫描插件示例不再注册（文件仍在
磁盘上，需要时取消注释即可恢复）。
"""
from core.registry import get_registry

_reg = get_registry()

from algorithms.aco import ACOGTSPAlgorithm          # noqa: E402
from algorithms.aco.pso_fa3aco import PSOFA3ACOAlgorithm  # noqa: E402

# from algorithms.greedy_nearest import GreedyNearestAlgorithm  # noqa: E402
# from algorithms.import_order import ImportOrderAlgorithm      # noqa: E402

_reg.register(ACOGTSPAlgorithm)
_reg.register(PSOFA3ACOAlgorithm)
# _reg.register(GreedyNearestAlgorithm)
# _reg.register(ImportOrderAlgorithm)

__all__ = ["ACOGTSPAlgorithm", "PSOFA3ACOAlgorithm"]
