# -*- coding: utf-8 -*-
"""多次运行统计：均值/标准差/最优/最差/相对基线改善率。"""
import math
from typing import Dict, List, Optional

import pandas as pd

from compare.metrics import summarize_run


def stats_of(values: List[float]) -> dict:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"mean": float("nan"), "std": float("nan"),
                "min": float("nan"), "max": float("nan")}
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    return {"mean": mean, "std": math.sqrt(var),
            "min": min(vals), "max": max(vals)}


def build_comparison_table(runs_by_algo: Dict[str, List[dict]],
                           baseline: Optional[str] = None) -> pd.DataFrame:
    """将「算法名 → 多次运行结果字典列表」汇总为对比表。

    行 = 指标（距离/转弯/耗时 的均值/标准差/最优/最差 + 相对基线改善率），
    列 = 算法。
    """
    rows = {}
    metric_labels = {
        ("total_distance", "mean"): "总距离均值 (m)",
        ("total_distance", "std"): "总距离标准差",
        ("total_distance", "min"): "总距离最优",
        ("total_distance", "max"): "总距离最差",
        ("total_turns", "mean"): "转弯次数均值",
        ("total_turns", "min"): "转弯次数最优",
        ("runtime", "mean"): "耗时均值 (s)",
    }

    for label in metric_labels.values():
        rows[label] = {}

    # 相对基线改善率
    imp_label = "相对基线距离改善率 (%)"
    rows[imp_label] = {}

    for algo, runs in runs_by_algo.items():
        if not runs:
            continue
        dists = [r["total_distance"] for r in runs]
        turns = [r["total_turns"] for r in runs]
        runtimes = [r["runtime"] for r in runs]
        sd, st = stats_of(dists), stats_of(turns)
        rows[metric_labels[("total_distance", "mean")]][algo] = round(sd["mean"], 2)
        rows[metric_labels[("total_distance", "std")]][algo] = round(sd["std"], 2)
        rows[metric_labels[("total_distance", "min")]][algo] = round(sd["min"], 2)
        rows[metric_labels[("total_distance", "max")]][algo] = round(sd["max"], 2)
        rows[metric_labels[("total_turns", "mean")]][algo] = round(st["mean"], 1)
        rows[metric_labels[("total_turns", "min")]][algo] = round(st["min"], 0)
        rows[metric_labels[("runtime", "mean")]][algo] = round(stats_of(runtimes)["mean"], 3)

    if baseline and baseline in runs_by_algo and runs_by_algo[baseline]:
        base_mean = stats_of([r["total_distance"] for r in runs_by_algo[baseline]])["mean"]
        if base_mean and base_mean > 0:
            for algo in runs_by_algo:
                if not runs_by_algo[algo]:
                    continue
                m = stats_of([r["total_distance"] for r in runs_by_algo[algo]])["mean"]
                rows[imp_label][algo] = round((base_mean - m) / base_mean * 100.0, 2)
            rows[imp_label][baseline] = 0.0

    df = pd.DataFrame.from_dict(rows, orient="index")
    return df


def relative_improvement(algo_mean: float, baseline_mean: float) -> float:
    if not baseline_mean:
        return float("nan")
    return (baseline_mean - algo_mean) / baseline_mean * 100.0
