"""Choose separate or overlaid JPEG exports without altering solver results."""
from pathlib import Path
import hashlib
import re
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)
from config.default_params import PICTURE_DIR


def combination_name(label, run):
    combo = run.get('combination') or (run.get('metadata') or {}).get('combination') or {}
    return f"{combo['decomposition']} + {combo['planning']}" if combo else re.sub(r'\s*\[[^]]*\].*$', '', label).replace('×', '+')


def route_filename(runs):
    names = [combination_name(label, run) for label, run in runs.items()]
    stem = names[0] if len(names) == 1 else '｜'.join(f'{i}{name}' for i, name in enumerate(names, 1))
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', stem).strip().rstrip('.')
    if len(stem) > 170:
        stem = stem[:150] + '_' + hashlib.sha256(stem.encode()).hexdigest()[:12]
    return stem + '.jpg'


def export_route_images(directory, dataset, runs, overlay=False):
    from core.experiment_bundle import _plot_runs
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    outputs = []
    batches = [runs] if overlay else [{label: run} for label, run in runs.items()]
    for batch in batches:
        path = directory / route_filename(batch)
        number = 2
        while path.exists():
            path = directory / (Path(route_filename(batch)).stem + f' ({number}).jpg')
            number += 1
        _plot_runs(path, dataset, batch)
        outputs.append(path)
    return outputs


def export_convergence_images(directory, runs_by_algo, overlay=False):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from compare.convergence import draw_convergence
    from core.image_export import save_jpeg
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    outputs = []
    batches = [runs_by_algo] if overlay else [{label: runs} for label, runs in runs_by_algo.items()]
    for batch in batches:
        name = '收敛曲线_' + route_filename({label: runs[0] for label, runs in batch.items()})
        path = directory / name
        number = 2
        while path.exists():
            path = directory / (Path(name).stem + f' ({number}).jpg')
            number += 1
        figure = Figure(figsize=(10, max(6, 3 * len({
            (run.get('metadata') or {}).get('gtsp', {}).get('objective', 'mission_total_distance')
            for runs in batch.values() for run in runs}))))
        FigureCanvasAgg(figure)
        try:
            draw_convergence(figure, batch)
            save_jpeg(figure, path)
        finally:
            figure.clear()
        outputs.append(path)
    return outputs


class RouteExportDialog(QDialog):
    def __init__(self, labels, selected=None, parent=None, convergence=False):
        super().__init__(parent)
        self.setWindowTitle('勾选组合 · 导出高清 JPEG ' + ('收敛曲线' if convergence else '路线图'))
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        hint = QLabel('每个组合汇总全部有效种子的曲线，显示均值与标准差带；不同优化目标分图，DP显示结果点。'
                      if convergence else '每个组合使用航程最短的有效种子。分别导出生成单组合图片；叠加导出把勾选组合绘在一张图中。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.listing = QListWidget()
        for label in labels:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if selected is None or selected == label else Qt.Unchecked)
            self.listing.addItem(item)
        layout.addWidget(self.listing, 1)
        all_check = QCheckBox('全选 / 取消全选')
        all_check.toggled.connect(lambda on: [self.listing.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)
                                              for i in range(self.listing.count())])
        layout.addWidget(all_check)
        self.mode = QComboBox()
        self.mode.addItem('勾选组合分别导出', 'separate')
        self.mode.addItem('勾选组合叠加为一张图', 'overlay')
        self.mode.addItem('一键导出全部单一组合', 'all')
        layout.addWidget(self.mode)
        row = QHBoxLayout()
        self.directory = QLineEdit(PICTURE_DIR)
        row.addWidget(self.directory, 1)
        browse = QPushButton('选择目录')
        def choose():
            directory = QFileDialog.getExistingDirectory(self, '导出目录', self.directory.text())
            if directory:
                self.directory.setText(directory)
        browse.clicked.connect(choose)
        row.addWidget(browse)
        layout.addLayout(row)
        note = QLabel('文件名：分割方法 + 规划算法；叠加图按 1…｜2… 编号。Windows 不允许文件名使用半角 |，这里采用全角 ｜。')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('导出 JPEG')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_labels(self):
        return [self.listing.item(i).data(Qt.UserRole) for i in range(self.listing.count())
                if self.mode.currentData() == 'all' or self.listing.item(i).checkState() == Qt.Checked]
