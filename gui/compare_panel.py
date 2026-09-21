# -*- coding: utf-8 -*-
"""比较结果面板：多算法对比表格、收敛曲线、统计图表与论文写作辅助导出。

对应需求规格 4.6.2 / 4.6.3 / 4.7 / 4.8：
- 收敛曲线多算法同图叠加（均值 ± 标准差带），标注最优轮次与值；
- 柱状图（距离误差棒）、箱线图（稳定性）、散点图（Pareto 视角）；
- LaTeX（booktabs）表格导出、CSV/JSON 导出、实验报告生成；
- 航点导出（KML/CSV/TXT，可导入 Mission Planner）。
"""
import os

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from compare import report_gen
from compare.statistics import build_comparison_table
from config.default_params import ALGORITHM_META, EXPERIMENT_DIR, APP_NAME
from data.coord_transform import CoordTransform
from data.waypoint_export import export_waypoints


class ComparePanel(QWidget):
    """多算法 × 多数据集 × 多种子的比较与论文辅助导出。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results = {}          # dataset_name -> {algo: [run,...]}
        self._datasets = {}         # dataset_name -> Dataset
        self._camera = {}
        self._baseline = None
        self._algos_meta = {}
        self._params_by_algo = {}
        self._seeds = []
        self._project_name = "未命名工程"

        self._conv_fig = None
        self._stat_fig = None

        self._build_ui()

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)

        # ---- 顶部选择与操作 ----
        top = QHBoxLayout()
        top.addWidget(QLabel("数据集:"))
        self.ds_combo = QComboBox()
        self.ds_combo.currentTextChanged.connect(self._on_ds_changed)
        top.addWidget(self.ds_combo, 1)
        top.addWidget(QLabel("航点算法:"))
        self.wp_algo_combo = QComboBox()
        top.addWidget(self.wp_algo_combo, 1)
        self.btn_wp = QPushButton("导出航点")
        self.btn_wp.clicked.connect(self.export_waypoints)
        top.addWidget(self.btn_wp)
        v.addLayout(top)

        ops = QHBoxLayout()
        self.btn_latex = QPushButton("导出 LaTeX")
        self.btn_latex.clicked.connect(self.export_latex)
        self.btn_csv = QPushButton("导出 CSV")
        self.btn_csv.clicked.connect(self.export_csv)
        self.btn_json = QPushButton("导出 JSON")
        self.btn_json.clicked.connect(self.export_json)
        self.btn_report = QPushButton("生成报告")
        self.btn_report.clicked.connect(self.generate_report)
        self.btn_fig = QPushButton("导出图表")
        self.btn_fig.clicked.connect(self.export_figure)
        for b in (self.btn_latex, self.btn_csv, self.btn_json,
                  self.btn_report, self.btn_fig):
            ops.addWidget(b)
        ops.addStretch(1)
        v.addLayout(ops)

        # ---- 标签页 ----
        self.tabs = QTabWidget()
        # 表格
        self.table = QTableWidget()
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.tabs.addTab(self.table, "对比表格")

        # 收敛曲线
        self.conv_host = QWidget()
        conv_v = QVBoxLayout(self.conv_host)
        conv_v.setContentsMargins(0, 0, 0, 0)
        self.conv_canvas = FigureCanvasQTAgg(Figure(figsize=(7, 4.5), dpi=100))
        conv_v.addWidget(self.conv_canvas)
        self.conv_hint = QLabel("收敛曲线（元启发式算法才有；多次运行显示均值 ± 标准差带）")
        self.conv_hint.setStyleSheet("color:#888;font-size:11px;")
        conv_v.addWidget(self.conv_hint)
        self.tabs.addTab(self.conv_host, "收敛曲线")

        # 统计图表
        self.stat_host = QWidget()
        stat_v = QVBoxLayout(self.stat_host)
        stat_v.setContentsMargins(0, 0, 0, 0)
        self.stat_canvas = FigureCanvasQTAgg(Figure(figsize=(7, 6), dpi=100))
        stat_v.addWidget(self.stat_canvas)
        self.stat_hint = QLabel("柱状图：总距离均值±标准差；箱线图：多次运行分布；"
                                "散点图：距离 vs 转弯 Pareto 视角")
        self.stat_hint.setStyleSheet("color:#888;font-size:11px;")
        stat_v.addWidget(self.stat_hint)
        self.tabs.addTab(self.stat_host, "统计图表")

        v.addWidget(self.tabs, 1)

    # ------------------------------------------------------------ 数据
    def set_data(self, results, datasets, camera, baseline,
                 algos_meta=None, params_by_algo=None, seeds=None,
                 project_name="未命名工程"):
        """results: {dataset_name: {algo: [run_dict,...]}}"""
        self._results = results or {}
        self._datasets = {ds.name: ds for ds in (datasets or [])}
        self._camera = dict(camera or {})
        self._baseline = baseline
        self._algos_meta = algos_meta or ALGORITHM_META
        self._params_by_algo = params_by_algo or {}
        self._seeds = seeds or []
        self._project_name = project_name or "未命名工程"

        # 数据集下拉
        self.ds_combo.blockSignals(True)
        self.ds_combo.clear()
        for name in self._results:
            self.ds_combo.addItem(name, name)
        self.ds_combo.blockSignals(False)
        if self.ds_combo.count():
            self.ds_combo.setCurrentIndex(0)
        self._refresh_waypoint_algos()
        self.rebuild()
        self._set_enabled(self.ds_combo.count() > 0)

    def _set_enabled(self, on: bool):
        for w in (self.btn_latex, self.btn_csv, self.btn_json, self.btn_report,
                  self.btn_fig, self.btn_wp, self.ds_combo, self.wp_algo_combo):
            w.setEnabled(on)

    def _active_runs(self) -> dict:
        name = self.ds_combo.currentData()
        return self._results.get(name, {}) if name else {}

    def _on_ds_changed(self, *_):
        self._refresh_waypoint_algos()
        self.rebuild()

    def _refresh_waypoint_algos(self):
        runs = self._active_runs()
        self.wp_algo_combo.blockSignals(True)
        self.wp_algo_combo.clear()
        for algo in runs:
            self.wp_algo_combo.addItem(algo, algo)
        self.wp_algo_combo.blockSignals(False)

    # ------------------------------------------------------------ 重建
    def rebuild(self):
        self._rebuild_table()
        self._rebuild_convergence()
        self._rebuild_stats()

    def _rebuild_table(self):
        runs_by_algo = self._active_runs()
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        if not runs_by_algo:
            self.table.setRowCount(1)
            self.table.setColumnCount(1)
            self.table.setItem(0, 0, QTableWidgetItem("（尚无实验数据）"))
            return
        try:
            df = build_comparison_table(runs_by_algo, baseline=self._baseline)
        except Exception as e:
            self.table.setRowCount(1)
            self.table.setColumnCount(1)
            self.table.setItem(0, 0, QTableWidgetItem(f"统计失败：{e}"))
            return
        self.table.setRowCount(df.shape[0])
        self.table.setColumnCount(df.shape[1])
        self.table.setHorizontalHeaderLabels([str(c) for c in df.columns])
        self.table.setVerticalHeaderLabels([str(i) for i in df.index])
        for i in range(df.shape[0]):
            for j in range(df.shape[1]):
                v = df.iat[i, j]
                if isinstance(v, (int, float)):
                    text = f"{v:g}" if v == v else "--"   # NaN → --
                else:
                    text = str(v)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, j, item)

    def _rebuild_convergence(self):
        fig = self.conv_canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        runs_by_algo = self._active_runs()
        colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd",
                  "#ff7f0e", "#8c564b", "#e377c2", "#7f7f7f"]
        plotted = 0
        for k, (algo, runs) in enumerate(runs_by_algo.items()):
            convs = [np.asarray(r.get("convergence") or [], dtype=float)
                     for r in runs]
            convs = [c for c in convs if c.size > 0]
            if not convs:
                continue
            maxlen = max(len(c) for c in convs)
            mat = np.full((len(convs), maxlen), np.nan)
            for i, c in enumerate(convs):
                mat[i, :len(c)] = c
            mean = np.nanmean(mat, axis=0)
            std = np.nanstd(mat, axis=0)
            color = colors[k % len(colors)]
            x = np.arange(maxlen)
            if len(convs) > 1:
                ax.fill_between(x, mean - std, mean + std, color=color,
                                alpha=0.15)
            ax.plot(x, mean, color=color, linewidth=1.6,
                    label=f"{algo} (n={len(convs)})")
            if mean.size:
                bi = int(np.nanargmin(mean))
                ax.annotate(f"{mean[bi]:.0f} @ {bi}",
                            xy=(bi, mean[bi]), xytext=(8, 10),
                            textcoords="offset points", fontsize=8,
                            color=color,
                            arrowprops=dict(arrowstyle="->", color=color,
                                            lw=0.8))
            plotted += 1
        if plotted == 0:
            ax.text(0.5, 0.5, "无可比收敛数据：\n元启发式算法（如 ACO-GTSP）"
                              "才有收敛历史，\n确定性基线无迭代过程。",
                    ha="center", va="center", transform=ax.transAxes,
                    fontsize=11, color="#666")
            ax.set_axis_off()
        else:
            ax.set_xlabel("迭代次数")
            ax.set_ylabel("全程路径最优值 (m)")
            ax.set_title("多算法收敛曲线对比")
            ax.grid(True, alpha=0.3)
            ax.legend(loc="upper right", fontsize=8)
        self.conv_canvas.draw_idle()
        self._conv_fig = fig

    def _rebuild_stats(self):
        fig = self.stat_canvas.figure
        fig.clear()
        runs_by_algo = self._active_runs()
        if not runs_by_algo:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, "（尚无实验数据）", ha="center", va="center",
                    transform=ax.transAxes, color="#666")
            ax.set_axis_off()
            self.stat_canvas.draw_idle()
            return

        colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd",
                  "#ff7f0e", "#8c564b", "#e377c2", "#7f7f7f"]
        algos = list(runs_by_algo.keys())
        dist_means, dist_stds = [], []
        dist_all, turn_all = [], []
        for algo in algos:
            dists = [r["total_distance"] for r in runs_by_algo[algo]
                     if "total_distance" in r]
            turns = [r["total_turns"] for r in runs_by_algo[algo]
                     if "total_turns" in r]
            dist_means.append(float(np.mean(dists)) if dists else 0.0)
            dist_stds.append(float(np.std(dists)) if dists else 0.0)
            dist_all.append(dists)
            turn_all.append(turns)

        # 1) 柱状图：距离均值±标准差
        ax1 = fig.add_subplot(1, 3, 1)
        ax1.bar(range(len(algos)), dist_means, yerr=dist_stds,
                color=colors[:len(algos)], capsize=4, alpha=0.85)
        ax1.set_xticks(range(len(algos)))
        ax1.set_xticklabels(algos, rotation=20, ha="right", fontsize=8)
        ax1.set_ylabel("总距离均值 (m)")
        ax1.set_title("距离对比（误差棒=标准差）")
        ax1.grid(axis="y", alpha=0.3)

        # 2) 箱线图：距离分布
        ax2 = fig.add_subplot(1, 3, 2)
        ax2.boxplot(dist_all, labels=algos, patch_artist=True,
                    boxprops=dict(alpha=0.7))
        for patch, c in zip(ax2.patches, colors[:len(algos)]):
            patch.set_facecolor(c)
        for lbl in ax2.get_xticklabels():
            lbl.set_rotation(20)
            lbl.set_ha("right")
            lbl.set_fontsize(8)
        ax2.set_ylabel("总距离 (m)")
        ax2.set_title("多次运行分布（稳定性）")
        ax2.grid(axis="y", alpha=0.3)

        # 3) 散点图：距离 vs 转弯
        ax3 = fig.add_subplot(1, 3, 3)
        for k, algo in enumerate(algos):
            ds = dist_all[k]
            ts = turn_all[k]
            ax3.scatter(ds, ts, s=36, color=colors[k % len(colors)],
                        alpha=0.8, label=algo, edgecolors="white", linewidths=0.5)
        ax3.set_xlabel("总距离 (m)")
        ax3.set_ylabel("总转弯次数")
        ax3.set_title("距离 vs 转弯（Pareto 视角）")
        ax3.grid(alpha=0.3)
        ax3.legend(fontsize=7, loc="best")

        fig.tight_layout()
        self.stat_canvas.draw_idle()
        self._stat_fig = fig

    # ------------------------------------------------------------ 导出
    def _best_run(self, algo: str) -> dict:
        runs = self._active_runs().get(algo) or []
        if not runs:
            return {}
        return min(runs, key=lambda r: r.get("total_distance", float("inf")))

    def export_latex(self):
        runs_by_algo = self._active_runs()
        if not runs_by_algo:
            return self._no_data()
        try:
            df = build_comparison_table(runs_by_algo, baseline=self._baseline)
        except Exception as e:
            return QMessageBox.warning(self, "错误", f"统计失败：{e}")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 LaTeX 表格", os.path.join(EXPERIMENT_DIR, "compare_table.tex"),
            "TeX (*.tex);;文本 (*.txt)")
        if not path:
            return
        src = report_gen.latex_booktabs(df)
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        QMessageBox.information(self, "完成", f"LaTeX 源码已导出：\n{path}")

    def export_csv(self):
        runs_by_algo = self._active_runs()
        if not runs_by_algo:
            return self._no_data()
        df = build_comparison_table(runs_by_algo, baseline=self._baseline)
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV", os.path.join(EXPERIMENT_DIR, "compare_table.csv"),
            "CSV (*.csv)")
        if not path:
            return
        report_gen.export_csv(df, path)
        QMessageBox.information(self, "完成", f"已导出：\n{path}")

    def export_json(self):
        if not self._results:
            return self._no_data()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 JSON", os.path.join(EXPERIMENT_DIR, "runs.json"),
            "JSON (*.json)")
        if not path:
            return
        report_gen.export_json(self._results, path)
        QMessageBox.information(self, "完成", f"已导出：\n{path}")

    def export_figure(self):
        if not self._active_runs():
            return self._no_data()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出图表", os.path.join(EXPERIMENT_DIR, "chart.png"),
            "PNG 300dpi (*.png);;SVG 矢量 (*.svg);;PDF 矢量 (*.pdf)")
        if not path:
            return
        idx = self.tabs.currentIndex()
        fig = self._stat_fig if idx == 2 else self._conv_fig if idx == 1 else None
        if fig is None:
            fig = self._stat_fig or self._conv_fig
        if fig is None:
            return self._no_data()
        fig.savefig(path, dpi=300, bbox_inches="tight")
        QMessageBox.information(self, "完成", f"已导出：\n{path}")

    def generate_report(self):
        runs_by_algo = self._active_runs()
        if not runs_by_algo:
            return self._no_data()
        # 先落盘当前两张图为 PNG，插入报告
        figs = []
        for fig, tag in ((self._conv_fig, "convergence"),
                         (self._stat_fig, "stats")):
            if fig is None:
                continue
            fp = os.path.join(EXPERIMENT_DIR, f"{tag}.png")
            try:
                fig.savefig(fp, dpi=150, bbox_inches="tight")
                figs.append(fp)
            except Exception:
                pass
        ds_name = self.ds_combo.currentData() or ""
        md = report_gen.generate_report(
            project_name=f"{self._project_name} [{ds_name}]",
            camera=self._camera,
            runs_by_algo=runs_by_algo,
            baseline=self._baseline,
            algos_meta=self._algos_meta,
            params_by_algo=self._params_by_algo,
            seeds=self._seeds,
            figures=figs,
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "生成实验记录报告", os.path.join(EXPERIMENT_DIR, "report.md"),
            "Markdown (*.md);;文本 (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        QMessageBox.information(self, "完成", f"报告已生成：\n{path}")

    def export_waypoints(self):
        algo = self.wp_algo_combo.currentData()
        ds_name = self.ds_combo.currentData()
        if not algo or not ds_name:
            return self._no_data()
        run = self._best_run(algo)
        if not run or not run.get("waypoints"):
            return QMessageBox.information(self, "提示", "该算法无航点数据")
        ds = self._datasets.get(ds_name)
        if ds is None:
            return QMessageBox.warning(self, "错误", "找不到数据集信息，无法换算经纬度")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出航点", os.path.join(EXPERIMENT_DIR, f"waypoints_{algo}.kml"),
            "KML (*.kml);;CSV (*.csv);;TXT (*.txt)")
        if not path:
            return
        try:
            tf = CoordTransform(epsg=ds.epsg)
            alt = float(self._camera.get("flight_height_m", 100.0))
            wps = [(lon, lat, alt) for lon, lat in
                   tf.points_utm_to_lonlat(run["waypoints"])]
            export_waypoints(wps, path, mission_name=f"{APP_NAME}-{algo}")
        except Exception as e:
            return QMessageBox.warning(self, "错误", f"导出失败：{e}")
        QMessageBox.information(self, "完成", f"航点已导出（可导入 Mission Planner）：\n{path}")

    def _no_data(self):
        QMessageBox.information(self, "提示", "当前没有实验数据，请先运行实验。")
