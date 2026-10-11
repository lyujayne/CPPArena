# -*- coding: utf-8 -*-
"""分割（凸分解）结果对比窗口：行=地块，列=分割算法，叠加显示分解图形。

点击主窗口画布工具栏「分解对比」按钮弹出；每个子图展示该地块在对应算法
分割方式下的凸子区域（不同填色）、子区数量与旋转卡壳最小宽度之和
（Σ宽度越小→牛耕扫描条带越少→转弯越少），并标注原始凹点。
"""
from typing import List, Optional

import numpy as np
from matplotlib.backends.backend_qtagg import (FigureCanvasQTAgg,
                                               NavigationToolbar2QT)
from matplotlib.figure import Figure
from matplotlib.patches import Polygon as MplPolygon
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from algorithms.aco.polygon_decomp import (clean_ring, ensure_ccw,
                                           reflex_indices)
from algorithms.aco.pso_decomp import rotating_calipers_width
from algorithms.common import decompose_region_with

import matplotlib.cm as _cm  # noqa: E402

_FILL = _cm.Set3.colors


class DecompCompareDialog(QDialog):
    """各算法分割结果对比窗口。"""

    def __init__(self, dataset, algo_names: List[str],
                 registry=None, params_by_algo: Optional[dict] = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("分割方式分解对比")
        self.resize(1100, 720)

        self._dataset = dataset
        self._algo_names = list(algo_names)
        self._registry = registry
        self._params_by_algo = params_by_algo or {}

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)

        self.figure = Figure(dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        v.addWidget(self.toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.addWidget(self.canvas)
        host_layout.addStretch(1)
        scroll.setWidget(host)
        v.addWidget(scroll, 1)

        row = QHBoxLayout()
        self.btn_rebuild = QPushButton("重新生成")
        self.btn_rebuild.clicked.connect(self.render)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(self.btn_rebuild)
        row.addWidget(self.btn_close)
        v.addLayout(row)

        self.render()

    # ----------------------------------------------------------------
    def _display(self, algo_name: str) -> str:
        if self._registry is not None:
            m = self._registry.meta(algo_name)
            return m.get("display_name") or algo_name
        return algo_name

    def render(self):
        """计算各算法对各地块的分解并绘图（行=地块，列=算法）。"""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.btn_rebuild.setEnabled(False)
        try:
            self._render_impl()
        finally:
            self.btn_rebuild.setEnabled(True)
            QApplication.restoreOverrideCursor()

    def _render_impl(self):
        self.figure.clear()
        regions = [r for r in self._dataset.regions if len(r.vertices) >= 3]
        n_rows = max(1, len(regions))
        n_cols = max(1, len(self._algo_names))
        # 动态尺寸：单元格约 4.2×3.8 英寸，地块多时可滚动
        self.figure.set_size_inches(max(4.6 * n_cols, 6.0),
                                    max(3.9 * n_rows, 4.5))
        gs = self.figure.add_gridspec(n_rows, n_cols, hspace=0.28, wspace=0.12)

        for ri, region in enumerate(regions):
            verts = ensure_ccw(clean_ring(region.vertices))
            reflex = reflex_indices(verts)
            for ci, algo in enumerate(self._algo_names):
                ax = self.figure.add_subplot(gs[ri, ci])
                if ri == 0:
                    ax.set_title(self._display(algo), fontsize=11,
                                 fontweight="bold")
                try:
                    params = self._params_by_algo.get(algo)
                    pieces, info = decompose_region_with(algo, verts, params)
                    self._draw_cell(ax, verts, pieces, reflex)
                    width_sum = sum(rotating_calipers_width(p) for p in pieces)
                    seg = info.get("segmentation", "")
                    extra = ""
                    if info.get("n_reflex") is not None:
                        extra = f"，凹点 {info.get('n_reflex')}"
                    ax.set_xlabel(f"{len(pieces)} 个凸子区，Σ宽度="
                                  f"{width_sum:.1f} m（{seg}{extra}）",
                                  fontsize=8.5)
                except Exception as e:
                    ax.text(0.5, 0.5, f"分解失败：{type(e).__name__}: {e}",
                            ha="center", va="center", fontsize=9, color="red",
                            transform=ax.transAxes, wrap=True)
                if ci == 0:
                    ax.annotate(region.name, xy=(0.0, 0.5),
                                xytext=(-0.22, 0.5), xycoords="axes fraction",
                                textcoords="axes fraction", rotation=90,
                                ha="center", va="center", fontsize=10,
                                fontweight="bold")
                ax.set_aspect("equal", adjustable="datalim")
                ax.grid(True, alpha=0.25)
                ax.tick_params(labelsize=7)

        self.figure.suptitle("各算法分割（凸分解）结果对比", fontsize=13,
                             y=0.995)
        self.canvas.draw_idle()

    @staticmethod
    def _draw_cell(ax, verts, pieces, reflex_idx):
        # 凸子区填色
        for i, p in enumerate(pieces):
            ax.add_patch(MplPolygon(p, closed=True,
                                    facecolor=_FILL[i % len(_FILL)],
                                    edgecolor="#1f6f43", linewidth=1.1,
                                    alpha=0.85, zorder=2))
        # 原始地块外边界
        arr = np.asarray(verts + [verts[0]], dtype=float)
        ax.plot(arr[:, 0], arr[:, 1], "-", color="black", linewidth=1.8,
                zorder=4)
        # 原始凹点标红
        if reflex_idx:
            rx = [verts[i][0] for i in reflex_idx]
            ry = [verts[i][1] for i in reflex_idx]
            ax.scatter(rx, ry, s=26, marker="o", facecolor="red",
                       edgecolor="black", linewidths=0.6, zorder=5,
                       label=f"凹点({len(reflex_idx)})")
            ax.legend(loc="upper right", fontsize=7)
        ax.autoscale_view()
        ax.margins(0.08)
