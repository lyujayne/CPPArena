# -*- coding: utf-8 -*-
"""多次运行统计：均值/标准差/最优/最差/相对基线改善率。"""
import math
from typing import Dict, List, Optional

import pandas as pd

from compare.metrics import summarize_run, successful_run


def stats_of(values: List[float]) -> dict:
    vals = []
    for value in values:
        try:
            number = float(value)
            if math.isfinite(number):
                vals.append(number)
        except (TypeError, ValueError):
            continue
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
    raw_runs = runs_by_algo
    rows = {'运行状态': {}, '失败运行次数': {}}
    runs_by_algo = {name: [run for run in runs if successful_run(run)]
                    for name, runs in runs_by_algo.items()}
    metric_labels = {
        ("total_distance", "mean"): "总距离均值 (m)",
        ("total_distance", "std"): "总距离标准差",
        ("total_distance", "min"): "总距离最优",
        ("total_distance", "max"): "总距离最差",
        ("total_turns", "mean"): "航向拐点均值",
        ("total_turns", "min"): "航向拐点最少",
        ("runtime", "mean"): "耗时均值 (s)",
    }

    for label in metric_labels.values():
        rows[label] = {}
    for label in ('有效运行次数', '覆盖率均值 (%)', '覆盖率最低 (%)', '未覆盖面积均值 (m²)',
                  '子区域转运距离均值 (m)', '区域外航程均值 (m)', '冗余率均值 (%)',
                  '扫描换行次数均值', '非扫描航程均值 (m)'):
        rows[label] = {}

    # 相对基线改善率
    imp_label = "相对基线距离改善率 (%)"
    rows[imp_label] = {}

    for algo, runs in runs_by_algo.items():
        failed = len(raw_runs[algo])-len(runs)
        rows['运行状态'][algo] = ('部分失败' if runs and failed else '成功' if runs else
                                 '运行失败' if failed else '无运行结果')
        rows['失败运行次数'][algo] = failed
        rows['有效运行次数'][algo] = len(runs)
        if not runs:
            continue
        dists = [r.get("total_distance") for r in runs]
        turns = [r.get("total_turns") for r in runs]
        runtimes = [r.get("runtime") for r in runs]
        rows['有效运行次数'][algo] = len(runs)
        coverage = [(r.get('metadata') or {}).get('coverage', {}) for r in runs]
        ratios = [c['covered_ratio'] for c in coverage if c.get('covered_ratio') is not None]
        missed = [c['uncovered_area_m2'] for c in coverage if c.get('uncovered_area_m2') is not None]
        if ratios:
            rows['覆盖率均值 (%)'][algo] = stats_of(ratios)['mean']*100
            rows['覆盖率最低 (%)'][algo] = float(min(ratios))*100
        if missed:
            rows['未覆盖面积均值 (m²)'][algo] = stats_of(missed)['mean']
        from compare.route_metrics import compute_route_metrics
        route_metrics = [(r.get('metadata') or {}).get('route_metrics') or compute_route_metrics(r) for r in runs]
        for key, label in (('subregion_transfer_m', '子区域转运距离均值 (m)'),
                           ('outside_distance_m', '区域外航程均值 (m)'),
                           ('redundancy_pct', '冗余率均值 (%)'),
                           ('sweep_reversals', '扫描换行次数均值'),
                           ('non_scan_distance_m', '非扫描航程均值 (m)')):
            rows[label][algo] = round(stats_of([m.get(key) for m in route_metrics])['mean'], 2)
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

    df = pd.DataFrame.from_dict(rows, orient="index").reindex(index=list(rows), columns=list(raw_runs))
    return df


def relative_improvement(algo_mean: float, baseline_mean: float) -> float:
    if not baseline_mean:
        return float("nan")
    return (baseline_mean - algo_mean) / baseline_mean * 100.0
