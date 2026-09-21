# -*- coding: utf-8 -*-
"""单算法结果统计面板：展示最近一次运行的标准指标与算法自定义信息。

对应需求规格 4.6.3 表格的「单次运行明细」与 CPPResult.metadata 展示。
"""
import json

from PySide6.QtWidgets import (QFormLayout, QGroupBox, QLabel, QTextBrowser,
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
        self.lbl_order = QLabel("--")
        self.lbl_order.setWordWrap(True)
        form.addRow("算法", self.lbl_algo)
        form.addRow("随机种子", self.lbl_seed)
        form.addRow("总飞行距离 (m)", self.lbl_dist)
        form.addRow("总转弯次数", self.lbl_turns)
        form.addRow("运行耗时 (s)", self.lbl_runtime)
        form.addRow("区域访问顺序", self.lbl_order)
        v.addWidget(g)

        g2 = QGroupBox("算法细节（metadata）")
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        g2.setLayout(QVBoxLayout())
        g2.layout().addWidget(self.detail)
        v.addWidget(g2, 1)

    def clear(self):
        for lbl in (self.lbl_algo, self.lbl_seed, self.lbl_dist,
                    self.lbl_turns, self.lbl_runtime, self.lbl_order):
            lbl.setText("--")
        self.detail.setPlainText("运行实验后，此处显示算法细节（凸分解信息、"
                                 "GTSP 统计、收敛末尾值等）。")

    def show_run(self, run: dict):
        """run: ExperimentRunner 输出的单次运行字典。"""
        self.lbl_algo.setText(str(run.get("algorithm", "--")))
        self.lbl_seed.setText(str(run.get("seed", "--")))
        self.lbl_dist.setText(f"{run.get('total_distance', float('nan')):.2f}")
        self.lbl_turns.setText(str(run.get("total_turns", "--")))
        self.lbl_runtime.setText(f"{run.get('runtime', 0.0):.4f}")
        order = run.get("region_order") or []
        self.lbl_order.setText(" → ".join(str(i) for i in order) if order else "--")

        conv = run.get("convergence") or []
        lines = []
        meta = run.get("metadata") or {}
        if meta:
            try:
                lines.append(json.dumps(meta, ensure_ascii=False, indent=2))
            except Exception:
                lines.append(str(meta))
        else:
            lines.append("（无自定义元信息）")
        if conv:
            tail = [f"{v:.1f}" for v in conv[-5:]]
            lines.append(f"\n收敛历史长度: {len(conv)}，末段: {', '.join(tail)}")
        self.detail.setPlainText("\n".join(lines))
