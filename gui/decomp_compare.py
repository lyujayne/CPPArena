"""Paged decomposition comparison with checked geometry and explicit metric scope."""
import csv
import math
import time
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.ticker import MaxNLocator
from shapely.geometry import Polygon
from shapely.ops import unary_union
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea, QSpinBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)
from algorithms.aco.polygon_decomp import clean_ring, ensure_ccw, reflex_indices
from algorithms.aco.pso_decomp import rotating_calipers_width
from algorithms.common import decompose_region_with
from core.path_annotations import draw_partitions
from gui.export_toolbar import JpegNavigationToolbar

METRIC_DEFS = [
    ('n_cells', '凸子区数量', '个', 'down', '{:.0f}'),
    ('width_sum', '最小宽度之和 Σw', 'm', 'down', '{:.2f}'),
    ('cut_length', '切割线总长度（描述）', 'm', None, '{:.2f}'),
    ('n_steiner', '新增顶点数（描述）', '个', None, '{:.0f}'),
    ('area_cv', '子区面积 CV（描述）', '%', None, '{:.1f}'),
    ('regularity', '宽径比均值 w/D（描述）', '', None, '{:.3f}'),
    ('coverage', '分割覆盖率', '%', 'up', '{:.4f}'),
    ('runtime', '分割耗时', 's', 'down', '{:.6f}'),
]
METRIC_SOURCES = (
    '评价前提：覆盖原区域、无越界、无重叠、子区凸。无效或不完整结果不参与高亮。\n'
    'Σw=各凸片最小宽度之和，反映相同航线间距下的换行负担（Li等，2011）；不保证完整任务航程最短。\n'
    '凸子区数、Σw与耗时仅在相同输入及参数预算下参考较小值；覆盖率=子区并集∩原区域面积/原区域面积，应接近100%。\n'
    '切割长度按内部线段并集计一次；新增顶点是不在原顶点集合中的唯一顶点。二者不直接代表飞行成本。\n'
    '面积CV=总体标准差/均值×100%，只描述面积分布；单机任务不据此排名。\n'
    'w/D=最小宽度/最大顶点距离，是描述量，不是标准紧凑度或“越大越好”的保证。'
)

def _cut_info(verts, pieces):
    """Count a shared edge once even when the opposite side subdivides it."""
    cut = unary_union([Polygon(p).boundary for p in pieces]).difference(Polygon(verts).boundary)
    original = {(round(x, 6), round(y, 6)) for x, y in verts}
    added = {(round(x, 6), round(y, 6)) for p in pieces for x, y in p} - original
    return cut.length, len(added)

def compute_metrics(records):
    if not records:
        return {}
    pieces, cut_length, added, covered, area, runtime = [], 0., 0, 0., 0., 0.
    valid = True
    for rec in records:
        original = Polygon(rec['verts'])
        polygons = [Polygon(p) for p in rec['pieces']]
        if not original.is_valid or original.area <= 0 or not polygons or any(not p.is_valid or p.area <= 0 for p in polygons):
            return {'valid': False}
        union = unary_union(polygons)
        tol = max(1e-6, original.area*1e-9)
        valid &= (union.symmetric_difference(original).area <= tol and
                  sum(p.area for p in polygons)-union.area <= tol and
                  all(p.convex_hull.area-p.area <= tol for p in polygons))
        pieces.extend(rec['pieces'])
        length, count = _cut_info(rec['verts'], rec['pieces'])
        cut_length += length
        added += count
        covered += union.intersection(original).area
        area += original.area
        runtime += rec.get('runtime', 0.)
    widths = [rotating_calipers_width(p) for p in pieces]
    areas = np.array([Polygon(p).area for p in pieces])
    diameters = [max(math.dist(a, b) for a in p for b in p) for p in pieces]
    return dict(valid=bool(valid), n_cells=len(pieces), width_sum=sum(widths), cut_length=cut_length,
        n_steiner=added, area_cv=float(areas.std(ddof=0)/areas.mean()*100),
        regularity=float(np.mean([w/d for w, d in zip(widths, diameters) if d > 0])),
        coverage=covered/area*100, runtime=runtime)

class EnlargedCellDialog(QDialog):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(data['region_name'] + ' · ' + data['algo_display'])
        self.resize(1000, 800)
        layout = QVBoxLayout(self)
        figure = Figure(figsize=(10, 8), dpi=100)
        canvas = FigureCanvasQTAgg(figure)
        layout.addWidget(JpegNavigationToolbar(canvas, self))
        layout.addWidget(canvas, 1)
        ax = figure.subplots()
        DecompCompareDialog._draw_cell(ax, data['verts'], data['pieces'], data['reflex'])
        ax.set_title(self.windowTitle())
        ax.set_xlabel(data['seg_label'])
        figure.tight_layout()

class DecompCompareDialog(QDialog):
    def __init__(self, dataset, algo_names, registry=None, params_by_algo=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('分解对比 · 图形与评价指标')
        self.resize(1400, 940)
        self._dataset, self._algo_names = dataset, list(algo_names)
        self._registry, self._params_by_algo = registry, params_by_algo or {}
        self._cache, self._cell_by_ax = {}, {}
        self._zoom_mode = False
        self._build_ui()
        self.render()

    def _valid_regions(self):
        return [r for r in self._dataset.regions if len(r.vertices) >= 3]

    def _display(self, key):
        from core.combinations import DECOMPOSITIONS
        return DECOMPOSITIONS[key][0] if key in DECOMPOSITIONS else key

    def _build_ui(self):
        layout = QVBoxLayout(self)
        title = QLabel('分解对比：逐页查看地块；双击子图放大。分割评价和完整路线评价分别解释。')
        title.setStyleSheet('font-size:15px;font-weight:600;padding:10px;color:#126b72;')
        layout.addWidget(title)
        parameters = QLabel('本窗口独立评估分割参数（鼠标悬停查看）；完整实验路线的指标请在“比较分析”查看。')
        parameters.setToolTip(str(self._params_by_algo) if self._params_by_algo else '使用各分割模块默认参数，默认 seed=42')
        layout.addWidget(parameters)
        row = QHBoxLayout()
        row.addWidget(QLabel('显示地块'))
        self.region_filter = QComboBox()
        self.region_filter.addItem('全部地块（每页3个）', -1)
        for i, region in enumerate(self._valid_regions()):
            self.region_filter.addItem(region.name, i)
        row.addWidget(self.region_filter, 1)
        row.addWidget(QLabel('页码'))
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, max(1, (len(self._valid_regions())+2)//3))
        row.addWidget(self.page_spin)
        layout.addLayout(row)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        host = QWidget()
        plots = QVBoxLayout(host)
        self.figure = Figure(dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = JpegNavigationToolbar(self.canvas, self)
        plots.addWidget(self.toolbar)
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setWidgetResizable(True)
        plots.addWidget(scroll, 1)
        self.tabs.addTab(host, '分解图形')
        self.tabs.addTab(self._build_metrics_panel(), '评价指标与定义')
        self.region_filter.currentIndexChanged.connect(self._refresh_page)
        self.page_spin.valueChanged.connect(self._refresh_page)
        self.canvas.mpl_connect('button_press_event', self._on_canvas_click)
        row = QHBoxLayout()
        self.tip_label = QLabel('结果缓存复用；切换地块和页码不会重新运行分割。')
        row.addWidget(self.tip_label, 1)
        self.btn_metrics = QPushButton('评价指标')
        self.btn_metrics.clicked.connect(self._show_metrics)
        self.btn_zoom = QPushButton('放大子图')
        self.btn_zoom.setCheckable(True)
        self.btn_zoom.toggled.connect(self._on_zoom_button)
        self.btn_rebuild = QPushButton('重新计算')
        self.btn_rebuild.clicked.connect(self.render)
        close = QPushButton('关闭')
        close.clicked.connect(self.accept)
        for button in (self.btn_metrics, self.btn_zoom, self.btn_rebuild, close):
            row.addWidget(button)
        layout.addLayout(row)

    def _build_metrics_panel(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        row = QHBoxLayout()
        row.addWidget(QLabel('统计范围'))
        self.scope_combo = QComboBox()
        self.scope_combo.addItem('全部地块（完整汇总）', -1)
        for i, region in enumerate(self._valid_regions()):
            self.scope_combo.addItem(region.name, i)
        self.scope_combo.currentIndexChanged.connect(self._populate_metrics)
        row.addWidget(self.scope_combo, 1)
        self.btn_export = QPushButton('导出指标 CSV')
        self.btn_export.clicked.connect(self._export_csv)
        row.addWidget(self.btn_export)
        layout.addLayout(row)
        self.metric_table = QTableWidget(len(METRIC_DEFS), len(self._algo_names)+1)
        self.metric_table.verticalHeader().hide()
        self.metric_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.metric_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.metric_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.metric_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.metric_table.horizontalHeader().setMinimumSectionSize(220)
        self.metric_table.horizontalHeader().setDefaultSectionSize(270)
        self.metric_table.verticalHeader().setDefaultSectionSize(44)
        self.metric_table.setAlternatingRowColors(True)
        layout.addWidget(self.metric_table, 1)
        note = QLabel(METRIC_SOURCES)
        note.setWordWrap(True)
        note.setStyleSheet('padding:12px;background:#f0f7f7;color:#334155;')
        layout.addWidget(note)
        return host

    def render(self):
        self.btn_rebuild.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._cache = {}
            for ri, region in enumerate(self._valid_regions()):
                verts = ensure_ccw(clean_ring(region.vertices))
                for algo in self._algo_names:
                    start = time.perf_counter()
                    try:
                        pieces, info = decompose_region_with(algo, verts, self._params_by_algo.get(algo))
                        elapsed = time.perf_counter()-start
                        self._cache[ri, algo] = dict(verts=verts, pieces=pieces, runtime=elapsed,
                            reflex=reflex_indices(verts), seg_label=f'{len(pieces)} 个凸子区，Σw={sum(rotating_calipers_width(p) for p in pieces):.1f} m')
                    except Exception as exc:
                        self._cache[ri, algo] = {'error': str(exc)}
            self._refresh_page()
            self._populate_metrics()
        finally:
            self.btn_rebuild.setEnabled(True)
            QApplication.restoreOverrideCursor()

    def _refresh_page(self):
        self.page_spin.setEnabled(self.region_filter.currentData() == -1)
        self._render_impl()

    def _render_impl(self):
        self.figure.clear()
        self._cell_by_ax = {}
        indexed = list(enumerate(self._valid_regions()))
        selected = self.region_filter.currentData()
        indexed = [indexed[selected]] if selected is not None and selected >= 0 else indexed[(self.page_spin.value()-1)*3:self.page_spin.value()*3]
        rows, cols = max(1, len(indexed)), max(1, len(self._algo_names))
        width, height = max(1100, cols*420), max(400, rows*330)
        self.figure.set_size_inches(width/self.figure.dpi, height/self.figure.dpi)
        self.canvas.setMinimumSize(width, height)
        self.canvas.resize(width, height)
        for row, (ri, region) in enumerate(indexed):
            for col, algo in enumerate(self._algo_names):
                ax = self.figure.add_subplot(rows, cols, row*cols+col+1)
                rec = self._cache.get((ri, algo), {})
                ax.set_title(region.name + '\n' + self._display(algo), fontsize=10)
                if rec.get('pieces'):
                    self._draw_cell(ax, rec['verts'], rec['pieces'], rec['reflex'])
                    ax.set_xlabel(rec['seg_label'], fontsize=9)
                    self._cell_by_ax[ax] = dict(rec, region_name=region.name, algo_display=self._display(algo))
                else:
                    ax.text(.5, .5, '分解失败：' + rec.get('error', '结果缺失'), color='#b91c1c',
                            wrap=True, ha='center', va='center', transform=ax.transAxes)
        self.figure.tight_layout(pad=2.2)
        self.canvas.draw_idle()

    def _scope_records(self):
        indices = list(range(len(self._valid_regions()))) if self.scope_combo.currentData() == -1 else [self.scope_combo.currentData()]
        return {algo: [self._cache[ri, algo] for ri in indices if (ri, algo) in self._cache and not self._cache[ri, algo].get('error')]
                for algo in self._algo_names}

    def _scoped_metrics(self):
        expected = len(self._valid_regions()) if self.scope_combo.currentData() == -1 else 1
        return {algo: compute_metrics(recs) if len(recs) == expected and recs else {}
                for algo, recs in self._scope_records().items()}

    def _populate_metrics(self):
        values = self._scoped_metrics()
        self.metric_table.setHorizontalHeaderLabels(['评价指标'] + [self._display(a) for a in self._algo_names])
        for row, (key, name, unit, direction, fmt) in enumerate(METRIC_DEFS):
            title = QTableWidgetItem(f'{name} ({unit})' if unit else name)
            title.setToolTip('描述性指标，不作优劣排名' if direction is None else '只在几何有效、相同输入与预算下参考')
            self.metric_table.setItem(row, 0, title)
            candidates = [m[key] for m in values.values() if m.get('valid') and key in m]
            best = (min(candidates) if direction == 'down' else max(candidates)) if candidates and direction else None
            for col, algo in enumerate(self._algo_names, 1):
                metrics = values[algo]
                text = '结果缺失' if not metrics else '无效分割' if not metrics.get('valid') else fmt.format(metrics[key])
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                if metrics.get('valid') and best is not None and abs(metrics[key]-best) < 1e-9:
                    item.setBackground(QColor('#d8f1e3'))
                elif metrics and not metrics.get('valid'):
                    item.setForeground(QColor('#b91c1c'))
                self.metric_table.setItem(row, col, item)

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出分割指标', '分割指标.csv', 'CSV (*.csv)')
        if not path:
            return
        values = self._scoped_metrics()
        with open(path, 'w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.writer(stream)
            writer.writerow(['指标', '单位', '适用方向'] + self._algo_names)
            for key, label, unit, direction, fmt in METRIC_DEFS:
                writer.writerow([label, unit, direction or '仅描述'] +
                    [fmt.format(values[a][key]) if values[a].get('valid') else '无效或缺失结果' for a in self._algo_names])

    def _show_metrics(self):
        self.tabs.setCurrentIndex(1)

    def _on_zoom_button(self, checked):
        self._zoom_mode = checked
        self.canvas.setCursor(Qt.PointingHandCursor if checked else Qt.ArrowCursor)

    def _on_canvas_click(self, event):
        if event.inaxes not in self._cell_by_ax or not (event.dblclick or self._zoom_mode):
            return
        self.btn_zoom.setChecked(False)
        EnlargedCellDialog(self._cell_by_ax[event.inaxes], self).exec()

    @staticmethod
    def _draw_cell(ax, verts, pieces, reflex_idx):
        colors = ['#d1fae5', '#dbeafe', '#fef3c7', '#ede9fe', '#fee2e2']
        for i, piece in enumerate(pieces):
            ax.add_patch(MplPolygon(piece, facecolor=colors[i % len(colors)], edgecolor='none', zorder=2))
        draw_partitions(ax, pieces)
        if reflex_idx:
            ax.scatter([verts[i][0] for i in reflex_idx], [verts[i][1] for i in reflex_idx],
                       color='#dc2626', s=20, zorder=10)
        ax.set_aspect('equal', adjustable='box')
        ax.autoscale_view()
        ax.margins(.08)
        ax.grid(alpha=.2)
        ax.tick_params(labelsize=8)
        ax.xaxis.set_major_locator(MaxNLocator(3))
        ax.yaxis.set_major_locator(MaxNLocator(4))
