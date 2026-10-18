# -*- coding: utf-8 -*-
"""分割（凸分解）结果对比窗口：行=地块，列=分割算法，叠加显示分解图形，
并在下方给出评价各分割方式的权威指标表。

点击主窗口画布工具栏「分解对比」按钮弹出。

界面结构：
  顶部标题横幅 → Matplotlib 导航工具栏 → 可上下拖动的分割条
    （上：分解图形网格（可滚动）；下：分割方式评价指标表）
  → 底部操作按钮（放大子图 / 重新生成 / 导出指标 / 关闭）。

评价指标（均有权威出处，见窗口脚注）：
  凸子区数量、最小宽度之和 Σw、切割线总长度、Steiner 点数量、面积变异系数
  CV、平均形状规则度 w/D、覆盖率、分割耗时；每行自动高亮该指标的最优算法。
"""
import csv
import math
import os
import time
from typing import Dict, List, Optional

import numpy as np
from matplotlib import rcParams
from matplotlib.backends.backend_qtagg import (FigureCanvasQTAgg,
                                               NavigationToolbar2QT)
from matplotlib.figure import Figure
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.ticker import MaxNLocator
from shapely.geometry import LineString, Point, Polygon as ShPolygon

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFrame,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QScrollArea, QSizePolicy,
                               QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from algorithms.aco.polygon_decomp import (clean_ring, ensure_ccw,
                                           reflex_indices, signed_area)
from algorithms.aco.pso_decomp import rotating_calipers_width
from algorithms.common import decompose_region_with

import matplotlib.cm as _cm  # noqa: E402

_FILL = _cm.Set3.colors

# 主色调（深青绿），避免大面积紫/靛
PRIMARY = "#14695d"
ACCENT = "#178a76"


# ============================================================ 指标定义
# (key, 显示名, 单位, 方向 down=越小越好/up=越大越好, 格式)
METRIC_DEFS = [
    ("n_cells",    "凸子区数量",          "个", "down", "{:.0f}"),
    ("width_sum",  "最小宽度之和 Σw",     "m",  "down", "{:.2f}"),
    ("cut_length", "切割线总长度",        "m",  "down", "{:.2f}"),
    ("n_steiner",  "Steiner 点数量",      "个", "down", "{:.0f}"),
    ("area_cv",    "面积变异系数 CV",     "%",  "down", "{:.1f}"),
    ("regularity", "平均形状规则度 w/D",  "",   "up",   "{:.3f}"),
    ("coverage",   "分割覆盖率",          "%",  "up",   "{:.2f}"),
    ("runtime",    "分割耗时",            "s",  "down", "{:.3f}"),
]

# 指标权威依据（脚注，分条换行显示）
METRIC_SOURCES = (
    "指标依据（↓ 越小越好，↑ 越大越好）：\n"
    "① 凸子区数量 / 切割线总长度 / Steiner 点：凸分解两大经典最优准则"
    "（Chazelle & Dobkin 1985 最小子区数；Keil 1985 最小边长凸划分；"
    "Chazelle《Optimal Convex Decompositions》的 Steiner 点）。\n"
    "② 最小宽度之和 Σw：Li et al. 2011《Enhanced exact cellular decomposition》§4.3。\n"
    "③ 面积变异系数 CV：多机均衡分割文献（子区负载均衡）。\n"
    "④ 形状规则度 w/D：子区紧凑度，越接近方形越利于牛耕扫描。\n"
    "⑤ 分割覆盖率：子区并集与原区域交集面积/原面积；航拍覆盖另按相机足迹验证。\n"
    "⑥ 分割耗时：计算效率。"
)


# ============================================================ JPEG 保存工具栏
class JpegNavigationToolbar(NavigationToolbar2QT):
    """导航工具栏：保存图片默认/首选 JPEG（.jpg，质量 95）。"""

    def save_figure(self, *args):
        """弹出保存对话框，默认格式为 JPEG（其余格式仍可在下拉中选择）。"""
        try:
            start_dir = str(rcParams["savefig.directory"] or os.path.expanduser("~"))
        except Exception:
            start_dir = os.path.expanduser("~")
        try:
            stem = os.path.splitext(self.canvas.get_default_filename())[0]
        except Exception:
            stem = "decomp_compare"
        base = stem + ".jpg"
        start = os.path.join(start_dir, base) if start_dir else base
        filt = ("JPEG 图片 (*.jpg *.jpeg);;PNG 图片 (*.png);;PDF (*.pdf);;"
                "SVG (*.svg);;所有文件 (*)")
        path, _ = QFileDialog.getSaveFileName(
            self.canvas.window(), "保存图片（默认 JPEG）", start, filt,
            "JPEG 图片 (*.jpg *.jpeg)")
        if not path:
            return
        low = path.lower()
        if not low.endswith((".jpg", ".jpeg", ".png", ".pdf", ".svg")):
            path += ".jpg"
        directory = os.path.dirname(path)
        if directory:
            rcParams["savefig.directory"] = directory
        kwargs = dict(dpi=200, facecolor="white")
        if path.lower().endswith((".jpg", ".jpeg")):
            kwargs["format"] = "jpeg"
            kwargs["pil_kwargs"] = {"quality": 95}
        self.canvas.figure.savefig(path, **kwargs)


# ============================================================ 单图放大窗口
class EnlargedCellDialog(QDialog):
    """单个（地块 × 分割方式）子图的放大查看窗口，自带 JPEG 保存工具栏。"""

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        verts = data["verts"]
        reflex = data["reflex"]
        pieces = data["pieces"]
        region_name = data["region_name"]
        algo_display = data["algo_display"]
        seg_label = data["seg_label"]

        self.setWindowTitle(f"放大查看 — {region_name} — {algo_display}")
        self.resize(920, 800)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)

        self.figure = Figure(dpi=110, figsize=(9, 7.6))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = JpegNavigationToolbar(self.canvas, self)
        v.addWidget(self.toolbar)
        v.addWidget(self.canvas)

        ax = self.figure.add_subplot(111)
        DecompCompareDialog._draw_cell(ax, verts, pieces, reflex)
        ax.set_title(f"{region_name}  —  {algo_display}",
                     fontsize=13, fontweight="bold")
        ax.set_xlabel(seg_label, fontsize=11)
        ax.set_aspect("equal", adjustable="datalim")
        ax.grid(True, alpha=0.25)

        row = QHBoxLayout()
        hint = QLabel("提示：工具栏可矩形缩放/平移；保存默认 JPEG。点关闭返回。")
        hint.setStyleSheet("color:#666;font-size:11px;")
        row.addWidget(hint)
        row.addStretch(1)
        btn_close = QPushButton("关闭")
        btn_close.setObjectName("PrimaryButton")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        v.addLayout(row)


# ============================================================ 指标几何计算
def _cut_info(verts: List, pieces: List[List]) -> tuple:
    """计算单个地块的 (切割线总长度, Steiner 点数量)。

    内部切割边：子区边的中点不在原多边形边界上者；每条内边被相邻两片各记录
    一次，按中点去重后计长度。Steiner 点：子区顶点中不属于原多边形顶点者。
    """
    orig = ShPolygon(verts).buffer(0)
    boundary = orig.boundary
    orig_pts = {(round(x, 6), round(y, 6)) for x, y in verts}

    seen_mid: set = set()
    cut_length = 0.0
    steiner: set = set()
    for piece in pieces:
        m = len(piece)
        for k in range(m):
            a = piece[k]
            b = piece[(k + 1) % m]
            mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            mkey = (round(mid[0], 6), round(mid[1], 6))
            # 中点到原边界距离≈0 → 该边在原边界上；否则为内部切割边
            if boundary.distance(Point(mid)) > 1e-6 and mkey not in seen_mid:
                seen_mid.add(mkey)
                cut_length += math.hypot(b[0] - a[0], b[1] - a[1])
            for pt in (a, b):
                pkey = (round(pt[0], 6), round(pt[1], 6))
                if pkey not in orig_pts:
                    steiner.add(pkey)
    return cut_length, len(steiner)


def _diameter(poly: List) -> float:
    """凸多边形顶点间最大距离（直径）。"""
    best = 0.0
    for i in range(len(poly)):
        for j in range(i + 1, len(poly)):
            d = math.hypot(poly[i][0] - poly[j][0], poly[i][1] - poly[j][1])
            if d > best:
                best = d
    return best


def compute_metrics(records: List[dict]) -> Dict[str, float]:
    """对一个统计范围（单地块或全部地块的 records 列表）计算全部指标。

    :param records: [{"verts", "pieces", "runtime"}, ...]（每地块一项）
    """
    all_pieces: List[List] = []
    cut_length = 0.0
    n_steiner = 0
    union_area = 0.0
    orig_area = 0.0
    runtime = 0.0

    for rec in records:
        verts = rec["verts"]
        pieces = rec["pieces"]
        all_pieces.extend(pieces)
        c_len, n_st = _cut_info(verts, pieces)
        cut_length += c_len
        n_steiner += n_st
        from shapely.ops import unary_union
        gs = unary_union([ShPolygon(p).buffer(0) for p in pieces])
        union_area += gs.intersection(ShPolygon(verts)).area
        orig_area += abs(signed_area(verts))
        runtime += float(rec.get("runtime", 0.0))

    n_cells = len(all_pieces)
    widths = [rotating_calipers_width(p) for p in all_pieces]
    width_sum = sum(widths)

    areas = np.array([abs(signed_area(p)) for p in all_pieces], dtype=float)
    cv = float(areas.std(ddof=0) / areas.mean() * 100.0) if areas.mean() > 0 else 0.0

    regs = []
    for p in all_pieces:
        d = _diameter(p)
        w = rotating_calipers_width(p)
        if d > 0:
            regs.append(w / d)
    regularity = float(np.mean(regs)) if regs else 0.0

    coverage = union_area / orig_area * 100.0 if orig_area > 0 else 0.0

    return {
        "n_cells": float(n_cells),
        "width_sum": float(width_sum),
        "cut_length": float(cut_length),
        "n_steiner": float(n_steiner),
        "area_cv": cv,
        "regularity": regularity,
        "coverage": float(coverage),
        "runtime": runtime,
    }


# ============================================================ 主对比窗口
class DecompCompareDialog(QDialog):
    """各算法分割结果对比窗口（图形 + 权威评价指标表）。"""

    def __init__(self, dataset, algo_names: List[str],
                 registry=None, params_by_algo: Optional[dict] = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("分割方式分解对比")
        # 默认占屏幕绝大部分，保证一屏内看全（地块×算法）对比
        from PySide6.QtWidgets import QApplication
        _scr = (parent.screen() if parent is not None else None) \
            or QApplication.primaryScreen()
        _geo = _scr.availableGeometry()
        self.resize(int(_geo.width() * 0.94), int(_geo.height() * 0.92))

        self._dataset = dataset
        self._algo_names = list(algo_names)
        self._registry = registry
        self._params_by_algo = params_by_algo or {}

        # 缓存：(地块索引, 算法) -> {verts, pieces, reflex, runtime, seg_label}
        self._cache: Dict[tuple, dict] = {}
        self._zoom_mode = False
        self._cell_by_ax: dict = {}

        self._build_ui()
        self.render()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._build_header())

        self.figure = Figure(dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = JpegNavigationToolbar(self.canvas, self)
        root.addWidget(self.toolbar)
        self.canvas.mpl_connect("button_press_event", self._on_canvas_click)

        # 图形区占满主窗口；评价指标改为按钮弹出的独立窗口（默认不占位）
        self.canvas.setMinimumHeight(220)
        root.addWidget(self.canvas, 1)

        # 评价指标弹窗（默认隐藏，点底部「评价指标」按钮弹出）
        self.metrics_dlg = QDialog(self)
        self.metrics_dlg.setWindowTitle("分割方式评价指标")
        self.metrics_dlg.resize(980, 620)
        mlay = QVBoxLayout(self.metrics_dlg)
        mlay.setContentsMargins(0, 0, 0, 0)
        mlay.addWidget(self._build_metrics_panel())

        root.addLayout(self._build_bottom_row())

        self.setStyleSheet(self._stylesheet())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(58)
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 8, 16, 8)
        col = QVBoxLayout()
        t = QLabel("分割方式分解对比")
        t.setObjectName("HeaderTitle")
        s = QLabel("行＝待覆盖地块，列＝分割算法；点底部「评价指标」按钮查看各分割方式的权威指标")
        s.setObjectName("HeaderSub")
        col.addWidget(t)
        col.addWidget(s)
        h.addLayout(col)
        h.addStretch(1)
        return header

    def _build_metrics_panel(self) -> QGroupBox:
        group = QGroupBox("分割方式评价指标")
        g = QVBoxLayout(group)
        g.setContentsMargins(10, 12, 10, 8)

        top = QHBoxLayout()
        top.addWidget(QLabel("统计范围："))
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("全部地块（汇总）", -1)
        for ri, region in enumerate(self._valid_regions()):
            self.scope_combo.addItem(region.name, ri)
        self.scope_combo.currentIndexChanged.connect(self._populate_metrics)
        top.addWidget(self.scope_combo)
        top.addStretch(1)
        self.btn_export = QPushButton("导出指标 CSV")
        self.btn_export.clicked.connect(self._export_csv)
        top.addWidget(self.btn_export)
        g.addLayout(top)

        self.metric_table = QTableWidget()
        self.metric_table.setColumnCount(len(self._algo_names) + 1)
        self.metric_table.setRowCount(len(METRIC_DEFS))
        self.metric_table.verticalHeader().setVisible(False)
        self.metric_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.metric_table.setSelectionMode(QTableWidget.NoSelection)
        self.metric_table.setFocusPolicy(Qt.NoFocus)
        self.metric_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.metric_table.horizontalHeader().setFixedHeight(34)
        self.metric_table.verticalHeader().setDefaultSectionSize(30)
        g.addWidget(self.metric_table)

        note = QLabel(METRIC_SOURCES)
        note.setWordWrap(True)
        note.setObjectName("SourceNote")
        g.addWidget(note)
        return group

    def _build_bottom_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.tip_label = QLabel("双击任一子图可放大查看；保存图片默认 JPEG。")
        self.tip_label.setObjectName("TipLabel")
        row.addWidget(self.tip_label)
        row.addStretch(1)

        self.btn_metrics = QPushButton("评价指标")
        self.btn_metrics.setToolTip("单独查看各分割方式的权威评价指标表")
        self.btn_metrics.clicked.connect(self._show_metrics)
        self.btn_zoom = QPushButton("放大子图")
        self.btn_zoom.setToolTip("点击后，再单击要放大的子图（也可直接双击子图放大）")
        self.btn_zoom.setCheckable(True)
        self.btn_zoom.clicked.connect(self._on_zoom_button)
        self.btn_rebuild = QPushButton("重新生成")
        self.btn_rebuild.setObjectName("PrimaryButton")
        self.btn_rebuild.clicked.connect(self.render)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        for b in (self.btn_metrics, self.btn_zoom, self.btn_rebuild, self.btn_close):
            b.setMinimumHeight(30)
            b.setMinimumWidth(92)
            row.addWidget(b)
        return row

    def _show_metrics(self):
        """弹出评价指标窗口，并刷新为最新结果。"""
        self._populate_metrics()
        self.metrics_dlg.show()
        self.metrics_dlg.raise_()
        self.metrics_dlg.activateWindow()

    @staticmethod
    def _stylesheet() -> str:
        return f"""
            QFrame#Header {{ background:{PRIMARY}; border-radius:8px; }}
            QLabel#HeaderTitle {{ color:white; font-size:17px; font-weight:bold; }}
            QLabel#HeaderSub {{ color:#d7efe9; font-size:11px; }}
            QGroupBox {{ font-size:12px; font-weight:bold; border:1px solid #cfd8dc;
                         border-radius:8px; margin-top:10px; }}
            QGroupBox::title {{ subcontrol-origin:margin; left:10px; padding:0 4px;
                                color:{PRIMARY}; }}
            QPushButton {{ background:#f2f5f4; border:1px solid #c4cfcc;
                           border-radius:5px; padding:4px 10px; }}
            QPushButton:hover {{ background:#e4eeec; }}
            QPushButton:checked {{ background:{ACCENT}; color:white; border-color:{ACCENT}; }}
            QPushButton#PrimaryButton {{ background:{ACCENT}; color:white;
                                         border:1px solid {ACCENT}; font-weight:bold; }}
            QPushButton#PrimaryButton:hover {{ background:#13907b; }}
            QTableWidget {{ border:1px solid #d5dddb; gridline-color:#e6ecea;
                            font-size:11px; }}
            QHeaderView::section {{ background:#eef4f2; color:{PRIMARY};
                                    border:none; border-right:1px solid #dde6e3;
                                    border-bottom:1px solid #dde6e3;
                                    font-weight:bold; padding:6px; }}
            QLabel#SourceNote {{ color:#555; font-size:11px; background:#f6f9f8;
                                 border:1px solid #e3eae7; border-radius:6px;
                                 padding:8px 10px; margin-top:6px; }}
            QLabel#TipLabel {{ color:#666; font-size:11px; }}
            QComboBox {{ padding:3px 6px; }}
        """

    def _valid_regions(self):
        return [r for r in self._dataset.regions if len(r.vertices) >= 3]

    # ---------------------------------------------------------------- 放大
    def _on_zoom_button(self):
        self._zoom_mode = self.btn_zoom.isChecked()
        if self._zoom_mode:
            self.tip_label.setText("放大模式：请单击要放大的子图（再次点按钮可取消）。")
            self.canvas.setCursor(Qt.PointingHandCursor)
        else:
            self.tip_label.setText("双击任一子图可放大查看；保存图片默认 JPEG。")
            self.canvas.unsetCursor()

    def _on_canvas_click(self, event):
        if event.inaxes is None:
            return
        want_open = event.dblclick or self._zoom_mode
        if not want_open:
            return
        data = self._cell_by_ax.get(event.inaxes)
        if data is None:
            return
        if self._zoom_mode:
            self._zoom_mode = False
            self.btn_zoom.setChecked(False)
            self.tip_label.setText("双击任一子图可放大查看；保存图片默认 JPEG。")
            self.canvas.unsetCursor()
        dlg = EnlargedCellDialog(data, parent=self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.exec()

    # ---------------------------------------------------------------- 渲染
    def render(self):
        """计算各算法对各地块的分解并绘图 + 刷新指标。"""
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.btn_rebuild.setEnabled(False)
        try:
            self._render_impl()
            self._populate_metrics()
        finally:
            self.btn_rebuild.setEnabled(True)
            QApplication.restoreOverrideCursor()

    def _render_impl(self):
        self.figure.clear()
        self._cell_by_ax = {}
        self._cache = {}
        regions = self._valid_regions()
        n_rows = max(1, len(regions))
        n_cols = max(1, len(self._algo_names))
        # 初始 figsize（窗口显示后画布随窗口自适应缩放，一屏排下全部子图）
        self.figure.set_size_inches(max(4.2 * n_cols, 6.0),
                                    max(2.4 * n_rows, 4.0))
        gs = self.figure.add_gridspec(
            n_rows, n_cols,
            left=0.12, right=0.975, top=0.93, bottom=0.10,
            hspace=0.58, wspace=0.12)

        for ri, region in enumerate(regions):
            verts = ensure_ccw(clean_ring(region.vertices))
            reflex = reflex_indices(verts)
            row_first_ax = None
            for ci, algo in enumerate(self._algo_names):
                ax = self.figure.add_subplot(gs[ri, ci], sharey=row_first_ax)
                if ci == 0:
                    row_first_ax = ax
                if ri == 0:
                    ax.set_title(self._display(algo), fontsize=11,
                                 fontweight="bold")
                pieces = None
                t0 = time.perf_counter()
                try:
                    params = self._params_by_algo.get(algo)
                    pieces, info = decompose_region_with(algo, verts, params)
                    runtime = time.perf_counter() - t0
                    self._draw_cell(ax, verts, pieces, reflex)
                    width_sum = sum(rotating_calipers_width(p) for p in pieces)
                    seg = info.get("segmentation", "")
                    seg_label = (f"{len(pieces)} 个凸子区，Σ宽度="
                                 f"{width_sum:.1f} m（{seg}）")
                    ax.set_xlabel(seg_label, fontsize=8.5)
                    self._cache[(ri, algo)] = {
                        "verts": verts, "pieces": pieces, "reflex": reflex,
                        "runtime": runtime, "seg_label": seg_label,
                    }
                    self._cell_by_ax[ax] = {
                        "region_name": region.name,
                        "algo_display": self._display(algo),
                        "verts": verts, "reflex": reflex, "pieces": pieces,
                        "seg_label": seg_label,
                    }
                except Exception as e:
                    ax.text(0.5, 0.5, f"分解失败：{type(e).__name__}: {e}",
                            ha="center", va="center", fontsize=9, color="red",
                            transform=ax.transAxes, wrap=True)
                if ci == 0:
                    # 地块名置于子图内左上角（每行独立，避免竖排跨行重叠）
                    ax.text(0.02, 0.97, region.name,
                            transform=ax.transAxes, fontsize=8.5,
                            fontweight="bold", ha="left", va="top", zorder=20,
                            bbox=dict(boxstyle="round,pad=0.18",
                                      facecolor="white", edgecolor="#cfd8dc",
                                      alpha=0.85))
                ax.set_aspect("equal", adjustable="datalim")
                # 恢复坐标刻度与网格（三列同地块需按坐标系对齐对比）；
                # 每轴仅 2-3 个主刻度，避免 UTM 大数标签密集重叠
                ax.grid(True, alpha=0.25)
                ax.tick_params(labelsize=7)
                ax.xaxis.set_major_locator(MaxNLocator(2))
                ax.yaxis.set_major_locator(MaxNLocator(3))
                # 隐藏与刻度重叠的大数偏移量文字（绝对坐标在放大窗口完整显示）
                ax.yaxis.offsetText.set_visible(False)

        # 画布随窗口自适应缩放（不固定尺寸），一屏内排下全部（地块×算法）子图
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.canvas.setMinimumSize(0, 0)
        self.canvas.draw_idle()

    # ---------------------------------------------------------------- 指标表
    def _scope_records(self) -> List[dict]:
        scope = self.scope_combo.currentData()
        if scope == -1 or scope is None:
            idxs = range(len(self._valid_regions()))
        else:
            idxs = [scope]
        out = []
        for ri in idxs:
            for algo in self._algo_names:
                rec = self._cache.get((ri, algo))
                if rec is not None:
                    out.append((ri, algo, rec))
        # 按算法分组返回：{algo: [records]}
        grouped: Dict[str, List[dict]] = {a: [] for a in self._algo_names}
        for ri, algo, rec in out:
            grouped[algo].append(rec)
        return grouped

    def _populate_metrics(self):
        grouped = self._scope_records()
        values_by_algo: Dict[str, Dict[str, float]] = {}
        for algo in self._algo_names:
            recs = grouped.get(algo) or []
            values_by_algo[algo] = compute_metrics(recs) if recs else {}

        # 表头
        headers = ["评价指标"] + [self._display(a) for a in self._algo_names]
        self.metric_table.setHorizontalHeaderLabels(headers)

        # 逐行填值并确定最优
        for row, (key, name, unit, direction, fmt) in enumerate(METRIC_DEFS):
            name_item = QTableWidgetItem(f"{name}（{unit}）" if unit else name)
            name_item.setToolTip("↓ 越小越好" if direction == "down"
                                 else "↑ 越大越好")
            name_item.setBackground(Qt.white)
            self.metric_table.setItem(row, 0, name_item)

            vals = {}
            for ci, algo in enumerate(self._algo_names):
                v = values_by_algo[algo].get(key)
                vals[ci] = v
            present = [v for v in vals.values() if v is not None]
            best = (min(present) if direction == "down" else max(present)) \
                if present else None

            for ci, algo in enumerate(self._algo_names):
                v = vals[ci]
                if v is None:
                    item = QTableWidgetItem("—")
                else:
                    item = QTableWidgetItem(fmt.format(v))
                    if best is not None and abs(v - best) <= 1e-9:
                        item.setBackground(_best_brush())
                        f = item.font(); f.setBold(True); item.setFont(f)
                    else:
                        item.setBackground(Qt.white)
                item.setTextAlignment(Qt.AlignCenter)
                self.metric_table.setItem(row, ci + 1, item)

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出评价指标 CSV", "分割方式评价指标.csv", "CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        grouped = self._scope_records()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["指标", "单位", "方向"] +
                       [self._display(a) for a in self._algo_names])
            for key, name, unit, direction, fmt in METRIC_DEFS:
                row = [name, unit, "越小越好" if direction == "down"
                       else "越大越好"]
                for algo in self._algo_names:
                    recs = grouped.get(algo) or []
                    if recs:
                        v = compute_metrics(recs).get(key)
                        row.append(fmt.format(v) if v is not None else "")
                    else:
                        row.append("")
                w.writerow(row)
        self.tip_label.setText(f"指标已导出：{path}")

    # ----------------------------------------------------------------
    def _display(self, algo_name: str) -> str:
        if self._registry is not None:
            m = self._registry.meta(algo_name)
            return m.get("display_name") or algo_name
        return algo_name

    @staticmethod
    def _draw_cell(ax, verts, pieces, reflex_idx):
        for i, p in enumerate(pieces):
            ax.add_patch(MplPolygon(p, closed=True,
                                    facecolor=_FILL[i % len(_FILL)],
                                    edgecolor="#1f6f43", linewidth=1.1,
                                    alpha=0.85, zorder=2))
        arr = np.asarray(verts + [verts[0]], dtype=float)
        ax.plot(arr[:, 0], arr[:, 1], "-", color="black", linewidth=1.8,
                zorder=4)
        if reflex_idx:
            rx = [verts[i][0] for i in reflex_idx]
            ry = [verts[i][1] for i in reflex_idx]
            ax.scatter(rx, ry, s=26, marker="o", facecolor="red",
                       edgecolor="black", linewidths=0.6, zorder=5,
                       label=f"凹点({len(reflex_idx)})")
            ax.legend(loc="upper right", fontsize=7)
        ax.autoscale_view()
        ax.margins(0.08)


def _best_brush():
    """最优单元格背景（浅绿）。"""
    from PySide6.QtGui import QColor, QBrush
    return QBrush(QColor("#d8f1e3"))
