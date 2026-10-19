# -*- coding: utf-8 -*-
"""相机与飞行参数面板（全局共享，保证公平比较口径）。

- 参数项与默认值对齐需求规格 4.3.1（焦距 5.2mm、传感器 7.6×5.7mm、
  飞行高度 100m、旁向/航向重叠率 80%）；
- 实时计算显示：GSD、单幅影像覆盖宽/高、航线间距、航向拍照间距。
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QLabel, QSpinBox, QVBoxLayout, QWidget)

from config.default_params import CAMERA_DEFAULTS, CAMERA_PARAM_ORDER, compute_camera

_INT_KEYS = {"image_width_px", "image_height_px"}


class CameraPanel(QWidget):
    """相机参数配置 + 派生量实时计算。"""

    changed = Signal()          # 任一参数变化
    reset_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._widgets = {}
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)

        g = QGroupBox("相机与飞行参数（全局共享）")
        form = QFormLayout(g)
        self.boundary_combo = QComboBox()
        self.boundary_combo.addItem('子区内扫描（端点裁至边界）', 'inside')
        self.boundary_combo.addItem('条带包络覆盖（允许越界）', 'envelope')
        self.boundary_combo.setToolTip('子区内模式限制扫描和区内换行；起降和子区之间的转场可经过区外。覆盖率按实际相机足迹计算。')
        self.boundary_combo.currentIndexChanged.connect(self._on_change)
        form.addRow('扫描边界', self.boundary_combo)
        self.boundary_help = QLabel()
        self.boundary_help.setWordWrap(True)
        self.boundary_help.setStyleSheet('color:#475569;padding:5px;')
        form.addRow(self.boundary_help)
        for key, label in CAMERA_PARAM_ORDER:
            default = CAMERA_DEFAULTS[key]
            if key in _INT_KEYS:
                w = QSpinBox()
                w.setRange(1, 40000)
                w.setValue(int(default))
            else:
                w = QDoubleSpinBox()
                w.setRange(0.001, 1e6)
                w.setDecimals(3 if key != "flight_height_m" else 1)
                w.setValue(float(default))
            w.valueChanged.connect(self._on_change)
            form.addRow(label, w)
            self._widgets[key] = w
        v.addWidget(g)

        g2 = QGroupBox("实时计算（派生量）")
        f2 = QFormLayout(g2)
        self.lbl_gsd = QLabel("--")
        self.lbl_cov_w = QLabel("--")
        self.lbl_cov_h = QLabel("--")
        self.lbl_line = QLabel("--")
        self.lbl_along = QLabel("--")
        f2.addRow("GSD (m/px)", self.lbl_gsd)
        f2.addRow("单幅覆盖宽 (m)", self.lbl_cov_w)
        f2.addRow("单幅覆盖高 (m)", self.lbl_cov_h)
        f2.addRow("旁向航线间距 (m)", self.lbl_line)
        f2.addRow("航向拍照间距 (m)", self.lbl_along)
        v.addWidget(g2)

        hint = QLabel("航线间距 = 覆盖宽 × (1 − 旁向重叠率)，"
                      "是全部算法共用的覆盖扫描间距。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:11px;")
        v.addWidget(hint)
        v.addStretch(1)

        self._refresh_computed()

    # ---------------- 读写 ----------------
    def get_camera(self) -> dict:
        return dict({k: w.value() for k, w in self._widgets.items()}, scan_boundary_mode=self.boundary_combo.currentData())

    def set_camera(self, cam: dict):
        self.boundary_combo.blockSignals(True)
        self.boundary_combo.setCurrentIndex(max(0, self.boundary_combo.findData(cam.get('scan_boundary_mode', 'inside'))))
        self.boundary_combo.blockSignals(False)
        for k, w in self._widgets.items():
            if k in cam:
                w.blockSignals(True)
                w.setValue(float(cam[k]))
                w.blockSignals(False)
        self._refresh_computed()

    # ---------------- 计算 ----------------
    def _on_change(self, *_):
        self._refresh_computed()
        self.changed.emit()

    def _refresh_computed(self):
        if hasattr(self, 'boundary_help'):
            self.boundary_help.setText(
                '子区内扫描：扫描端点裁到凸子区边界，区内换行也留在子区内；尖角可能漏扫。起降与子区转场仍可经过区外。'
                if self.boundary_combo.currentData() == 'inside' else
                '条带包络覆盖：为覆盖整条带的尖角，沿扫描方向延长航段；扫描及换行可越过子区边界。按相机足迹检验覆盖，不代表具备避障能力。')
        try:
            c = compute_camera(self.get_camera())
            self.lbl_gsd.setText(f"{c['gsd']:.4f}")
            self.lbl_cov_w.setText(f"{c['coverage_w']:.2f}")
            self.lbl_cov_h.setText(f"{c['coverage_h']:.2f}")
            self.lbl_line.setText(f"{c['line_spacing']:.2f}")
            self.lbl_along.setText(f"{c['along_spacing']:.2f}")
        except Exception:
            for lbl in (self.lbl_gsd, self.lbl_cov_w, self.lbl_cov_h,
                        self.lbl_line, self.lbl_along):
                lbl.setText("参数非法")
