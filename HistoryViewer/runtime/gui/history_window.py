"""Standalone history library, sharing the live result widgets without solving."""
import json
import tempfile
import re
from html import escape
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)
from config.default_params import APP_VERSION, HISTORY_EXPERIMENT_DIR as EXPERIMENT_DIR
from core.experiment_bundle import load_experiment_directory, import_experiment
from data.dataset import Dataset
from gui.path_canvas import PathCanvas
from gui.compare_panel import ComparePanel
from gui.result_panel import ResultPanel


class HistoryWindow(QMainWindow):
    def __init__(self, library_dir=None):
        super().__init__()
        self.setWindowTitle(f'CPP Arena v{APP_VERSION} · 历史实验平台（离线）')
        self.resize(1480, 900)
        self._record = None
        self._datasets = []
        self.library_scan_errors = []
        self.library_directory = Path(library_dir or EXPERIMENT_DIR).resolve()
        self.library_directory.mkdir(parents=True, exist_ok=True)
        self._assets = tempfile.TemporaryDirectory(prefix='cpp_history_')
        splitter = QSplitter(Qt.Horizontal)
        library = QWidget()
        left = QVBoxLayout(library)
        left.addWidget(QLabel('历史实验库'))
        row = QHBoxLayout()
        open_button = QPushButton('导入旧实验包')
        open_button.clicked.connect(self.open_dialog)
        directory_button = QPushButton('导入实验文件夹')
        directory_button.clicked.connect(self.scan_dialog)
        row.addWidget(open_button); row.addWidget(directory_button)
        left.addLayout(row)
        row = QHBoxLayout()
        refresh = QPushButton('刷新实验库')
        refresh.clicked.connect(self.refresh_library)
        reveal = QPushButton('打开默认实验库')
        reveal.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.library_directory))))
        row.addWidget(refresh)
        row.addWidget(reveal)
        left.addLayout(row)
        self.library = QListWidget()
        self.library.itemClicked.connect(self._open_item)
        left.addWidget(self.library, 1)
        self.info = QLabel('支持完整实验文件夹，兼容 .cppx / .zip / .json；导入后永久保存到默认实验库。')
        self.info.setWordWrap(True)
        left.addWidget(self.info)
        self.ds_combo = QComboBox()
        self.ds_combo.currentIndexChanged.connect(self._dataset_changed)
        self.run_combo = QComboBox()
        self.run_combo.currentIndexChanged.connect(self._run_changed)
        left.addWidget(QLabel('数据集')); left.addWidget(self.ds_combo)
        left.addWidget(QLabel('组合与种子')); left.addWidget(self.run_combo)
        left.addWidget(QLabel('可打开多个实验包，在库中切换对比；所有视图均基于保存数据。'))
        library.setMinimumWidth(260); library.setMaximumWidth(360)
        self.canvas = PathCanvas()
        self.canvas.offline = True
        for key, text in (('image', '显示背景图'), ('route', '显示路径'), ('suborder', '访问顺序'), ('endpoints', '显示入口 / 出口')):
            check = QCheckBox(text)
            check.setChecked(True)
            check.toggled.connect(lambda on, k=key: self.canvas.set_layer(k, on))
            self.canvas.add_toolbar_extra(check)
            setattr(self, key + '_check', check)
        self.decomp_check = QCheckBox('显示保存的分割结果')
        self.decomp_check.setChecked(True)
        self.decomp_check.toggled.connect(self.canvas.set_decomposed)
        self.canvas.add_toolbar_extra(self.decomp_check)
        tabs = QTabWidget()
        self.detail = ResultPanel()
        self.comparison = ComparePanel()
        self.comparison_window = QMainWindow(self, Qt.Window)
        self.comparison_window.setWindowTitle(f'历史实验 · 比较分析 · v{APP_VERSION}')
        self.comparison_window.resize(1320, 880)
        self.comparison_window.setCentralWidget(self.comparison)
        self.logs = QTextBrowser()
        tabs.addTab(self.detail, '运行指标与日志')
        tabs.addTab(self.logs, '实验日志与信息')
        tabs.setMinimumWidth(360)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        compare_button = QPushButton('比较分析')
        compare_button.setObjectName('PrimaryButton')
        compare_button.clicked.connect(self._open_comparison)
        right_layout.addWidget(compare_button)
        right_layout.addWidget(tabs, 1)
        splitter.addWidget(library); splitter.addWidget(self.canvas); splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 760, 440])
        self.setCentralWidget(splitter)
        self.refresh_library()
        self.library_timer = QTimer(self)
        self.library_timer.setInterval(2000)
        self.library_timer.timeout.connect(self.refresh_library)
        self.library_timer.start()

    def _add_path(self, path):
        path = str(Path(path).resolve())
        for i in range(self.library.count()):
            if self.library.item(i).data(Qt.UserRole) == path:
                return self.library.item(i)
        item = QListWidgetItem(Path(path).name)
        item.setData(Qt.UserRole, path)
        item.setToolTip(path)
        self.library.addItem(item)
        return item

    def _open_comparison(self):
        if self._record is None:
            QMessageBox.information(self, '比较分析', '请先打开历史实验。')
            return
        self.comparison_window.show()
        self.comparison_window.raise_()
        self.comparison_window.activateWindow()

    def scan_directory(self, directory):
        directory = Path(directory)
        errors = []
        known = {self.library.item(i).data(Qt.UserRole) for i in range(self.library.count())}
        try:
            paths = sorted(directory.iterdir(), reverse=True)
        except OSError as exc:
            paths = []
            errors.append(f'{directory}：{exc}')
        for path in paths:
            if path.name.startswith('.'):
                continue
            if str(path.resolve()) in known:
                continue
            try:
                if path.is_dir() and (path / 'experiment.json').is_file():
                    candidate = json.loads((path / 'experiment.json').read_text(encoding='utf-8'))
                    if isinstance(candidate, dict) and candidate.get('schema') == 'cpp-arena-experiment':
                        self._add_path(path)
                elif path.suffix.lower() in ('.cppx', '.zip'):
                    self._add_path(path)
                elif path.suffix.lower() == '.json':
                    candidate = json.loads(path.read_text(encoding='utf-8'))
                    if isinstance(candidate, dict) and candidate.get('schema') == 'cpp-arena-experiment':
                        self._add_path(path)
            except (OSError, ValueError) as exc:
                errors.append(f'{path.name}：{exc}')
        if errors:
            self.statusBar().setStyleSheet('color:#b91c1c;')
            self.statusBar().showMessage(f'实验库有{len(errors)}条记录无法读取：' + errors[0])
        elif self.library_scan_errors:
            self.statusBar().setStyleSheet('')
            self.statusBar().clearMessage()
        self.library_scan_errors = errors

    def scan_dialog(self):
        directory = QFileDialog.getExistingDirectory(self, '选择包含 experiment.json 的实验文件夹', str(self.library_directory))
        if directory:
            self.open_path(directory)

    def refresh_library(self):
        for i in range(self.library.count()-1, -1, -1):
            if not Path(self.library.item(i).data(Qt.UserRole)).exists():
                self.library.takeItem(i)
        self.scan_directory(self.library_directory)

    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '导入旧实验包到默认实验库', str(self.library_directory),
            'CPP Arena 实验 (*.cppx *.zip *.json)')
        for path in paths:
            self.open_path(path)

    def _open_item(self, item):
        self.open_path(item.data(Qt.UserRole))

    def open_path(self, path):
        try:
            stored = import_experiment(path, self.library_directory)
            record = load_experiment_directory(stored)
            self.library.setCurrentItem(self._add_path(stored))
            self.set_record(record)
            self.statusBar().showMessage('已保存到默认实验库，离线回放：' + str(stored))
            return stored
        except Exception as exc:
            QMessageBox.warning(self, '历史实验打开失败', str(exc))

    def set_record(self, record):
        self._record = record
        self.detail.log.clear()
        for line in record.get('logs', '').splitlines():
            color = '#b91c1c' if re.search(r'失败|报错|错误|Error|Exception', line, re.I) else '#22354b'
            self.detail.log.appendHtml(f'<span style="color:{color}">{escape(line)}</span>')
        self._datasets = [Dataset.from_dict(d) for d in record['datasets']]
        self.comparison.set_data(record['results'], self._datasets, record['camera'],
            record.get('comparison', {}).get('baseline', next(iter(next(iter(record['results'].values()), {})), None)),
            project_name=record.get('experiment_name') or record.get('project', '历史实验'))
        self.logs.setPlainText(json.dumps({k: v for k, v in record.items()
            if k not in ('results', 'datasets', 'logs')}, ensure_ascii=False, indent=2)
            + '\n\n' + record.get('logs', ''))
        self.info.setText(f"{record.get('experiment_name') or record.get('project', '')}\n{record.get('saved_at', '')}\n状态：{record.get('status', '')}")
        self.ds_combo.blockSignals(True)
        self.ds_combo.clear()
        for ds in self._datasets:
            self.ds_combo.addItem(ds.name)
        selected = record.get('view', {}).get('active_dataset')
        index = next((i for i, ds in enumerate(self._datasets) if ds.name == selected), 0)
        self.ds_combo.setCurrentIndex(index)
        self.ds_combo.blockSignals(False)
        self._dataset_changed()
        view = record.get('view', {})
        self.canvas._hidden_algos = set(view.get('hidden_combinations', []))
        self.canvas._rebuild_algo_toggles()
        for layer, on in view.get('layers', {}).items():
            self.canvas._layers[layer] = on
        for layer in ('image', 'route', 'suborder', 'endpoints'):
            getattr(self, layer + '_check').setChecked(self.canvas._layers[layer])
        self.decomp_check.setChecked(view.get('decomposed', True))
        self.canvas.set_decomposed(self.decomp_check.isChecked())
        selected_run = view.get('selected_run')
        if selected_run:
            for i in range(self.run_combo.count()):
                if self.run_combo.itemData(i) == tuple(selected_run):
                    self.run_combo.setCurrentIndex(i)
                    break
        if view.get('xlim') and view.get('ylim'):
            self.canvas.ax.set_xlim(view['xlim'])
            self.canvas.ax.set_ylim(view['ylim'])
            self.canvas.canvas.draw_idle()

    def _dataset_changed(self):
        index = self.ds_combo.currentIndex()
        if index < 0 or not self._record:
            return
        ds = self._datasets[index]
        self.canvas.set_results({})
        self.canvas.set_dataset(ds, self.decomp_check.isChecked())
        self.run_combo.blockSignals(True)
        self.run_combo.clear()
        self.run_combo.addItem('全部组合叠加（各组合最优种子）', None)
        for label, runs in self._record['results'].get(ds.name, {}).items():
            for i, run in enumerate(runs):
                self.run_combo.addItem(f"{label} · seed={run.get('seed')}" + (' · 失败' if run.get('error') else ''), (label, i))
        self.run_combo.blockSignals(False)
        ci = self.comparison.ds_combo.findData(ds.name)
        if ci >= 0:
            self.comparison.ds_combo.setCurrentIndex(ci)
        self._run_changed()

    def _run_changed(self):
        if not self._record or self.ds_combo.currentIndex() < 0:
            return
        from compare.metrics import successful_run
        ds = self._datasets[self.ds_combo.currentIndex()]
        values = self._record['results'].get(ds.name, {})
        selected = self.run_combo.currentData()
        if selected:
            label, i = selected
            run = values[label][i]
            self.canvas.set_results({label: run} if successful_run(run) else {})
            self.detail.show_run(run)
        else:
            best = {}
            for label, runs in values.items():
                good = [r for r in runs if successful_run(r)]
                if good:
                    best[label] = min(good, key=lambda r: r['total_distance'])
            self.canvas.set_results(best)
            if best:
                self.detail.show_run(next(iter(best.values())))
            else:
                self.detail.clear()

    def closeEvent(self, event):
        self.library_timer.stop()
        self.comparison_window.close()
        self._assets.cleanup()
        super().closeEvent(event)
