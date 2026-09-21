# -*- coding: utf-8 -*-
"""算法管理面板：多选算法、动态参数表单、基线设置、参数方案保存/加载。"""
import json
import os
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
                               QWidget)

from core.registry import AlgorithmRegistry
from config.default_params import ALGORITHM_META, BASE_DIR

PARAM_SCHEME_DIR = os.path.join(BASE_DIR, "param_schemes")


class AlgorithmPanel(QWidget):
    """算法选择与参数配置。"""

    algorithms_changed = Signal()
    baseline_changed = Signal(str)
    run_requested = Signal()

    def __init__(self, registry: AlgorithmRegistry, parent=None):
        super().__init__(parent)
        self.registry = registry
        self._param_widgets: Dict[str, QWidget] = {}
        self._current_algo: Optional[str] = None
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)

        # ---- 算法多选列表 ----
        g_algo = QGroupBox("算法选择（多选参与比较）")
        gv = QVBoxLayout(g_algo)
        self.algo_list = QListWidget()
        self.algo_list.itemChanged.connect(self._on_item_changed)
        gv.addWidget(self.algo_list)
        info_row = QHBoxLayout()
        self.meta_label = QLabel("点击算法查看说明")
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet("color:#666;font-size:11px;")
        info_row.addWidget(self.meta_label, 1)
        gv.addLayout(info_row)
        gv.addWidget(self._make_meta_box())
        v.addWidget(g_algo)

        # ---- 基线 ----
        g_base = QGroupBox("基线算法（相对改善率基准）")
        bv = QHBoxLayout(g_base)
        bv.addWidget(QLabel("基线:"))
        self.baseline_combo = QComboBox()
        self.baseline_combo.currentTextChanged.connect(self._on_baseline)
        bv.addWidget(self.baseline_combo, 1)
        v.addWidget(g_base)

        # ---- 动态参数表单 ----
        g_params = QGroupBox("算法参数（按选中算法动态加载）")
        pv = QVBoxLayout(g_params)
        self.param_scroll = QScrollArea()
        self.param_scroll.setWidgetResizable(True)
        self.param_scroll.setFixedHeight(200)
        self.param_form_host = QWidget()
        self.param_form = QFormLayout(self.param_form_host)
        self.param_scroll.setWidget(self.param_form_host)
        pv.addWidget(self.param_scroll)
        btn_row = QHBoxLayout()
        self.btn_default = QPushButton("恢复默认")
        self.btn_default.clicked.connect(self._restore_defaults)
        self.btn_save_scheme = QPushButton("保存参数方案")
        self.btn_save_scheme.clicked.connect(self._save_scheme)
        self.btn_load_scheme = QPushButton("加载参数方案")
        self.btn_load_scheme.clicked.connect(self._load_scheme)
        btn_row.addWidget(self.btn_default)
        btn_row.addWidget(self.btn_save_scheme)
        btn_row.addWidget(self.btn_load_scheme)
        pv.addLayout(btn_row)
        v.addWidget(g_params)

        # ---- 运行按钮 ----
        self.btn_run = QPushButton("▶ 运行选中算法")
        self.btn_run.setStyleSheet(
            "QPushButton{background:#2f6fed;color:white;font-weight:bold;"
            "padding:8px;border-radius:4px;}"
            "QPushButton:disabled{background:#aaa;}")
        self.btn_run.clicked.connect(self.run_requested)
        v.addWidget(self.btn_run)

        v.addStretch(1)

    def _make_meta_box(self):
        self.meta_detail = QLabel("")
        self.meta_detail.setWordWrap(True)
        self.meta_detail.setStyleSheet("color:#444;font-size:11px;background:#f5f5f5;"
                                       "border:1px solid #ddd;padding:4px;")
        return self.meta_detail

    # ---------------- 数据加载 ----------------
    def refresh(self):
        names = self.registry.names()
        current = self.selected_names()
        self.algo_list.blockSignals(True)
        self.algo_list.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if name in current else Qt.Unchecked)
            item.setData(Qt.UserRole, name)
            self.algo_list.addItem(item)
        self.algo_list.blockSignals(False)
        # 基线下拉
        self.baseline_combo.blockSignals(True)
        self.baseline_combo.clear()
        for name in names:
            self.baseline_combo.addItem(name, name)
        self.baseline_combo.blockSignals(False)
        if current:
            idx = self.baseline_combo.findData(current[0])
            if idx >= 0:
                self.baseline_combo.setCurrentIndex(idx)
        self._on_item_changed()

    def selected_names(self) -> List[str]:
        out = []
        for i in range(self.algo_list.count()):
            item = self.algo_list.item(i)
            if item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return out

    def baseline_name(self) -> Optional[str]:
        return self.baseline_combo.currentData()

    # ---------------- 参数 ----------------
    def _on_item_changed(self, *_):
        names = self.selected_names()
        self.meta_label.setText(
            f"已选 {len(names)} 个算法参与比较" if names else "未选择算法")
        # 参数表单显示第一个选中算法的参数
        if names:
            self._load_param_form(names[0])
            self._show_meta(names[0])
        else:
            self._clear_param_form()
        self.algorithms_changed.emit()

    def _load_param_form(self, algo_name: str):
        self._clear_param_form()
        cls = self.registry.get(algo_name)
        if cls is None:
            return
        self._current_algo = algo_name
        inst = cls()
        defaults = dict(inst.default_params)
        spec = inst.get_param_spec() if hasattr(inst, "get_param_spec") else []
        for key, label, typ, default in spec:
            if key == "seed":
                continue
            if typ == "int":
                w = QSpinBox()
                w.setRange(1, 1000000)
                w.setValue(int(default))
            else:
                w = QDoubleSpinBox()
                w.setRange(-1e9, 1e9)
                w.setDecimals(4)
                w.setValue(float(default))
            self.param_form.addRow(label, w)
            self._param_widgets[key] = w

    def _clear_param_form(self):
        for i in reversed(range(self.param_form.count())):
            item = self.param_form.itemAt(i)
            if item.widget():
                item.widget().deleteLater()
        self._param_widgets.clear()
        self._current_algo = None

    def get_params(self, algo_name: str) -> dict:
        """返回指定算法当前表单参数（含默认值与 seed）。"""
        cls = self.registry.get(algo_name)
        if cls is None:
            return {}
        params = dict(cls.default_params)
        if self._current_algo == algo_name:
            for key, w in self._param_widgets.items():
                if isinstance(w, QSpinBox):
                    params[key] = w.value()
                else:
                    params[key] = w.value()
        params["seed"] = int(params.get("seed", 42))
        return params

    def get_all_params(self) -> Dict[str, dict]:
        return {name: self.get_params(name) for name in self.selected_names()}

    def _restore_defaults(self):
        if self._current_algo:
            self._load_param_form(self._current_algo)

    # ---------------- 参数方案 ----------------
    def _save_scheme(self):
        if not self._current_algo:
            QMessageBox.information(self, "提示", "请先选择算法")
            return
        os.makedirs(PARAM_SCHEME_DIR, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "保存参数方案", os.path.join(PARAM_SCHEME_DIR,
                                          f"{self._current_algo}_方案.json"),
            "JSON (*.json)")
        if not path:
            return
        data = {"algorithm": self._current_algo,
                "params": self.get_params(self._current_algo)}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "完成", f"方案已保存：\n{path}")

    def _load_scheme(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载参数方案", PARAM_SCHEME_DIR, "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            algo = data.get("algorithm")
            if algo and algo in self.registry.names():
                self._load_param_form(algo)
                for key, val in data.get("params", {}).items():
                    if key in self._param_widgets:
                        w = self._param_widgets[key]
                        w.setValue(val)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载失败：{e}")

    # ---------------- 元信息 ----------------
    def _show_meta(self, algo_name: str):
        m = ALGORITHM_META.get(algo_name, {})
        cls = self.registry.get(algo_name)
        if cls is None:
            return
        lines = [f"作者/来源：{m.get('author', '') or getattr(cls, 'author', '')}",
                 f"文献引用：{m.get('citation', '') or getattr(cls, 'citation', '')}",
                 f"适用范围：{m.get('scope', '') or getattr(cls, 'scope', '')}",
                 f"参数说明：{m.get('params_note', '') or getattr(cls, 'params_note', '')}"]
        self.meta_detail.setText("\n".join(l for l in lines if l))

    def _on_baseline(self, text: str):
        self.baseline_changed.emit(text)
