# -*- coding: utf-8 -*-
"""内置覆盖算法注册。

Kato ACO、Wu框架/作者记忆核、Li增强分割+ACO组合、Li邻接开放DP。
算法假设及不能严格复现的部分见 PAPER_ALIGNMENT.md。
"""
from core.registry import get_registry

_reg = get_registry()

from algorithms.aco import ACOGTSPAlgorithm          # noqa: E402
from algorithms.aco.pso_fa3aco import PSOFA3ACOAlgorithm  # noqa: E402
from algorithms.aco.enhanced_aco import EnhancedECDACOAlgorithm  # noqa: E402
from algorithms.aco.enhanced_ecd_dp import EnhancedECDDPAlgorithm  # noqa: E402

# from algorithms.greedy_nearest import GreedyNearestAlgorithm  # noqa: E402
# from algorithms.import_order import ImportOrderAlgorithm      # noqa: E402

_reg.register(ACOGTSPAlgorithm)
_reg.register(PSOFA3ACOAlgorithm)
_reg.register(EnhancedECDACOAlgorithm)
_reg.register(EnhancedECDDPAlgorithm)
# _reg.register(GreedyNearestAlgorithm)
# _reg.register(ImportOrderAlgorithm)

__all__ = ["ACOGTSPAlgorithm", "PSOFA3ACOAlgorithm", "EnhancedECDACOAlgorithm",
           "EnhancedECDDPAlgorithm"]
