# -*- coding: utf-8 -*-
"""统一指标计算（公平比较口径）。

所有算法的 total_distance / total_turns / runtime 均在本模块统一定义，
消除跨算法实现差异。
"""
import math
from typing import List, Tuple

XY = Tuple[float, float]
TURN_ANGLE_THRESHOLD_DEG = 5.0


def successful_run(run):
    try:
        return not run.get('error') and math.isfinite(float(run.get('total_distance', float('nan'))))
    except (TypeError, ValueError):
        return False


def path_length(waypoints: List[XY]) -> float:
    """航点序列总长度 (m)。"""
    return float(sum(
        math.hypot(waypoints[i + 1][0] - waypoints[i][0],
                   waypoints[i + 1][1] - waypoints[i][1])
        for i in range(len(waypoints) - 1)))


def count_turns(waypoints: List[XY],
                threshold_deg: float = TURN_ANGLE_THRESHOLD_DEG) -> int:
    """几何口径转弯次数：航向变化超过阈值的拐点计数。

    对航点序列逐三角判断航向角变化，避免依赖具体算法实现。
    """
    cleaned = []
    for point in waypoints:
        if not cleaned or math.dist(point, cleaned[-1]) >= 1e-9:
            cleaned.append(point)
    waypoints = cleaned
    if len(waypoints) < 3:
        return 0
    thresh = math.radians(threshold_deg)
    turns = 0
    for i in range(1, len(waypoints) - 1):
        v1 = (waypoints[i][0] - waypoints[i - 1][0],
              waypoints[i][1] - waypoints[i - 1][1])
        v2 = (waypoints[i + 1][0] - waypoints[i][0],
              waypoints[i + 1][1] - waypoints[i][1])
        n1 = math.hypot(*v1)
        n2 = math.hypot(*v2)
        if n1 < 1e-9 or n2 < 1e-9:
            continue
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        angle = abs(math.atan2(cross, dot))
        if angle > thresh:
            turns += 1
    return turns


def summarize_run(result) -> dict:
    """从 CPPResult 提取标准指标字典。"""
    return {
        "seed": int(result.seed),
        "total_distance": float(result.total_distance),
        "total_turns": int(result.total_turns),
        "runtime": float(result.runtime),
        "algorithm": getattr(result, "algorithm_name", ""),
        "convergence": list(getattr(result, "convergence", []) or []),
    }
