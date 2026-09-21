# -*- coding: utf-8 -*-
"""实验控制面板：运行模式、种子管理、进度控制。"""
import random
from typing import List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QProgressBar, QPushButton,
                               QRadioButton, QVBoxLayout, QWidget)


class ExperimentPanel(QWidget):
    """实验调度控制。"""

    run_requested = Signal(str)      # mode
    stop_requested = Signal()

    MODES = {
        "single": "单算法单次运行（快速验证）",
        "repeated": "单算法多次运行（统计稳定性）",
        "batch": "批量比较（算法×数据集×种子）",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)

        g = QGroupBox("运行模式")
        gv = QVBoxLayout(g)
        self.mode_combo = QComboBox()
        for key, label in self.MODES.items():
            self.mode_combo.addItem(label, key)
        gv.addWidget(self.mode_combo)
        v.addWidget(g)

        g2 = QGroupBox("随机种子（可复现性）")
        g2v = QVBoxLayout(g2)
        row = QHBoxLayout()
        self.seeds_edit = QLineEdit("42")
        self.seeds_edit.setPlaceholderText("如: 42, 7, 123 或 1-10")
        row.addWidget(self.seeds_edit, 1)
        btn_gen = QPushButton("生成")
        btn_gen.clicked.connect(self._gen_seeds)
        row.addWidget(btn_gen)
        g2v.addLayout(row)
        hint = QLabel("支持逗号分隔或区间（如 1-10 表示 1..10）")
        hint.setStyleSheet("color:#888;font-size:10px;")
        g2v.addWidget(hint)
        v.addWidget(g2)

        g3 = QGroupBox("运行控制")
        g3v = QVBoxLayout(g3)
        row2 = QHBoxLayout()
        self.btn_run = QPushButton("▶ 运行实验")
        self.btn_run.setStyleSheet(
            "QPushButton{background:#16a34a;color:white;font-weight:bold;"
            "padding:8px;border-radius:4px;}"
            "QPushButton:disabled{background:#aaa;}")
        self.btn_run.clicked.connect(lambda: self.run_requested.emit(self.mode()))
        self.btn_stop = QPushButton("■ 终止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_requested)
        row2.addWidget(self.btn_run, 2)
        row2.addWidget(self.btn_stop, 1)
        g3v.addLayout(row2)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        g3v.addWidget(self.progress)
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color:#444;font-size:11px;")
        g3v.addWidget(self.status_label)
        v.addWidget(g3)

        v.addStretch(1)

    def mode(self) -> str:
        return self.mode_combo.currentData()

    def set_mode(self, mode: str):
        idx = self.mode_combo.findData(mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)

    def seeds(self) -> List[int]:
        text = self.seeds_edit.text().strip()
        if not text:
            return [42]
        seeds: List[int] = []
        for part in text.replace("，", ",").split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part and part.count("-") == 1:
                a, b = part.split("-")
                try:
                    seeds.extend(range(int(a), int(b) + 1))
                except ValueError:
                    continue
            else:
                try:
                    seeds.append(int(part))
                except ValueError:
                    continue
        seeds = list(dict.fromkeys(seeds))
        return seeds or [42]

    def set_seeds_text(self, seeds: List[int]):
        self.seeds_edit.setText(", ".join(str(s) for s in seeds))

    def _gen_seeds(self):
        n, ok = self._ask_count()
        if not ok:
            return
        rnd = random.Random()
        seeds = sorted(rnd.sample(range(1, 100000), n))
        self.set_seeds_text(seeds)

    def _ask_count(self):
        from PySide6.QtWidgets import QInputDialog
        n, ok = QInputDialog.getInt(self, "生成种子", "生成数量：", 3, 1, 100)
        return n, ok

    # ---------------- 运行状态 ----------------
    def set_running(self, running: bool):
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    def set_progress(self, done: int, total: int, msg: str = ""):
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(min(done, total))
        if msg:
            self.status_label.setText(msg)
