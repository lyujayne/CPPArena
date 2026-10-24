"""Shared convergence plotting for the comparison view and selected JPEG exports."""
import numpy as np


def draw_convergence(figure, runs_by_algo):
    figure.clear()
    grouped = {}
    for algo, runs in runs_by_algo.items():
        for run in runs:
            objective = (run.get('metadata') or {}).get('gtsp', {}).get('objective', 'mission_total_distance')
            curve = np.asarray(run.get('convergence') or [], dtype=float)
            if curve.size:
                grouped.setdefault(objective, {}).setdefault(algo, []).append(curve)
    if not grouped:
        ax = figure.add_subplot(111)
        ax.text(.5, .5, '暂无有效收敛数据', ha='center', va='center', transform=ax.transAxes)
        ax.set_axis_off()
    for pos, (objective, curves) in enumerate(grouped.items(), 1):
        ax = figure.add_subplot(len(grouped), 1, pos)
        for algo, convs in curves.items():
            mat = np.full((len(convs), max(map(len, convs))), np.nan)
            for i, curve in enumerate(convs):
                mat[i, :len(curve)] = curve
            mean, std = np.nanmean(mat, axis=0), np.nanstd(mat, axis=0)
            x = np.arange(mean.size)
            line, = ax.plot(x, mean, marker='o' if mean.size == 1 else None,
                            linewidth=1.6, label=f'{algo} (n={len(convs)})')
            if len(convs) > 1:
                ax.fill_between(x, mean-std, mean+std, color=line.get_color(), alpha=.15)
        label = ('开放子区连接距离（不含起降/内部）' if objective == 'open_inter_region_distance'
                 else '完整任务距离')
        ax.set_ylabel(label+' (m)')
        ax.set_xlabel('迭代编号 / DP结果')
        ax.set_title(label+'：同目标函数比较')
        ax.grid(True, alpha=.3)
        ax.legend(fontsize=8)
    figure.tight_layout()
