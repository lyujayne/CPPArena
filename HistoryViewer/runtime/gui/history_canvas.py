"""Batch full route geometry for large offline overlays."""
from matplotlib.collections import LineCollection
from matplotlib.image import imread
from matplotlib.patches import Polygon
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QListWidget, QListWidgetItem, QMenu, QToolButton,
                               QWidgetAction)

from core.path_annotations import draw_partitions, subregion_endpoints
from gui.path_canvas import PathCanvas, ALGO_COLORS


class HistoryCanvas(PathCanvas):
    def __init__(self):
        self.overlay_details = False
        self._background_key = None
        self._background = None
        super().__init__()
        self.layout().removeWidget(self._toggle_scroll)
        self._toggle_scroll.deleteLater()
        self.combination_button = QToolButton()
        self.combination_button.setPopupMode(QToolButton.InstantPopup)
        self.combination_button.setToolTip('展开后勾选要显示的路径规划组合，可上下滚动并同时选择多个组合。')
        self.combination_menu = QMenu(self.combination_button)
        self.combination_list = QListWidget()
        self.combination_list.setWordWrap(True)
        self.combination_list.setTextElideMode(Qt.ElideNone)
        self.combination_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        action = QWidgetAction(self.combination_menu)
        action.setDefaultWidget(self.combination_list)
        self.combination_menu.addAction(action)
        self.combination_button.setMenu(self.combination_menu)
        self.combination_list.itemChanged.connect(self._combination_changed)
        self.layout().insertWidget(2, self.combination_button)
        self.combination_button.hide()

    def set_results(self, results):
        self._hidden_algos.update(set(results or {}) - self._results.keys())
        super().set_results(results)

    def _rebuild_algo_toggles(self):
        self._hidden_algos.intersection_update(self._results)
        self.combination_list.blockSignals(True)
        self.combination_list.clear()
        for index, name in enumerate(self._results):
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if name in self._hidden_algos else Qt.Checked)
            item.setForeground(QColor(ALGO_COLORS[index % len(ALGO_COLORS)]))
            item.setToolTip(name)
            self.combination_list.addItem(item)
        self.combination_list.blockSignals(False)
        width = max((self.combination_list.fontMetrics().horizontalAdvance(name)
                     for name in self._results), default=260) + 64
        self.combination_list.setFixedSize(min(640, max(300, width)),
                                          min(320, max(48, len(self._results) * 28 + 8)))
        self.combination_button.setVisible(bool(self._results))
        self.combination_button.setText(
            f'显示路径规划组合（已选 {len(self._results) - len(self._hidden_algos)} / {len(self._results)}）')

    def _combination_changed(self, item):
        self._toggle_algo_path(item.data(Qt.UserRole), item.checkState() == Qt.Checked)
        self.combination_button.setText(
            f'显示路径规划组合（已选 {len(self._results) - len(self._hidden_algos)} / {len(self._results)}）')

    def set_dataset(self, dataset, decomposed=False, *, redraw=True):
        self._dataset = dataset
        self._decomposed = decomposed
        self._decomp_cache.clear()
        self._reset_view = True
        if redraw:
            self.redraw()

    def redraw(self):
        visible = [(name, run) for name, run in self._results.items()
                   if name not in self._hidden_algos]
        if len(visible) <= 8 or self.overlay_details or self._dataset is None:
            return super().redraw()
        limits = self.ax.get_xlim(), self.ax.get_ylim()
        self.ax.clear()
        self._temp_artist = None
        ds = self._dataset
        if self._layers['image'] and ds.bg_image_path and ds.bg_bounds_utm:
            from pathlib import Path
            path = Path(ds.bg_image_path)
            stat = path.stat()
            key = str(path), stat.st_mtime_ns, stat.st_size
            if key != self._background_key:
                self._background = imread(path)
                self._background_key = key
            x0, y0, x1, y1 = ds.bg_bounds_utm
            self.ax.imshow(self._background, extent=(x0, x1, y0, y1), zorder=0, alpha=.9)
        for region in ds.regions:
            if self._layers['regions']:
                patch = Polygon(region.vertices, fill=False, edgecolor='#333333', lw=1.6, zorder=2)
                patch.set_picker(6)
                self.ax.add_patch(patch)
                center = np.asarray(region.vertices).mean(axis=0)
                self.ax.text(*center, region.name, ha='center', fontsize=9, zorder=5)
        if self._layers['launch'] and ds.launch_point:
            self.ax.plot(*ds.launch_point, '^', color='#e6194b', markersize=11, zorder=6)
        colors = {name: ALGO_COLORS[index % len(ALGO_COLORS)]
                  for index, name in enumerate(self._results)}
        for name, run in visible:
            color = colors[name]
            if self._decomposed and self._layers['subregions']:
                draw_partitions(self.ax, [item['polygon'] for item in run.get('subregion_sequence', [])], color)
            if not self._layers['route']:
                continue
            paths = run.get('internal_paths') or []
            points = run.get('waypoints') or []
            internal = [path for path in paths if len(path) >= 2]
            if not paths and len(points) >= 2:
                internal = [points]
            directions = []
            if self._layers['internal'] and internal:
                lines = LineCollection(internal, colors=color, linewidths=1.15, zorder=8, label=name)
                lines.set_gid('history-internal-routes')
                self.ax.add_collection(lines)
                directions.extend((a, b) for path in internal for a, b in zip(path, path[1:]))
            if self._layers['transitions'] and paths and points:
                position = points[0]
                transfers = []
                for path in paths:
                    if path:
                        transfers.append((position, path[0]))
                        position = path[-1]
                transfers.append((position, points[-1]))
                lines = LineCollection(transfers, colors=color, linewidths=1.3, linestyles='--', zorder=8)
                lines.set_gid('history-transfer-routes')
                self.ax.add_collection(lines)
                directions.extend(transfers)
            directions = [(a, b) for a, b in directions if tuple(a) != tuple(b)]
            if directions:
                stride = max(1, (len(directions) + 39) // 40)
                segments = np.asarray(directions[::stride])
                delta = segments[:, 1] - segments[:, 0]
                start = segments[:, 0] + .36 * delta
                arrows = self.ax.quiver(start[:, 0], start[:, 1], .28 * delta[:, 0], .28 * delta[:, 1],
                                       angles='xy', scale_units='xy', scale=1, color=color,
                                       width=.002, zorder=10)
                arrows.set_gid('route-direction')
            if self._layers['endpoints']:
                endpoints = list(subregion_endpoints(run))
                for key, color, marker in (('entry', '#087f5b', 'o'), ('exit', '#c2410c', 's')):
                    if endpoints:
                        self.ax.scatter([item[key][0] for item in endpoints],
                                        [item[key][1] for item in endpoints], c=color, marker=marker,
                                        s=26, edgecolors='white', linewidths=.5, zorder=11)
        self.ax.set_aspect('equal', adjustable='datalim')
        if self._reset_view:
            self.ax.autoscale_view()
            self.ax.margins(.06)
            self._reset_view = False
        else:
            self.ax.set_xlim(limits[0])
            self.ax.set_ylim(limits[1])
        self.ax.set(xlabel='东向 (m)', ylabel='北向 (m)', title=f'{ds.name} —— {len(visible)}个组合完整轨迹叠加')
        self.ax.grid(alpha=.3)
        self.canvas.draw_idle()
