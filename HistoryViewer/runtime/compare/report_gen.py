# -*- coding: utf-8 -*-
"""论文写作辅助：对比表格（LaTeX booktabs）、实验报告、数据导出。"""
import csv
import datetime
import json
import os
from typing import Dict, List, Optional

import pandas as pd

from compare.statistics import build_comparison_table, stats_of


def latex_booktabs(df: pd.DataFrame, caption: str = "算法对比实验结果",
                   label: str = "tab:cpp_compare") -> str:
    """将对比表导出为 booktabs 风格 LaTeX 源码（可直接粘贴进论文）。"""
    lines = [
        "\\begin{table}[htbp]",
        "    \\centering",
        f"    \\caption{{{caption}}}",
        f"    \\label{{{label}}}",
        "    \\begin{tabular}{l" + "c" * max(1, len(df.columns)) + "}",
        "        \\toprule",
        "        指标 & " + " & ".join(str(c) for c in df.columns) + " \\\\",
        "        \\midrule",
    ]
    for idx, row in df.iterrows():
        vals = []
        for c in df.columns:
            v = row[c]
            if isinstance(v, (int, float)) and not pd.isna(v):
                vals.append(f"{v:g}")
            else:
                vals.append("--")
        lines.append(f"        {idx} & " + " & ".join(vals) + " \\\\")
    lines += [
        "        \\bottomrule",
        "    \\end{tabular}",
        "\\end{table}",
    ]
    return "\n".join(lines)


def export_csv(df: pd.DataFrame, path: str):
    df.to_csv(path, encoding="utf-8-sig")


def export_json(data, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def algorithm_description(meta: dict, params: dict) -> str:
    """自动生成 Methods 章节的算法流程描述。"""
    lines = [f"**{meta.get('display_name', meta.get('name', ''))}**"]
    if meta.get("description"):
        lines.append(meta["description"])
    if meta.get("citation"):
        lines.append(f"文献引用：{meta['citation']}")
    if meta.get("scope"):
        lines.append(f"适用范围：{meta['scope']}")
    if params:
        pstr = ", ".join(f"{k}={v}" for k, v in params.items() if k != "seed")
        if pstr:
            lines.append(f"主要参数：{pstr}")
    if meta.get("params_note"):
        lines.append(meta["params_note"])
    return "\n\n".join(lines)


def generate_report(project_name: str, camera: dict, runs_by_algo: Dict[str, List[dict]],
                    baseline: Optional[str], algos_meta: dict,
                    params_by_algo: dict, seeds: List[int],
                    figures: Optional[List[str]] = None) -> str:
    """生成实验章节素材（Markdown 报告）。"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md = [f"# {project_name} —— 实验记录报告", "",
          f"- 生成时间：{now}", f"- 随机种子：{seeds}", ""]

    # 相机参数
    md += ["## 1. 实验配置（相机与飞行参数）", "",
           "| 参数 | 值 |", "| --- | --- |"]
    for k, v in camera.items():
        md.append(f"| {k} | {v} |")
    md += [""]

    # 算法描述
    md += ["## 2. 算法描述（Methods 素材）", ""]
    for algo in runs_by_algo:
        meta = dict(algos_meta.get(algo, {}))
        meta.setdefault('display_name', algo)
        actual = next((r.get('params') for r in runs_by_algo[algo] if r.get('params')), {})
        md.append(algorithm_description(meta, actual or params_by_algo.get(algo, {})))
        md.append("")

    # 结果表
    df = build_comparison_table(runs_by_algo, baseline=baseline)
    md += ["## 3. 对比结果表", "", markdown_table(df), "",
           '开放子区连接距离只计算相邻访问子区的出口到入口，不含内部扫描及起降返航；完整任务距离包含这些部分。', '']
    md += [f'距离基线：{baseline or "未设置（改善率不计算）"}。改善率=(基线均值−此组合均值)/基线均值×100%。', '']
    from compare.route_metrics import METRIC_HELP
    md += ['### 路线指标定义', ''] + [f'- {key}：{value}' for key, value in METRIC_HELP.items()] + ['']
    md += ['转弯和非作业航程的评价方向参考 R-DFS (Remote Sensing, 2021)：https://www.mdpi.com/2072-4292/13/8/1525 。'
           '本平台按上述明确的几何定义实现；没有根据这些数值推算能耗。', '']

    # LaTeX
    md += ["## 4. LaTeX 表格源码（booktabs）", "",
           "```latex", latex_booktabs(df), "```", ""]

    # 收敛与图
    if figures:
        md += ["## 5. 图表", ""]
        for fig in figures:
            md.append(f"![{fig}]({fig})")
        md += [""]

    # 明细
    md += ["## 6. 单次运行明细", ""]
    for algo, runs in runs_by_algo.items():
        md.append(f"### {algo}")
        for r in runs:
            if r.get('error'):
                md.append(f"- seed={r.get('seed', '--')}: 运行失败：{r['error']}")
                continue
            md.append(f"- seed={r.get('seed', '--')}: 距离 {r.get('total_distance', 0):.2f} m, "
                      f"航向拐点 {r.get('total_turns', '--')}, 耗时 {r.get('runtime', 0):.3f} s")
            metadata = r.get('metadata') or {}
            if metadata.get('coverage'):
                md.append(f"  - 扫描足迹覆盖率：{metadata['coverage'].get('covered_ratio', '--')}；"
                          f"未覆盖面积：{metadata['coverage'].get('uncovered_area_m2', '--')} m²")
            if metadata.get('gtsp', {}).get('paper_extension'):
                md.append('  - ' + metadata['gtsp']['paper_extension'])
        md.append("")
    return "\n".join(md)


def markdown_table(df):
    """Render a portable summary without pandas' optional tabulate dependency."""
    def cell(value):
        if pd.isna(value):
            return '--'
        return str(value).replace('|', '\\|').replace('\n', ' ')
    lines = ['| 指标 | ' + ' | '.join(map(cell, df.columns)) + ' |',
             '| --- | ' + ' | '.join('---' for _ in df.columns) + ' |']
    lines.extend('| ' + cell(index) + ' | ' + ' | '.join(cell(v) for v in row) + ' |'
                 for index, row in df.iterrows())
    return '\n'.join(lines)


def save_runs_json(runs_by_algo: Dict[str, List[dict]], path: str):
    export_json(runs_by_algo, path)


def load_runs_json(path: str) -> Dict[str, List[dict]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
