# -*- coding: utf-8 -*-
"""内置算法包：导入即完成内置算法注册。

仅保留论文基准算法 ACO-GTSP；贪心最近邻 / 导入顺序 两个对照基线
及水平扫描插件示例不再注册（文件仍在磁盘上，需要时取消注释即可恢复）。
"""
from core.registry import get_registry

_reg = get_registry()

from algorithms.aco import ACOGTSPAlgorithm          # noqa: E402

# from algorithms.greedy_nearest import GreedyNearestAlgorithm  # noqa: E402
# from algorithms.import_order import ImportOrderAlgorithm      # noqa: E402

_reg.register(ACOGTSPAlgorithm)
# _reg.register(GreedyNearestAlgorithm)
# _reg.register(ImportOrderAlgorithm)

__all__ = ["ACOGTSPAlgorithm"]
