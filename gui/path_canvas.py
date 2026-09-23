# -*- coding: utf-8 -*-
"""路径绘图画布：区域边界、分解子区域、内部覆盖路径、区域间连接、起降点分层渲染。

支持：
- 图片底图导入 + 手动勾绘多边形 / 标记起飞点；
- 多算法结果叠加对比（不同颜色/线型）；
- 缩放、平移、点选查看区域；
- 图层开关与「原始/分解」预览切换。
"""
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.patches import Polygon as MplPolygon
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QWidget, QVBoxLayout

from algorithms.aco.polygon_decomp import convex_decompose
from data.dataset import Dataset

XY = Tuple[float, float]

# 多算法叠加配色
ALGO_COLORS = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd",
               "#ff7f0e", "#8c564b", "#e377c2", "#7f7f7f"]
ALGO_LINESTYLES = ["-", "--", "-.", ":"]


class PathCanvas(QWidget):
    """基于 matplotlib 的路径画布。"""

    region_picked = Signal(int)          # 区域 id
    polygon_drawn = Signal(object)       # 手动勾绘完成的顶点列表
    launch_point_set = Signal(object)    # 起飞点坐标

    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure(figsize=(8, 7), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        # 移除 Back/Forward（左右箭头），界面更简洁
        for _act in list(self.toolbar.actions()):
            if _act.text().lower() in ("back", "forward"):
                self.toolbar.removeAction(_act)
        self._toolbar_row = QHBoxLayout()
        self._toolbar_row.setContentsMargins(0, 0, 0, 0)
        self._toolbar_row.addWidget(self.toolbar)
        self._toolbar_row.addSpacing(16)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._toolbar_row)
        layout.addWidget(self.canvas)
        self.ax = self.figure.add_subplot(111)

        self._dataset: Optional[Dataset] = None
        self._results: Dict[str, dict] = {}      # algo -> run dict
        self._reset_view = True                  # 新数据集时重新自适应视图
        self._decomposed = False
        self._layers = {"regions": True, "subregions": True, "internal": True,
                        "transitions": True, "launch": True, "image": True,
                        "suborder": True}

        # 交互状态
        self._draw_mode = None        # None | "polygon" | "launch"
        self._temp_pts: List[XY] = []
        self._temp_artist = None

        self.canvas.mpl_connect("pick_event", self._on_pick)
        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)

    # ------------------------------------------------------------ 数据
    def set_dataset(self, dataset: Optional[Dataset], decomposed: bool = False):
        self._dataset = dataset
        self._decomposed = decomposed
        self._reset_view = True
        self.redraw()

    def set_results(self, results: Dict[str, dict]):
        self._results = dict(results or {})
        self.redraw()

    def add_toolbar_extra(self, widget):
        """把额外控件（如显示选项复选框）追加到画布工具栏右侧。"""
        self._toolbar_row.addWidget(widget)
        self._toolbar_row.addSpacing(8)

    def set_decomposed(self, on: bool):
        self._decomposed = bool(on)
        self.redraw()

    def set_layer(self, layer: str, on: bool):
        if layer in self._layers:
            self._layers[layer] = bool(on)
            self.redraw()

    def start_draw_polygon(self):
        self._draw_mode = "polygon"
        self._temp_pts = []
        self._safe_remove_temp()
        self._status_hint("勾绘模式：单击添加顶点，双击闭合，或点「完成勾绘」")

    def start_set_launch(self):
        self._draw_mode = "launch"
        self._status_hint("起飞点模式：单击画布放置起飞点")

    def finish_polygon(self):
        """手动闭合当前多边形（双击不可用时的备选）。"""
        if self._draw_mode == "polygon" and len(self._temp_pts) >= 3:
            self.polygon_drawn.emit(list(self._temp_pts))
            self._temp_pts = []
            self._safe_remove_temp()
            self.canvas.draw_idle()
        elif self._draw_mode == "polygon":
            self._status_hint("至少需要 3 个顶点才能闭合")

    def cancel_draw(self):
        self._draw_mode = None
        self._temp_pts = []
        self._safe_remove_temp()
        self.canvas.draw_idle()

    def _status_hint(self, msg: str):
        w = self.window()
        if w is not None and hasattr(w, "statusBar"):
            w.statusBar().showMessage(msg, 5000)

    # ------------------------------------------------------------ 绘制
    def _safe_remove_temp(self):
        """安全移除临时绘制线段（ax.clear 后引用可能已失效）。"""
        if self._temp_artist is not None:
            try:
                self._temp_artist.remove()
            except (NotImplementedError, ValueError):
                pass
            self._temp_artist = None

    def redraw(self):
        preserve_lim = (self.ax.get_xlim(), self.ax.get_ylim())
        self.ax.clear()
        self._temp_artist = None
        ds = self._dataset
        if ds is None:
            self.canvas.draw_idle()
            return

        # 背景图片
        if (self._layers["image"] and ds.bg_image_path
                and os.path.exists(ds.bg_image_path) and ds.bg_bounds_utm):
            try:
                img = plt_image = None
                from matplotlib.image import imread
                img = imread(ds.bg_image_path)
                minx, miny, maxx, maxy = ds.bg_bounds_utm
                self.ax.imshow(img, extent=(minx, maxx, miny, maxy),
                               zorder=0, alpha=0.9)
            except Exception:
                pass

        for region in ds.regions:
            pts = region.vertices
            if not pts:
                continue
            if self._layers["regions"]:
                poly = MplPolygon(pts, closed=True, fill=False,
                                  edgecolor="#333333", linewidth=1.6, zorder=2)
                poly.set_picker(6)
                self.ax.add_patch(poly)
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                self.ax.text(cx, cy, region.name, fontsize=9, ha="center",
                             va="center", zorder=5,
                             bbox=dict(boxstyle="round,pad=0.2",
                                       facecolor="white", alpha=0.7))

            if self._decomposed and self._layers["subregions"]:
                try:
                    parts = convex_decompose(pts)
                except Exception:
                    parts = []
                for part in parts:
                    self.ax.add_patch(MplPolygon(
                        part, closed=True, fill=False,
                        edgecolor="#ff7f0e", linewidth=1.0, alpha=0.8, zorder=3))

        # 起飞点
        if self._layers["launch"] and ds.launch_point:
            lx, ly = ds.launch_point
            self.ax.plot([lx], [ly], marker="^", markersize=11, color="#e6194b",
                         zorder=6, label="起飞点")
            self.ax.annotate("起飞点", (lx, ly), textcoords="offset points",
                             xytext=(8, 6), fontsize=9, color="#e6194b")

        # 多算法结果叠加
        for k, (algo, run) in enumerate(self._results.items()):
            color = ALGO_COLORS[k % len(ALGO_COLORS)]
            ls = ALGO_LINESTYLES[(k // len(ALGO_COLORS)) % len(ALGO_LINESTYLES)]
            wps = run.get("waypoints") or []
            if not wps:
                continue
            pts_arr = np.asarray(wps, dtype=float)
            if self._layers["transitions"]:
                self.ax.plot(pts_arr[:, 0], pts_arr[:, 1], ls, color=color,
                             linewidth=1.4, alpha=0.9,
                             label=f"{algo} ({run.get('total_distance', 0):.0f} m)",
                             zorder=4)
            if self._layers["internal"]:
                for path in run.get("internal_paths", []):
                    if len(path) < 2:
                        continue
                    p = np.asarray(path, dtype=float)
                    self.ax.plot(p[:, 0], p[:, 1], ls, color=color, linewidth=0.7,
                                 alpha=0.55, zorder=3)
            if self._layers.get("suborder"):
                for seq in run.get("subregion_sequence", []):
                    poly = seq.get("polygon") or []
                    if len(poly) < 3:
                        continue
                    cxx = sum(q[0] for q in poly) / len(poly)
                    cyy = sum(q[1] for q in poly) / len(poly)
                    self.ax.text(cxx, cyy, str(seq.get("order", "")),
                                 fontsize=11, fontweight="bold", color="#1f3b99",
                                 ha="center", va="center", zorder=8,
                                 bbox=dict(boxstyle="circle,pad=0.25",
                                           facecolor="white", edgecolor="#1f3b99",
                                           lw=1.2))

        self.ax.set_aspect("equal", adjustable="datalim")
        if self._reset_view:
            self.ax.autoscale()
            self._reset_view = False
        else:
            self.ax.set_xlim(preserve_lim[0])
            self.ax.set_ylim(preserve_lim[1])
        if self.ax.get_legend_handles_labels()[0]:
            self.ax.legend(loc="upper right", fontsize=8)
        self.ax.set_xlabel("东向 (m)")
        self.ax.set_ylabel("北向 (m)")
        self.ax.set_title(f"{ds.name} —— 覆盖路径规划")
        self.ax.grid(True, alpha=0.3)
        self.canvas.draw_idle()

    # ------------------------------------------------------------ 交互
    def _on_pick(self, event):
        if event.mouseevent.dblclick:
            return
        patch = event.artist
        if isinstance(patch, MplPolygon) and self._dataset:
            xy = patch.get_xy()[:-1]
            for region in self._dataset.regions:
                if len(region.vertices) == len(xy):
                    if np.allclose(np.asarray(region.vertices), np.asarray(xy)):
                        self.region_picked.emit(region.id)
                        return

    def _on_click(self, event):
        if event.inaxes != self.ax:
            return
        if event.button != 1:
            return
        if self._draw_mode == "polygon":
            if event.dblclick:
                if len(self._temp_pts) >= 3:
                    self.polygon_drawn.emit(list(self._temp_pts))
                    self._temp_pts = []
                    self._safe_remove_temp()
                    self._draw_mode = None
                    self.canvas.draw_idle()
                return
            if event.xdata is None or event.ydata is None:
                return
            self._temp_pts.append((float(event.xdata), float(event.ydata)))
            self._update_temp_artist()
        elif self._draw_mode == "launch":
            if event.xdata is None or event.ydata is None:
                return
            self.launch_point_set.emit((float(event.xdata), float(event.ydata)))
            self._draw_mode = None
            self._status_hint("起飞点已设置")

    def _on_motion(self, event):
        if (self._draw_mode == "polygon" and event.inaxes == self.ax
                and event.xdata is not None and event.ydata is not None):
            if self._temp_pts:
                self._update_temp_artist((float(event.xdata),
                                          float(event.ydata)))
                self.canvas.draw_idle()

    def _update_temp_artist(self, cursor: Optional[XY] = None):
        self._safe_remove_temp()
        pts = list(self._temp_pts)
        if cursor:
            pts.append(cursor)
        if len(pts) == 1:
            self._temp_artist = self.ax.plot([pts[0][0]], [pts[0][1]], "o",
                                             color="#e6194b", zorder=7)[0]
        elif len(pts) >= 2:
            arr = np.asarray(pts)
            self._temp_artist = self.ax.plot(arr[:, 0], arr[:, 1], "-o",
                                             color="#e6194b", zorder=7)[0]
        self.canvas.draw_idle()

    def _on_scroll(self, event):
        # 滚轮缩放（与工具栏兼容）
        scale = 1.2 if event.button == "up" else 1 / 1.2
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()
        x0, x1 = xlim
        y0, y1 = ylim
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        self.ax.set_xlim(cx + (x0 - cx) * scale, cx + (x1 - cx) * scale)
        self.ax.set_ylim(cy + (y0 - cy) * scale, cy + (y1 - cy) * scale)
        self.canvas.draw_idle()

    def fit_view(self):
        self.redraw()

    def reset_view(self):
        self.redraw()

    def save_figure(self, path: str, dpi: int = 300):
        self.figure.savefig(path, dpi=dpi, bbox_inches="tight")
        return path
