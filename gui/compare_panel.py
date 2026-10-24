# -*- coding: utf-8 -*-
"""比较结果面板：多算法对比表格、收敛曲线、统计图表与论文写作辅助导出。

对应需求规格 4.6.2 / 4.6.3 / 4.7 / 4.8：
- 收敛曲线多算法同图叠加（均值 ± 标准差带），标注最优轮次与值；
- 柱状图（距离误差棒）、箱线图（稳定性）、散点图（Pareto 视角）；
- LaTeX（booktabs）表格导出、CSV/JSON 导出、实验报告生成；
- 航点导出（KML/CSV/TXT，供外部地图或任务规划工具读取）。
"""
import os
from pathlib import Path
import re

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QPushButton, QPlainTextEdit,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from compare import report_gen
from compare.statistics import build_comparison_table
from compare.metrics import successful_run
from config.default_params import ALGORITHM_META, EXPERIMENT_DIR, APP_NAME, PICTURE_DIR
from data.coord_transform import CoordTransform
from data.waypoint_export import export_waypoints
from core.image_export import save_jpeg, jpeg_path


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
        self._dirty_charts = {1, 2}

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
        top.addWidget(QLabel("结果组合:"))
        self.wp_algo_combo = QComboBox()
        self.wp_algo_combo.setToolTip('选择要导出航点或路线图的组合；多种子运行时使用该组合航程最短的有效结果。')
        top.addWidget(self.wp_algo_combo, 1)
        self.btn_wp = QPushButton("导出航点")
        self.btn_wp.setToolTip('导出真实轨迹的经纬度/航高为 KML、CSV 或 TXT，供外部地图、任务规划软件读取；不含拍照触发及完整飞控任务命令。')
        self.btn_wp.clicked.connect(self.export_waypoints)
        top.addWidget(self.btn_wp)
        self.btn_route_image = QPushButton('导出路线图')
        self.btn_route_image.clicked.connect(self.choose_route_images)
        top.addWidget(self.btn_route_image)
        self.btn_convergence_image = QPushButton('导出收敛曲线')
        self.btn_convergence_image.clicked.connect(self.choose_convergence_images)
        top.addWidget(self.btn_convergence_image)
        v.addLayout(top)
        self.failure_label = QPlainTextEdit()
        self.failure_label.setReadOnly(True)
        self.failure_label.setFixedHeight(94)
        self.failure_label.setPlaceholderText('运行错误（可滚动查看）')
        self.failure_label.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.failure_label.setStyleSheet('color:#a33;')
        v.addWidget(self.failure_label)

        ops = QHBoxLayout()
        ops.addWidget(QLabel('距离基线：'))
        self.baseline_combo = QComboBox()
        self.baseline_combo.setMinimumWidth(170)
        self.baseline_combo.setToolTip('改善率 = (基线总距离均值 − 此组合总距离均值) / 基线均值 ×100%；正数表示距离缩短。')
        self.baseline_combo.currentIndexChanged.connect(self._baseline_changed)
        ops.addWidget(self.baseline_combo, 1)
        v.addLayout(ops)

        coverage_hint = QLabel('覆盖率 = 扫描到的目标面积 / 总任务面积（重复覆盖只计一次，区外不计）；未覆盖为0不代表航程最优。')
        coverage_hint.setWordWrap(True)
        coverage_hint.setStyleSheet('color:#475569;font-size:11px;')
        v.addWidget(coverage_hint)
        ops = QHBoxLayout()
        self.btn_latex = QPushButton("导出 LaTeX")
        self.btn_latex.clicked.connect(self.export_latex)
        self.btn_csv = QPushButton("导出 CSV")
        self.btn_csv.clicked.connect(self.export_csv)
        self.btn_json = QPushButton("导出 JSON")
        self.btn_json.clicked.connect(self.export_json)
        self.btn_report = QPushButton("导出实验摘要（Markdown）")
        self.btn_report.setToolTip('可选的实验归档摘要：参数、对比指标、各次运行与图表；不参与算法计算。')
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
        self.table.viewport().installEventFilter(self)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.horizontalScrollBar().setSingleStep(24)
        self.table.verticalScrollBar().setSingleStep(24)
        self.table.setWordWrap(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(260)
        self.table.horizontalHeader().setMinimumSectionSize(150)
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setAlternatingRowColors(True)
        self.tabs.addTab(self.table, "对比表格")

        # 收敛曲线
        self.conv_host = QWidget()
        conv_v = QVBoxLayout(self.conv_host)
        conv_v.setContentsMargins(0, 0, 0, 0)
        self.conv_canvas = FigureCanvasQTAgg(Figure(figsize=(7, 4.5), dpi=100))
        conv_v.addWidget(self.conv_canvas)
        self.conv_hint = QLabel('开放子区连接距离 = Σ(上一子区出口 → 下一子区入口)，不含区内扫描、起飞及返航。\n'
                               'DP 优化该连接距离；ACO/FA3ACO 优化完整任务距离，因此按目标分图。DP 是精确求解结果点，不是迭代收敛过程。')
        self.conv_hint.setWordWrap(True)
        self.conv_hint.setStyleSheet("color:#888;font-size:11px;")
        conv_v.addWidget(self.conv_hint)
        self.tabs.addTab(self.conv_host, "收敛曲线")

        # 统计图表
        self.stat_host = QWidget()
        stat_v = QVBoxLayout(self.stat_host)
        stat_v.setContentsMargins(0, 0, 0, 0)
        self.stat_canvas = FigureCanvasQTAgg(Figure(figsize=(7, 6), dpi=100))
        stat_v.addWidget(self.stat_canvas)
        self.scatter_check = QCheckBox('显示辅助图：航程与转弯次数权衡')
        self.scatter_check.setChecked(False)
        self.scatter_check.toggled.connect(self._scatter_changed)
        stat_v.addWidget(self.scatter_check)
        self.stat_hint = QLabel('柱状图比较航程；箱线图比较多次运行稳定性。可选散点图横轴为航程、纵轴为航向变化超过5°的次数，'
                                '用于观察短航程与少转弯的权衡；不是航点数量，也不等同于能耗。')
        self.stat_hint.setWordWrap(True)
        self.stat_hint.setStyleSheet("color:#888;font-size:11px;")
        stat_v.addWidget(self.stat_hint)
        self.tabs.addTab(self.stat_host, "统计图表")

        v.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(self._ensure_chart)

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
        from compare.route_metrics import attach_route_metrics
        for name, algos in self._results.items():
            for runs in algos.values():
                for run in runs:
                    if successful_run(run) and run.get('waypoints'):
                        attach_route_metrics(run, self._datasets.get(name))
                        from compare.coverage_metrics import coverage_details
                        coverage = coverage_details(run, self._datasets.get(name), self._camera)
                        if coverage:
                            run['metadata']['coverage'] = coverage

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

    def clear(self):
        """清空所有比较结果、表格与图表（保留 UI 框架与当前数据集）。"""
        self._results = {}
        self._datasets = {}
        self._camera = {}
        self._baseline = None
        self.ds_combo.blockSignals(True)
        self.ds_combo.clear()
        self.ds_combo.blockSignals(False)
        self.wp_algo_combo.clear()
        self.baseline_combo.clear()
        self.rebuild()
        self._set_enabled(False)

    def _set_enabled(self, on: bool):
        for w in (self.btn_latex, self.btn_csv, self.btn_json, self.btn_report,
                  self.btn_fig, self.btn_wp, self.btn_route_image, self.btn_convergence_image,
                  self.ds_combo, self.wp_algo_combo, self.baseline_combo):
            w.setEnabled(on)

    def _active_runs(self) -> dict:
        raw = self._table_runs()
        return {algo: valid for algo, runs in raw.items()
                if (valid := [run for run in runs if successful_run(run)])}

    def _table_runs(self):
        return self._results.get(self.ds_combo.currentData(), {})

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
        self.baseline_combo.blockSignals(True)
        self.baseline_combo.clear()
        self.baseline_combo.addItem('不设置基线', None)
        for algo in runs:
            self.baseline_combo.addItem(algo, algo)
        self.baseline_combo.setCurrentIndex(max(0, self.baseline_combo.findData(self._baseline)))
        self._baseline = self.baseline_combo.currentData()
        self.baseline_combo.blockSignals(False)

    def _baseline_changed(self):
        self._baseline = self.baseline_combo.currentData()
        self._rebuild_table()

    # ------------------------------------------------------------ 重建
    def rebuild(self):
        name = self.ds_combo.currentData()
        errors = [f"{algo} · seed={run.get('seed', '--')}：{run.get('error') or '结果缺少有效总距离'}"
                  for algo, runs in self._results.get(name, {}).items()
                  for run in runs if not successful_run(run)]
        self.failure_label.setPlainText('\n'.join(errors))
        self._rebuild_table()
        self._dirty_charts = {1, 2}
        self._conv_fig = self._stat_fig = None
        self._ensure_chart(self.tabs.currentIndex())

    def _ensure_chart(self, index):
        if index in self._dirty_charts:
            if index == 1:
                self._rebuild_convergence()
            elif index == 2:
                self._rebuild_stats()
            self._dirty_charts.discard(index)

    def _scatter_changed(self):
        self._dirty_charts.add(2)
        if self.tabs.currentIndex() == 2:
            self._ensure_chart(2)

    def _rebuild_table(self):
        runs_by_algo = self._table_runs()
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
        from compare.route_metrics import METRIC_HELP
        for i, key in enumerate(df.index):
            item = self.table.verticalHeaderItem(i)
            item.setToolTip(METRIC_HELP.get(key, key))
        for j, key in enumerate(df.columns):
            failed = [run for run in runs_by_algo[key] if not successful_run(run)]
            header = self.table.horizontalHeaderItem(j)
            header.setToolTip(key + '\n' + '\n'.join(
                f"seed={r.get('seed', '--')}：{r.get('error') or '结果缺少有效总距离'}" for r in failed))
            if failed:
                header.setForeground(QColor('#b91c1c'))
        for i in range(df.shape[0]):
            for j in range(df.shape[1]):
                v = df.iat[i, j]
                if isinstance(v, (int, float)):
                    if str(df.index[i]).startswith('覆盖率') and v == v:
                        from compare.coverage_metrics import format_coverage
                        text = format_coverage({'covered_ratio': v / 100})
                    else:
                        text = f"{v:g}" if v == v else "--"   # NaN → --
                else:
                    text = str(v)
                item = QTableWidgetItem(text)
                item.setToolTip(f'{df.index[i]}：{v}\n' + METRIC_HELP.get(df.index[i], ''))
                item.setTextAlignment(Qt.AlignCenter)
                if any(not successful_run(run) for run in runs_by_algo[df.columns[j]]):
                    item.setForeground(QColor('#b91c1c'))
                    item.setBackground(QColor('#fff1f2'))
                self.table.setItem(i, j, item)
        self._fit_table_columns()

    def _fit_table_columns(self, available=None):
        if not hasattr(self, 'table') or not self.table.columnCount():
            return
        count = self.table.columnCount()
        available = self.table.viewport().width() if available is None else available
        fitting = available >= count*260
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch if fitting else QHeaderView.Interactive)
        if not fitting:
            for column in range(count):
                self.table.setColumnWidth(column, 260)

    def eventFilter(self, watched, event):
        if hasattr(self, 'table') and watched is self.table.viewport() and event.type() == QEvent.Resize:
            self._fit_table_columns(event.size().width())
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_table_columns()

    def _rebuild_convergence(self):
        fig = self.conv_canvas.figure
        from compare.convergence import draw_convergence
        draw_convergence(fig, self._active_runs())
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
        ncols = 3 if self.scatter_check.isChecked() else 2
        ax1 = fig.add_subplot(1, ncols, 1)
        ax1.bar(range(len(algos)), dist_means, yerr=dist_stds,
                color=[colors[i % len(colors)] for i in range(len(algos))], capsize=4, alpha=0.85)
        ax1.set_xticks(range(len(algos)))
        ax1.set_xticklabels(algos, rotation=20, ha="right", fontsize=8)
        ax1.set_ylabel("总距离均值 (m)")
        ax1.set_title("距离对比（误差棒=标准差）")
        ax1.grid(axis="y", alpha=0.3)

        # 2) 箱线图：距离分布
        ax2 = fig.add_subplot(1, ncols, 2)
        boxes = ax2.boxplot(dist_all, tick_labels=algos, patch_artist=True,
                    boxprops=dict(alpha=0.7))
        for i, patch in enumerate(boxes['boxes']):
            patch.set_facecolor(colors[i % len(colors)])
        for lbl in ax2.get_xticklabels():
            lbl.set_rotation(20)
            lbl.set_ha("right")
            lbl.set_fontsize(8)
        ax2.set_ylabel("总距离 (m)")
        ax2.set_title("多次运行分布（稳定性）")
        ax2.grid(axis="y", alpha=0.3)

        # 3) 散点图：距离 vs 航向拐点
        if not self.scatter_check.isChecked():
            fig.tight_layout()
            self.stat_canvas.draw_idle()
            self._stat_fig = fig
            return
        ax3 = fig.add_subplot(1, ncols, 3)
        for k, algo in enumerate(algos):
            pairs = [(run['total_distance'], run['total_turns']) for run in runs_by_algo[algo]
                     if run.get('total_turns') is not None]
            ds, ts = zip(*pairs) if pairs else ([], [])
            ax3.scatter(ds, ts, s=36, color=colors[k % len(colors)],
                        alpha=0.8, label=algo, edgecolors="white", linewidths=0.5)
        ax3.set_xlabel("总距离 (m)")
        ax3.set_ylabel("航向拐点数(>5°)")
        ax3.set_title("距离 vs 航向拐点（Pareto 视角）")
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
        runs_by_algo = self._table_runs()
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
        runs_by_algo = self._table_runs()
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
            self, "导出图表", os.path.join(PICTURE_DIR, "chart.jpg"), 'JPEG (*.jpg *.jpeg)')
        if not path:
            return
        idx = self.tabs.currentIndex()
        self._ensure_chart(idx if idx in (1, 2) else 2)
        fig = self._stat_fig if idx == 2 else self._conv_fig if idx == 1 else None
        if fig is None:
            fig = self._stat_fig or self._conv_fig
        if fig is None:
            return self._no_data()
        path = save_jpeg(fig, path)
        QMessageBox.information(self, "完成", f"已导出：\n{path}")

    def export_route_image(self):
        label = self.wp_algo_combo.currentData()
        ds = self._datasets.get(self.ds_combo.currentData())
        run = self._best_run(label)
        if not ds or not run:
            return self._no_data()
        stem = re.sub(r'[<>:"/\\|?*]', '_', f'{ds.name}_{label}_seed{run.get("seed", "")}')
        path, _ = QFileDialog.getSaveFileName(self, '导出所选组合路线图',
            os.path.join(PICTURE_DIR, stem + '.jpg'), 'JPEG (*.jpg *.jpeg)')
        if not path:
            return
        path = str(jpeg_path(path))
        try:
            from core.experiment_bundle import _plot_run
            _plot_run(path, ds, run)
        except Exception as exc:
            return QMessageBox.warning(self, '路线图导出失败', str(exc))
        QMessageBox.information(self, '导出完成', '已导出所选组合的完整轨迹、分割边界与入口/出口：\n' + path)

    def choose_route_images(self):
        from PySide6.QtWidgets import QDialog
        from gui.route_export_dialog import RouteExportDialog, export_route_images
        if not self._active_runs():
            return self._no_data()
        dialog = RouteExportDialog(list(self._active_runs()), self.wp_algo_combo.currentData(), self)
        if dialog.exec() != QDialog.Accepted:
            return
        labels = dialog.selected_labels()
        if not labels or not dialog.directory.text().strip():
            return QMessageBox.warning(self, '未选择导出内容', '请勾选组合并填写导出目录。')
        try:
            paths = export_route_images(dialog.directory.text(), self._datasets[self.ds_combo.currentData()],
                {label: self._best_run(label) for label in labels}, dialog.mode.currentData() == 'overlay')
        except Exception as exc:
            return QMessageBox.warning(self, '路线图导出失败', str(exc))
        QMessageBox.information(self, '导出完成', f'已导出 {len(paths)} 张高清 JPEG：\n' + '\n'.join(str(p) for p in paths))

    def choose_convergence_images(self):
        from PySide6.QtWidgets import QDialog
        from gui.route_export_dialog import RouteExportDialog, export_convergence_images
        runs = {label: curves for label, values in self._active_runs().items()
                if (curves := [run for run in values if run.get('convergence')])}
        if not runs:
            return QMessageBox.information(self, '提示', '当前数据集没有有效收敛数据。')
        dialog = RouteExportDialog(list(runs), self.wp_algo_combo.currentData(), self, convergence=True)
        if dialog.exec() != QDialog.Accepted:
            return
        labels = dialog.selected_labels()
        if not labels or not dialog.directory.text().strip():
            return QMessageBox.warning(self, '未选择导出内容', '请勾选组合并填写导出目录。')
        try:
            paths = export_convergence_images(dialog.directory.text(),
                {label: runs[label] for label in labels}, dialog.mode.currentData() == 'overlay')
        except Exception as exc:
            return QMessageBox.warning(self, '收敛曲线导出失败', str(exc))
        QMessageBox.information(self, '导出完成', f'已导出 {len(paths)} 张高清 JPEG：\n' + '\n'.join(str(p) for p in paths))

    def generate_report(self):
        runs_by_algo = self._table_runs()
        if not runs_by_algo:
            return self._no_data()
        path, _ = QFileDialog.getSaveFileName(self, '导出实验摘要（Markdown）',
            os.path.join(EXPERIMENT_DIR, 'report.md'), 'Markdown (*.md)')
        if not path:
            return
        path = Path(path)
        if not path.suffix:
            path = path.with_suffix('.md')
        try:
            self._ensure_chart(1)
            self._ensure_chart(2)
            assets = path.parent / (path.stem + '_assets')
            assets.mkdir(parents=True, exist_ok=True)
            figures = []
            for figure, tag in ((self._conv_fig, 'convergence'), (self._stat_fig, 'statistics')):
                if figure is not None:
                    target = assets / (tag + '.jpg')
                    save_jpeg(figure, target)
                    figures.append(target.relative_to(path.parent).as_posix())
            md = report_gen.generate_report(
                project_name=f'{self._project_name} [{self.ds_combo.currentData()}]',
                camera=self._camera, runs_by_algo=runs_by_algo, baseline=self._baseline,
                algos_meta=self._algos_meta, params_by_algo=self._params_by_algo,
                seeds=self._seeds, figures=figures)
            path.write_text(md, encoding='utf-8')
        except Exception as exc:
            return QMessageBox.warning(self, '摘要导出失败', str(exc))
        QMessageBox.information(self, '导出完成', '实验摘要已保存；携带报告时请同时保留旁边的 assets 文件夹：\n' + str(path))

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
        QMessageBox.information(self, '完成', f'经纬度与航高已导出，可供外部地图或任务规划工具读取：\n{path}\n文件不含完整飞控任务指令。')

    def _no_data(self):
        QMessageBox.information(self, "提示", "当前没有实验数据，请先运行实验。")
