# -*- coding: utf-8 -*-
"""Selected-run metrics and the shared experiment log."""

from PySide6.QtWidgets import (QFormLayout, QGroupBox, QLabel, QPlainTextEdit,
                               QVBoxLayout, QWidget)


class ResultPanel(QWidget):
    """单算法单次运行结果。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.clear()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)

        g = QGroupBox("本次运行指标")
        form = QFormLayout(g)
        self.lbl_algo = QLabel("--")
        self.lbl_seed = QLabel("--")
        self.lbl_dist = QLabel("--")
        self.lbl_turns = QLabel("--")
        self.lbl_runtime = QLabel("--")
        self.lbl_coverage = QLabel("--")
        self.lbl_uncovered = QLabel('--')
        self.lbl_objective = QLabel("--")
        self.lbl_objective.setWordWrap(True)
        self.lbl_order = QLabel("--")
        self.lbl_order.setWordWrap(True)
        form.addRow("算法", self.lbl_algo)
        form.addRow("随机种子", self.lbl_seed)
        form.addRow("总飞行距离 (m)", self.lbl_dist)
        form.addRow("航向拐点数(>5°)", self.lbl_turns)
        form.addRow("运行耗时 (s)", self.lbl_runtime)
        form.addRow('覆盖率', self.lbl_coverage)
        form.addRow('未覆盖面积 (m²)', self.lbl_uncovered)
        form.addRow("优化目标", self.lbl_objective)
        v.addWidget(g)
        self.lbl_note = QLabel('')
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet('color:#92400e;background:#fff7e6;padding:8px;border-radius:5px;')
        self.lbl_note.hide()
        v.addWidget(self.lbl_note)

        self.log_box = QGroupBox('实验日志')
        self.log_layout = QVBoxLayout(self.log_box)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText('运行实验后显示进度、完成事件与错误信息。')
        self.log_layout.addWidget(self.log)
        self.detail = self.log  # Compatibility for script consumers; no metadata pane remains.
        self.outer_layout = v
        v.addWidget(self.log_box, 1)

    def attach_log_box(self, box, log):
        self.outer_layout.removeWidget(self.log_box)
        self.log_box.hide()
        self.log_box.deleteLater()
        self.log_box = box
        self.log = self.detail = log
        self.outer_layout.addWidget(box, 1)
        box.setMaximumHeight(16777215)
        box.show()

    def clear(self):
        self.lbl_note.clear()
        self.lbl_note.hide()
        for lbl in (self.lbl_algo, self.lbl_seed, self.lbl_dist,
                    self.lbl_turns, self.lbl_runtime, self.lbl_order,
                    self.lbl_coverage, self.lbl_uncovered, self.lbl_objective):
            lbl.setText("--")

    def show_run(self, run: dict):
        """run: ExperimentRunner 输出的单次运行字典。"""
        if run.get('error'):
            self.clear()
            self.lbl_algo.setText(str(run.get('algorithm', '--')))
            self.lbl_seed.setText(str(run.get('seed', '--')))
            self.lbl_objective.setText('运行失败')
            if run['error'] not in self.log.toPlainText():
                from html import escape
                self.log.appendHtml('<span style="color:#b91c1c">' + escape(run['error']) + '</span>')
            return
        self.lbl_algo.setText(str(run.get("algorithm", "--")))
        scopes = (run.get('metadata') or {}).get('component_implementation_scope') or {}
        self.lbl_algo.setToolTip('\n'.join(f'{kind}: {text}' for kind, text in scopes.items()))
        self.lbl_seed.setText(str(run.get("seed", "--")))
        self.lbl_dist.setText(f"{run.get('total_distance', float('nan')):.2f}")
        self.lbl_turns.setText(str(run.get("total_turns", "--")))
        self.lbl_runtime.setText(f"{run.get('runtime', 0.0):.4f}")
        order = run.get("region_order") or []
        self.lbl_order.setText(" → ".join(str(i) for i in order) if order else "--")

        meta = run.get("metadata") or {}
        coverage = meta.get("coverage", {})
        notes = [coverage.get('warning', ''), meta.get('gtsp', {}).get('paper_extension', '')]
        self.lbl_note.setText('\n'.join(note for note in notes if note))
        self.lbl_note.setVisible(bool(self.lbl_note.text()))
        from compare.coverage_metrics import format_coverage, format_area, coverage_tooltip
        self.lbl_coverage.setText(format_coverage(coverage))
        self.lbl_coverage.setToolTip(coverage_tooltip(coverage))
        self.lbl_uncovered.setText(format_area(coverage.get('uncovered_area_m2')))
        self.lbl_uncovered.setToolTip('0表示当前相机参数与连续扫描模型下无漏扫，不代表路线最优。非零小数不会四舍五入成0。')
        objective = meta.get("gtsp", {}).get("objective")
        self.lbl_objective.setText("开放子区连接距离（不含起降和内部扫描）"
            if objective == "open_inter_region_distance" else "完整任务距离")
