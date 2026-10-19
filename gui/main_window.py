# -*- coding: utf-8 -*-
"""主窗口：菜单栏 / 工具栏 / 左侧配置面板 / 中央画布 / 右侧结果面板 / 底部状态栏。

对应需求规格第四章：数据输入与区域管理、相机参数面板、算法管理、
实验调度、结果可视化、论文写作辅助，全部在主窗口集成。
"""
import os
import traceback
import sys
from copy import deepcopy
from datetime import datetime

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QProgressBar, QProgressDialog, QPushButton,
                               QSplitter, QTabWidget, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout,
                               QWidget, QApplication)

from core.base_algorithm import CameraParams
from compare.metrics import successful_run
from core.experiment_record import ExperimentRecorder
from core.experiment_runner import ExperimentRunner
from core.registry import AlgorithmRegistry
from core.combinations import Combination, DECOMPOSITIONS, COMPONENT_LOAD_ERRORS, build_combination_jobs
from core.experiment_bundle import make_record, dump_json, export_bundle, json_safe
from core.drawing_scale import validate_regions, calibrate_dataset
from config.app_settings import AppSettings
from config.default_params import (ALGORITHM_DEFAULTS, ALGORITHM_META,
                                   APP_NAME, APP_VERSION, BASE_DIR, RESOURCE_DIR,
                                   CAMERA_DEFAULTS, EXPERIMENT_DIR,
                                   PLUGIN_DIR, PROJECT_DIR)
from data.coord_transform import CoordTransform
from data.satellite_tiles import fetch_satellite_basemap
from data.dataset import Dataset, Project
from data.dataset_library import DatasetLibrary
from gui.algorithm_panel import AlgorithmPanel
from gui.camera_panel import CameraPanel
from gui.compare_panel import ComparePanel
from gui.decomp_compare import DecompCompareDialog
from gui.experiment_panel import ExperimentPanel
from gui.path_canvas import PathCanvas
from gui.result_panel import ResultPanel

_BUILTIN_ALGOS = {"ACO-GTSP", "PSO-FA3ACO", "Enhanced-ECD-ACO", "Enhanced-ECD-DP"}


class RunWorker(QObject):
    """后台实验线程：不阻塞 UI（对应非功能需求：批量比较异步运行）。"""

    progress = Signal(int, int, str)   # (done, total, message)
    finished = Signal(dict)            # results
    failed = Signal(str)

    def __init__(self, runner: ExperimentRunner, jobs):
        super().__init__()
        self._runner = runner
        self._jobs = jobs

    @Slot()
    def run(self):
        try:
            results = self._runner.run_jobs_isolated(
                self._jobs,
                progress=lambda d, t, m: self.progress.emit(d, t, m),
                reset_cancel=False)
            self.finished.emit(results)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


class SatelliteWorker(QObject):
    finished = Signal(object)

    def __init__(self, dataset):
        super().__init__()
        self.dataset = dataset

    @Slot()
    def run(self):
        try:
            ds = self.dataset
            x0, y0, x1, y1 = ds.bounds()
            dx, dy = max((x1-x0)*.1, 10), max((y1-y0)*.1, 10)
            tf = CoordTransform(epsg=ds.epsg)
            lon0, lat0 = tf.utm_to_lonlat(x0-dx, y0-dy)
            lon1, lat1 = tf.utm_to_lonlat(x1+dx, y1+dy)
            image, bounds = fetch_satellite_basemap(lon0, lat0, lon1, lat1,
                cancelled=lambda: QThread.currentThread().isInterruptionRequested())
            a = tf.lonlat_to_utm(bounds[0], bounds[1])
            b = tf.lonlat_to_utm(bounds[2], bounds[3])
            self.finished.emit((ds, image, (min(a[0], b[0]), min(a[1], b[1]),
                                           max(a[0], b[0]), max(a[1], b[1])), None))
        except Exception as exc:
            self.finished.emit((self.dataset, None, None, str(exc)))


class _CalibDialog(QDialog):
    """图片底图地理校准：输入四角经纬度，自动换算 UTM 范围。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("图片地理校准（四角经纬度）")
        self.setMinimumWidth(320)
        form = QFormLayout(self)
        self.ed_lon_min = QDoubleSpinBox()
        self.ed_lon_min.setRange(-180, 180)
        self.ed_lon_min.setDecimals(6)
        self.ed_lon_min.setValue(123.400000)
        self.ed_lat_min = QDoubleSpinBox()
        self.ed_lat_min.setRange(-90, 90)
        self.ed_lat_min.setDecimals(6)
        self.ed_lat_min.setValue(41.790000)
        self.ed_lon_max = QDoubleSpinBox()
        self.ed_lon_max.setRange(-180, 180)
        self.ed_lon_max.setDecimals(6)
        self.ed_lon_max.setValue(123.410000)
        self.ed_lat_max = QDoubleSpinBox()
        self.ed_lat_max.setRange(-90, 90)
        self.ed_lat_max.setDecimals(6)
        self.ed_lat_max.setValue(41.810000)
        form.addRow("西侧经度 (lon_min)", self.ed_lon_min)
        form.addRow("南侧纬度 (lat_min)", self.ed_lat_min)
        form.addRow("东侧经度 (lon_max)", self.ed_lon_max)
        form.addRow("北侧纬度 (lat_max)", self.ed_lat_max)
        hint = QLabel("校准后底图与勾绘地块将位于正确的 UTM 米制坐标，"
                      "导出航点可被 Mission Planner 识别。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:11px;")
        form.addRow(hint)
        btns = QDialogButtonBox(QDialogButtonBox.Ok
                                | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("校准")
        btns.button(QDialogButtonBox.Cancel).setText("跳过（仅预览）")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def lonlat_bounds(self):
        return (self.ed_lon_min.value(), self.ed_lat_min.value(),
                self.ed_lon_max.value(), self.ed_lat_max.value())


class MainWindow(QMainWindow):
    """CPP Arena 主窗口。"""

    def __init__(self, dataset_library_dir=None):
        super().__init__()
        self.setWindowTitle(
            f"{APP_NAME} v{APP_VERSION} —— 无人机覆盖路径规划算法比较平台")
        self.resize(1600, 960)

        self.settings = AppSettings.instance()
        self.registry = AlgorithmRegistry.instance()
        self.registry.refresh()          # 内置算法 + 插件目录扫描

        self.project = Project()
        self.dataset_library = DatasetLibrary(dataset_library_dir)
        self._library_ready = False
        self.active_dataset: Dataset = None
        self.results: dict = {}          # dataset_name -> {algo: [run]}
        self.runner = ExperimentRunner(self.registry)
        self._worker = None
        self._thread = None
        self._ds_counter = 0
        self._satellite_tasks = []
        self._record = None

        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._wire_signals()

        self.camera_panel.set_camera(CAMERA_DEFAULTS)
        self.project.camera = CameraParams.from_dict(CAMERA_DEFAULTS)
        self.algo_panel.refresh()
        self._refresh_region_list()
        self._update_status()
        self._restore_datasets()
        for error in COMPONENT_LOAD_ERRORS:
            self.experiment_panel.append_log('组件加载失败：' + error)

    # ================================================================ UI
    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)

        # ---- 左侧配置面板 ----
        left_tabs = QTabWidget()
        self.left_tabs = left_tabs
        left_tabs.addTab(self._build_data_panel(), "数据")
        self.camera_panel = CameraPanel()
        left_tabs.addTab(self.camera_panel, "相机参数")
        self.algo_panel = AlgorithmPanel(self.registry, self)
        self.algo_panel.hide()  # Legacy metadata provider; old experiment UI is replaced.
        self.experiment_panel = ExperimentPanel()
        left_tabs.addTab(self.experiment_panel, "实验")
        left_tabs.setMinimumWidth(480)
        left_tabs.setMaximumWidth(640)
        left_tabs.setCurrentWidget(self.experiment_panel)

        # ---- 中央画布 ----
        self.canvas = PathCanvas()
        # 显示选项复选框：放在画布工具栏右侧（替代原来左侧面板的位置）
        self.decomp_check = QCheckBox("分解预览（凸子区域）")
        # 分解预览所用分割算法下拉框（各算法的分割方式）
        self.decomp_algo_label = QLabel("分割算法:")
        self.decomp_algo_combo = QComboBox()
        self.decomp_algo_combo.setToolTip("选择分解预览使用哪个算法的分割方式")
        for key, (label, cls) in DECOMPOSITIONS.items():
            self.decomp_algo_combo.addItem(label, key)
        self.btn_decomp_compare = QPushButton("分解对比")
        self.btn_decomp_compare.setToolTip("弹出新窗口，并排对比各算法对每个地块的分割结果")
        self.route_check = QCheckBox("显示路径（移动路径+访问顺序）")
        self.route_check.setChecked(True)
        self.suborder_check = QCheckBox("显示子区域访问顺序")
        self.suborder_check.setChecked(True)
        self.canvas.add_toolbar_extra(self.decomp_check)
        self.canvas.add_toolbar_extra(self.decomp_algo_label)
        self.canvas.add_toolbar_extra(self.decomp_algo_combo)
        self.canvas.add_toolbar_extra(self.btn_decomp_compare)
        self.canvas.add_toolbar_extra(self.route_check)
        self.canvas.add_toolbar_extra(self.suborder_check)
        self.endpoints_check = QCheckBox('显示入口 / 出口（绿圆 / 橙方）')
        self.endpoints_check.setChecked(True)
        self.endpoints_check.toggled.connect(lambda on: self.canvas.set_layer('endpoints', on))
        self.canvas.add_toolbar_extra(self.endpoints_check)
        self.background_check = QCheckBox("显示背景图")
        self.background_check.setChecked(True)
        self.canvas.add_toolbar_extra(self.background_check)
        self.run_combo = QComboBox()
        self.run_combo.setMinimumWidth(180)
        self.run_combo.setToolTip("选择组合/种子查看完整轨迹、分割和指标")
        self.canvas.add_toolbar_extra(self.run_combo)
        self.canvas.add_toolbar_extra(QLabel('切换数据集：'))
        self.canvas_dataset_combo = QComboBox()
        self.canvas_dataset_combo.setToolTip('直接切换观察的数据集，无需返回数据页；不改变已开始的实验输入。')
        self.canvas_dataset_combo.currentIndexChanged.connect(self._dataset_changed)
        self.canvas.add_toolbar_extra(self.canvas_dataset_combo)

        # ---- 右侧结果面板 ----
        self.right_tabs = QTabWidget()
        self.result_panel = ResultPanel()
        self.result_panel.attach_log_box(self.experiment_panel.log_box, self.experiment_panel.log)
        self.compare_panel = ComparePanel()
        self.comparison_window = QMainWindow(self, Qt.Window)
        self.comparison_window.setWindowTitle(f'{APP_NAME} v{APP_VERSION} · 比较分析')
        self.comparison_window.resize(1320, 880)
        self.comparison_window.setCentralWidget(self.compare_panel)
        self.right_tabs.addTab(self.result_panel, "单算法结果")
        self.right_tabs.setMinimumWidth(330)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_compare = QPushButton('比较分析')
        self.btn_compare.setObjectName('PrimaryButton')
        self.btn_compare.clicked.connect(self._open_comparison)
        right_layout.addWidget(self.btn_compare)
        right_layout.addWidget(self.right_tabs, 1)

        splitter.addWidget(left_tabs)
        splitter.addWidget(self.canvas)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([520, 730, 350])
        self.setCentralWidget(splitter)

    def _build_data_panel(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)

        g = QGroupBox("数据输入")
        gv = QVBoxLayout(g)
        row = QHBoxLayout()
        self.btn_import_kml = QPushButton("导入 KML（支持多选）")
        self.btn_import_img = QPushButton("导入图片底图")
        row.addWidget(self.btn_import_kml)
        row.addWidget(self.btn_import_img)
        gv.addLayout(row)
        v.addWidget(g)
        self.dataset_combo = QComboBox()
        v.addWidget(self.dataset_combo)
        self.btn_remove_dataset = QPushButton('移除当前数据集')
        self.btn_remove_dataset.clicked.connect(self._remove_dataset)
        v.addWidget(self.btn_remove_dataset)

        g2 = QGroupBox("区域列表（勾选/删除/重命名）")
        g2v = QVBoxLayout(g2)
        self.region_list = QListWidget()
        g2v.addWidget(self.region_list)
        row2 = QHBoxLayout()
        self.btn_del_region = QPushButton("删除区域")
        self.btn_rename_region = QPushButton("重命名")
        row2.addWidget(self.btn_del_region)
        row2.addWidget(self.btn_rename_region)
        g2v.addLayout(row2)
        self.btn_draw = QPushButton("✏ 勾绘地块")
        self.btn_launch = QPushButton("▲ 标记起飞点")
        self.btn_finish = QPushButton("✓ 完成勾绘")
        self.btn_cancel_draw = QPushButton("取消绘制")
        row3a = QHBoxLayout()
        row3a.addWidget(self.btn_draw)
        row3a.addWidget(self.btn_launch)
        row3b = QHBoxLayout()
        row3b.addWidget(self.btn_finish)
        row3b.addWidget(self.btn_cancel_draw)
        g2v.addLayout(row3a)
        g2v.addLayout(row3b)
        self.btn_calibrate = QPushButton("尺寸校准（设定地块宽度 / 米）")
        g2v.addWidget(self.btn_calibrate)
        v.addWidget(g2, 1)

        self.data_info = QLabel("请导入 KML 或图片底图，\n"
                                "或新建空数据集后手动勾绘地块。")
        self.data_info.setWordWrap(True)
        self.data_info.setStyleSheet("color:#666;font-size:11px;"
                                     "background:#f5f5f5;padding:4px;")
        v.addWidget(self.data_info)
        return w

    def _build_menus(self):
        mb = self.menuBar()

        m_file = mb.addMenu("文件(&F)")
        m_file.addAction(self._act("导入 KML(&K)...", self._import_kml))
        m_file.addAction(self._act("导入图片底图(&I)...", self._import_image))
        m_file.addAction(self._act("新建空数据集(&N)", self._new_dataset))
        m_file.addSeparator()
        m_file.addAction(self._act("导出航点(&E)...", self.compare_panel.export_waypoints))
        m_file.addAction(self._act("保存工程(&S)", self._save_project, "Ctrl+S"))
        m_file.addAction(self._act("加载工程(&O)...", self._load_project, "Ctrl+O"))
        m_file.addSeparator()
        m_file.addAction(self._act("加载示例数据(&D)", self._load_sample_data))
        m_file.addSeparator()
        m_file.addAction(self._act("退出(&X)", self.close))

        m_view = mb.addMenu("视图(&V)")
        m_view.addAction(self._act("缩放适配(&F)", self.canvas.fit_view))
        m_view.addAction(self._act("重置视图(&R)", self.canvas.reset_view))
        m_view.addAction(self._act("图层管理(&L)...", self._layer_dialog))
        self.act_decomp = self._act("分解预览(&D)", self._toggle_decomposed)
        self.act_decomp.setCheckable(True)
        m_view.addAction(self.act_decomp)

        m_exp = mb.addMenu("实验(&X)")
        m_exp.addAction(self._act("组合实验设置", lambda: self.left_tabs.setCurrentWidget(self.experiment_panel)))
        m_exp.addAction(self._act("运行组合清单", lambda: self.run_experiment("combinations")))
        m_exp.addAction(self._act("完整导出实验...", self._export_experiment))
        m_exp.addSeparator()
        m_exp.addAction(self._act("终止当前实验(&T)", self._stop_experiment))
        m_exp.addAction(self._act("清除实验结果(&C)", self._clear_results, "F5"))
        m_exp.addAction(self._act("恢复默认参数(&D)", self._reset_all_params))

        m_tool = mb.addMenu("工具(&T)")
        m_tool.addAction(self._act("比较分析(&S)", self._open_comparison))
        m_tool.addAction(self._act("报告生成(&R)...", self.compare_panel.generate_report))
        m_tool.addAction(self._act("算法插件管理(&P)...", self._plugin_dialog))

        m_help = mb.addMenu("帮助(&H)")
        m_help.addAction(self._act("算法说明(&A)...", self._algo_help_dialog))
        m_help.addAction(self._act("关于(&B)", self._about))

    def _build_toolbar(self):
        tb = self.addToolBar("主工具栏")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        tb.addAction(self._act("运行组合清单", lambda: self.run_experiment("combinations")))
        tb.addAction(self._act("组合设置", lambda: self.left_tabs.setCurrentWidget(self.experiment_panel)))
        tb.addAction(self._act("完整导出", self._export_experiment))
        tb.addAction(self._act("比较分析", self._open_comparison))
        tb.addSeparator()
        tb.addAction(self._act("清除结果", self._clear_results))
        tb.addAction(self._act("导出图表", self.compare_panel.export_figure))
        tb.addAction(self._act('导出路线图', self._export_route_image))
        tb.addAction(self._act("保存工程", self._save_project))

    def _build_statusbar(self):
        sb = self.statusBar()
        self.sb_stage = QLabel("就绪")
        sb.addWidget(self.sb_stage)
        self.sb_progress = QProgressBar()
        self.sb_progress.setMaximumWidth(200)
        self.sb_progress.setVisible(False)
        sb.addWidget(self.sb_progress)
        self.sb_algo = QLabel("算法：--")
        sb.addPermanentWidget(self.sb_algo)

    def _wire_signals(self):
        self.btn_import_kml.clicked.connect(self._import_kml)
        self.btn_import_img.clicked.connect(self._import_image)
        self.btn_calibrate.clicked.connect(self._calibrate_drawing)
        self.dataset_combo.currentIndexChanged.connect(self._dataset_changed)
        self.run_combo.currentIndexChanged.connect(self._select_run)
        self.background_check.toggled.connect(lambda on: self.canvas.set_layer('image', on))
        self.btn_del_region.clicked.connect(self._delete_region)
        self.btn_rename_region.clicked.connect(self._rename_region)
        self.btn_draw.clicked.connect(self._start_drawing)
        self.btn_finish.clicked.connect(self.canvas.finish_polygon)
        self.btn_launch.clicked.connect(self.canvas.start_set_launch)
        self.btn_cancel_draw.clicked.connect(self.canvas.cancel_draw)
        self.decomp_check.toggled.connect(self.canvas.set_decomposed)
        # 分解预览：选择使用哪个算法的分割方式
        self.decomp_algo_combo.currentIndexChanged.connect(
            self._on_decomp_algo_changed)
        self.btn_decomp_compare.clicked.connect(self._open_decomp_compare)
        # 「显示路径」总开关：同时控制移动路径（区域间连接+内部覆盖）与访问顺序
        self.route_check.toggled.connect(self._on_route_toggled)
        self.suborder_check.toggled.connect(
            lambda on: self.canvas.set_layer("suborder", on))
        self.region_list.itemSelectionChanged.connect(self._on_region_selected)

        self.canvas.polygon_drawn.connect(self._on_polygon_drawn)
        self.canvas.launch_point_set.connect(self._on_launch_point_set)
        self.canvas.region_picked.connect(self._on_region_picked)

        self.camera_panel.changed.connect(self._on_camera_changed)
        self.algo_panel.algorithms_changed.connect(
            lambda: self._update_status(self.sb_stage.text()))
        self.algo_panel.run_requested.connect(
            lambda: self.run_experiment("single"))
        self.experiment_panel.run_requested.connect(self.run_experiment)
        self.experiment_panel.stop_requested.connect(self._stop_experiment)
        self.experiment_panel.export_requested.connect(self._export_experiment)
        self.experiment_panel.component_requested.connect(self._add_component)

    def _export_route_image(self):
        if not self.results:
            return self.compare_panel._no_data()
        selection = self.run_combo.currentData()
        if self.active_dataset:
            index = self.compare_panel.ds_combo.findData(self.active_dataset.name)
            if index >= 0:
                self.compare_panel.ds_combo.setCurrentIndex(index)
        if selection:
            index = self.compare_panel.wp_algo_combo.findData(selection[0])
            if index >= 0:
                self.compare_panel.wp_algo_combo.setCurrentIndex(index)
        labels = list(self.compare_panel._active_runs())
        if not labels:
            return self.compare_panel._no_data()
        self.compare_panel.choose_route_images()

    def _restore_datasets(self):
        try:
            self.project.datasets = self.dataset_library.load()
            self._library_ready = True
            self.experiment_panel.set_datasets(self.project.datasets)
            if self.project.datasets:
                self._set_active_dataset(self.project.datasets[0])
                self.experiment_panel.append_log(f'已从数据集库恢复 {len(self.project.datasets)} 个数据集。')
        except Exception as exc:
            self.experiment_panel.append_log('数据集库读取失败（原文件保留）：' + str(exc))

    def _save_datasets(self):
        if self._library_ready:
            try:
                self.dataset_library.save(self.project.datasets)
            except Exception as exc:
                self.experiment_panel.append_log('数据集库保存失败：' + str(exc))

    def _remove_dataset(self):
        ds = self.active_dataset
        if ds is None:
            return
        self.project.datasets = [item for item in self.project.datasets if item.id != ds.id]
        self.active_dataset = None
        self.dataset_combo.clear()
        self.canvas.set_results({})
        if self.project.datasets:
            self._set_active_dataset(self.project.datasets[0])
        else:
            self.canvas.set_dataset(None)
            self._refresh_region_list()

    def _add_component(self, kind):
        from core.component_plugins import install_component
        from gui.component_dialog import ComponentInstallDialog
        dialog = ComponentInstallDialog(kind, self)
        if dialog.exec() == QDialog.Accepted:
            try:
                key = install_component(dialog.path_edit.text(), kind)
                self.experiment_panel.refresh_modules()
                if kind == 'decomposition':
                    index = self.decomp_algo_combo.findData(key)
                    if index < 0:
                        self.decomp_algo_combo.addItem(DECOMPOSITIONS[key][0], key)
                    else:
                        self.decomp_algo_combo.setItemText(index, DECOMPOSITIONS[key][0])
                    self.canvas._decomp_cache.clear()
                self.experiment_panel.append_log('已安装组件：' + key)
            except Exception as exc:
                QMessageBox.warning(self, '组件安装失败', str(exc))

    def _view_state(self):
        return {'layers': dict(self.canvas._layers), 'decomposed': self.decomp_check.isChecked(),
                'xlim': list(self.canvas.ax.get_xlim()), 'ylim': list(self.canvas.ax.get_ylim()),
                'hidden_combinations': list(self.canvas._hidden_algos),
                'active_dataset': self.active_dataset.name if self.active_dataset else None,
                'selected_run': self.run_combo.currentData()}

    def _export_experiment(self):
        if not self._record:
            QMessageBox.information(self, '完整导出', '请先完成一次组合实验。')
            return
        path, _ = QFileDialog.getSaveFileName(self, '完整导出实验',
            os.path.join(EXPERIMENT_DIR, self._record['id'] + '.cppx'),
            'CPP Arena 实验包 (*.cppx);;ZIP (*.zip)')
        if not path:
            return
        if not path.lower().endswith(('.cppx', '.zip')):
            path += '.cppx'
        try:
            record = deepcopy(self._record)
            self._sync_record_backgrounds(record)
            record['view'] = self._view_state()
            export_bundle(path, record)
            self.experiment_panel.append_log('完整实验包已导出：' + path)
            self.statusBar().showMessage('完整实验包已导出：' + path, 8000)
        except Exception as exc:
            self.experiment_panel.append_log('导出报错：' + str(exc))
            QMessageBox.critical(self, '导出失败', str(exc))

    def _sync_record_backgrounds(self, record):
        # Background download may finish after the solver's immutable snapshot.
        # Copy it only when it still belongs to the exact saved input geometry.
        for saved in record['datasets']:
            for current in self.project.datasets:
                if (current.name == saved['name'] and current.epsg == saved['epsg']
                        and json_safe([r.to_dict() for r in current.regions]) == saved['regions']
                        and current.bg_image_path and os.path.isfile(current.bg_image_path)):
                    for key in ('bg_image_path', 'bg_bounds_utm', 'bg_corners_lonlat'):
                        saved[key] = json_safe(getattr(current, key))

    def _open_comparison(self):
        if not self.results:
            QMessageBox.information(self, '比较分析', '请先运行实验，再打开比较分析。')
            return
        self.comparison_window.show()
        self.comparison_window.raise_()
        self.comparison_window.activateWindow()

    def _refresh_run_choices(self):
        self.run_combo.blockSignals(True)
        self.run_combo.clear()
        self.run_combo.addItem('全部组合叠加', None)
        ds = self.active_dataset
        if ds:
            for label, runs in self.results.get(ds.name, {}).items():
                for index, run in enumerate(runs):
                    self.run_combo.addItem(f"{label} · seed={run.get('seed')}" + (' · 失败' if run.get('error') else ''), (label, index))
        self.run_combo.blockSignals(False)

    def _select_run(self):
        selection = self.run_combo.currentData()
        if not selection:
            self._show_canvas_results(self.results)
            return
        label, index = selection
        run = self.results[self.active_dataset.name][label][index]
        self.canvas.set_results({label: run} if not run.get('error') else {})
        self.result_panel.show_run(run)

    def _dataset_changed(self, index):
        if index >= 0 and index < len(self.project.datasets):
            if self.active_dataset is self.project.datasets[index]:
                return
            self._set_active_dataset(self.project.datasets[index])
            self._show_canvas_results(self.results)
            self._show_result_panel(self.results)
            self._refresh_run_choices()

    def _start_drawing(self):
        if self.active_dataset is None:
            self._new_dataset(activate=False)
            self._set_active_dataset(self.project.datasets[-1])
        ds = self.active_dataset
        if not ds.regions and not ds.bg_bounds_utm:
            dialog = QDialog(self)
            dialog.setWindowTitle('勾绘参照 · 坐标与长度单位为米')
            form = QFormLayout(dialog)
            lon, lat, width = QDoubleSpinBox(), QDoubleSpinBox(), QDoubleSpinBox()
            lon.setRange(-180, 180); lon.setDecimals(6); lon.setValue(117)
            lat.setRange(-79, 83); lat.setDecimals(6); lat.setValue(40)
            width.setRange(1, 100000); width.setValue(1000); width.setSuffix(' m')
            form.addRow('画布中心经度（请填实际位置）', lon)
            form.addRow('画布中心纬度', lat)
            form.addRow('可见范围宽度', width)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
            form.addRow(buttons)
            if dialog.exec() != QDialog.Accepted:
                return
            tf = CoordTransform(lon=lon.value(), lat=lat.value())
            ds.epsg = tf.epsg
            center = tf.lonlat_to_utm(lon.value(), lat.value())
            self.canvas.set_metric_view(center, width.value())
        self.canvas.start_draw_polygon()

    def _calibrate_drawing(self):
        ds = self.active_dataset
        if not ds or not ds.regions:
            QMessageBox.information(self, '尺寸校准', '请先勾绘地块。首次勾绘可设置经纬度与米制范围。')
            return
        width = max(p[0] for r in ds.regions for p in r.vertices)-min(p[0] for r in ds.regions for p in r.vertices)
        value, ok = QInputDialog.getDouble(self, '尺寸校准',
            '所有地块的实际总宽度（米）。以中心等比缩放，起飞点同步变换；需重新运行实验。\n校准将移除旧底图以免坐标错配。', max(width, 100), .01, 100000, 2)
        if ok:
            try:
                calibrate_dataset(ds, value)
                self._clear_results()
                self._record = None
                self.canvas.set_dataset(ds, False)
                self._refresh_region_list()
            except ValueError as exc:
                QMessageBox.warning(self, '尺寸校准', str(exc))

    def _act(self, text, slot, shortcut=None):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(shortcut)
        a.triggered.connect(slot)
        return a

    # ================================================================ 数据
    def _append_dataset(self, ds):
        base = ds.name
        existing = {value.name for value in self.project.datasets}
        number = 2
        while ds.name in existing:
            ds.name = f'{base} ({number})'
            number += 1
        self.project.datasets.append(ds)
        self.experiment_panel.set_datasets(self.project.datasets)
        self._save_datasets()

    def _new_dataset(self, activate: bool = True) -> Dataset:
        self._ds_counter += 1
        ds = Dataset(name=f"勾绘数据集{self._ds_counter}")
        self._append_dataset(ds)
        if activate:
            self._set_active_dataset(ds)
            self._start_drawing()
        return ds

    def _import_kml(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '导入多个 KML 数据集', '', 'KML (*.kml);;所有文件 (*)')
        if paths:
            self.import_kml_paths(paths)

    def import_kml_paths(self, paths):
        loaded, errors = [], []
        for path in paths:
            try:
                ds = Dataset(name=os.path.splitext(os.path.basename(path))[0])
                ds.load_kml(path)
                self._append_dataset(ds)
                self._set_active_dataset(ds)
                self._load_satellite()
                loaded.append(ds)
            except Exception as exc:
                errors.append(os.path.basename(path) + '：' + str(exc))
        self._save_datasets()
        if loaded:
            self.statusBar().showMessage(f'已导入并保存 {len(loaded)} 个数据集；请分别标记起飞点。', 8000)
        if errors:
            self.experiment_panel.append_log('导入错误：' + '\n'.join(errors))
            QMessageBox.warning(self, '部分数据导入失败', '\n'.join(errors))
        return loaded

    def _import_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入图片底图", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.tif);;所有文件 (*)")
        if not path:
            return
        dlg = _CalibDialog(self)
        if dlg.exec() == QDialog.Accepted:
            lon_min, lat_min, lon_max, lat_max = dlg.lonlat_bounds()
            try:
                tf = CoordTransform(lon=(lon_min + lon_max) / 2.0,
                                    lat=(lat_min + lat_max) / 2.0)
                p1 = tf.lonlat_to_utm(lon_min, lat_min)
                p2 = tf.lonlat_to_utm(lon_max, lat_max)
                bounds = (min(p1[0], p2[0]), min(p1[1], p2[1]),
                          max(p1[0], p2[0]), max(p1[1], p2[1]))
                epsg = tf.epsg
            except Exception as e:
                QMessageBox.warning(self, "校准失败",
                                    f"经纬度换算失败：{e}\n使用默认范围预览。")
                bounds, epsg = (0.0, 0.0, 1000.0, 1000.0), 32650
        else:
            bounds, epsg = (0.0, 0.0, 1000.0, 1000.0), 32650

        ds = Dataset(name=os.path.splitext(os.path.basename(path))[0])
        ds.bg_image_path = path
        ds.bg_bounds_utm = bounds
        ds.epsg = epsg
        self._append_dataset(ds)
        self._set_active_dataset(ds)
        self.canvas.start_draw_polygon()
        self.statusBar().showMessage("图片底图已导入，请在画布上勾绘地块", 5000)

    def _load_satellite(self):
        ds = self.active_dataset
        if ds is None or not ds.regions:
            return
        self.experiment_panel.append_log('正在自动加载卫星底图：' + ds.name)
        thread = QThread(self)
        worker = SatelliteWorker(ds)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._satellite_loaded)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._satellite_thread_finished)
        self._satellite_tasks.append((thread, worker))
        thread.start()

    def _satellite_loaded(self, payload):
        ds, image, bounds, error = payload
        if error:
            self.experiment_panel.append_log('底图加载失败：' + error + '；可继续进行实验。')
            return
        ds.bg_image_path, ds.bg_bounds_utm = image, bounds
        if self.active_dataset is ds:
            self.canvas.set_dataset(ds, self.decomp_check.isChecked())
            self._refresh_region_list()
        self.experiment_panel.append_log('卫星底图已加载：' + ds.name)
        self._save_datasets()

    def _satellite_thread_finished(self):
        thread = self.sender()
        self._satellite_tasks = [(t, w) for t, w in self._satellite_tasks if t is not thread]
        thread.deleteLater()

    def _load_sample_data(self):
        sample = os.path.join(RESOURCE_DIR, "data", "samples", "示例农田.kml")
        if not os.path.exists(sample):
            QMessageBox.information(self, "提示", "未找到示例数据文件：\n" + sample)
            return
        try:
            ds = Dataset(name="示例农田")
            ds.load_kml(sample)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"{type(e).__name__}: {e}")
            return
        self._append_dataset(ds)
        self._set_active_dataset(ds)
        self.statusBar().showMessage("已加载示例数据（含 1 个凹多边形地块，"
                                     "可直接运行 ACO-GTSP 验证）", 6000)

    # ---------------- 区域操作 ----------------
    def _set_active_dataset(self, ds: Dataset):
        self.active_dataset = ds
        self.dataset_combo.blockSignals(True)
        self.dataset_combo.clear()
        for value in self.project.datasets:
            self.dataset_combo.addItem(value.name)
        if ds in self.project.datasets:
            self.dataset_combo.setCurrentIndex(self.project.datasets.index(ds))
        self.dataset_combo.blockSignals(False)
        self.canvas.set_results({})
        self.canvas.set_dataset(ds, self.decomp_check.isChecked())
        self._refresh_region_list()

    def _refresh_region_list(self):
        self.canvas_dataset_combo.blockSignals(True)
        self.canvas_dataset_combo.clear()
        for value in self.project.datasets:
            self.canvas_dataset_combo.addItem(value.name, value.id)
        self.canvas_dataset_combo.setCurrentIndex(self.project.datasets.index(self.active_dataset)
            if self.active_dataset in self.project.datasets else -1)
        self.canvas_dataset_combo.blockSignals(False)
        self.experiment_panel.set_datasets(self.project.datasets)
        self._save_datasets()
        self.region_list.clear()
        ds = self.active_dataset
        if ds is None:
            self.data_info.setText("未加载数据集。\n导入 KML / 图片底图，"
                                   "或新建空数据集后手动勾绘。")
            return
        for r in ds.regions:
            item = QListWidgetItem(f"{r.name}（{len(r.vertices)} 顶点）")
            item.setData(Qt.UserRole, r.id)
            self.region_list.addItem(item)
        launch = "已设置" if ds.launch_point else "未设置"
        info = (f"数据集：{ds.name}  |  区域数：{len(ds.regions)}  |  "
                f"起飞点：{launch}  |  EPSG:{ds.epsg}")
        if ds.bg_image_path:
            info += "\n底图：" + os.path.basename(ds.bg_image_path)
        self.data_info.setText(info)

    def _on_region_selected(self):
        row = self.region_list.currentRow()
        ds = self.active_dataset
        if row < 0 or ds is None or row >= len(ds.regions):
            return
        r = ds.regions[row]
        self.statusBar().showMessage(
            f"选中区域：{r.name}（{len(r.vertices)} 顶点，id={r.id}）", 3000)

    def _on_region_picked(self, region_id: int):
        ds = self.active_dataset
        if ds is None:
            return
        for i, r in enumerate(ds.regions):
            if r.id == region_id:
                self.region_list.setCurrentRow(i)
                return

    def _delete_region(self):
        row = self.region_list.currentRow()
        ds = self.active_dataset
        if row < 0 or ds is None or row >= len(ds.regions):
            QMessageBox.information(self, "提示", "请先在列表中选择要删除的区域")
            return
        rid = ds.regions[row].id
        ds.remove_region(rid)
        self._refresh_region_list()
        self.canvas.set_dataset(ds, self.decomp_check.isChecked())

    def _rename_region(self):
        row = self.region_list.currentRow()
        ds = self.active_dataset
        if row < 0 or ds is None or row >= len(ds.regions):
            QMessageBox.information(self, "提示", "请先在列表中选择要重命名的区域")
            return
        region = ds.regions[row]
        new, ok = QInputDialog.getText(self, "重命名区域",
                                       "新名称：", text=region.name)
        if ok and new.strip():
            ds.rename_region(region.id, new.strip())
            self._refresh_region_list()

    # ---------------- 勾绘 ----------------
    def _on_polygon_drawn(self, pts):
        ds = self.active_dataset
        if ds is None:
            # 首次勾绘：新建并立即设为活动数据集
            self._ds_counter += 1
            ds = Dataset(name=f"勾绘数据集{self._ds_counter}")
            self._append_dataset(ds)
            self.active_dataset = ds
        try:
            ds.add_region(f"区域{len(ds.regions) + 1}", list(pts))
        except ValueError as e:
            QMessageBox.warning(self, "多边形无效", str(e))
            return
        self._refresh_region_list()
        self.canvas.set_dataset(ds, self.decomp_check.isChecked())
        # 保持勾绘模式，可连续绘制下一个地块；点「取消绘制」退出
        self.canvas.start_draw_polygon()
        self.statusBar().showMessage(
            f"已添加地块（{len(ds.regions)} 个），可继续点击绘制下一个，"
            f"或点「取消绘制」结束", 4000)

    def _on_launch_point_set(self, xy):
        ds = self.active_dataset
        if ds is None:
            ds = self._new_dataset(activate=False)
        ds.launch_point = (float(xy[0]), float(xy[1]))
        self._refresh_region_list()
        self.canvas.set_dataset(ds, self.decomp_check.isChecked())

    # ================================================================ 参数
    def _on_camera_changed(self):
        self.project.camera = CameraParams.from_dict(
            self.camera_panel.get_camera())

    def _reset_all_params(self):
        for combo in self.experiment_panel.combinations:
            combo.decomposition_params.clear()
            combo.planning_params.clear()
        self.experiment_panel.refresh_table()
        self.camera_panel.set_camera(CAMERA_DEFAULTS)
        self._on_camera_changed()
        self.statusBar().showMessage("已恢复全部默认参数", 3000)

    # ================================================================ 实验
    def run_experiment(self, mode='combinations'):
        if self._thread is not None:
            return
        panel = self.experiment_panel
        if not panel.combinations:
            self.left_tabs.setCurrentWidget(panel)
            QMessageBox.warning(self, '组合清单为空', '请先点击“穷举组合”或“添加组合”。')
            return
        defaults = (self.project.datasets if panel.scope_combo.currentData() == 'all'
                    else [self.active_dataset] if self.active_dataset else [])
        try:
            seeds = panel.seeds()
            camera = self.camera_panel.get_camera()
            snapshot = [Dataset.from_dict(deepcopy(ds.to_dict())) for ds in self.project.datasets]
            combinations = [Combination(**c.to_dict()) for c in panel.combinations]
            jobs = build_combination_jobs(combinations, snapshot, seeds, camera,
                                           default_dataset_ids=[ds.id for ds in defaults])
            selected = {job.dataset.id: job.dataset for job in jobs}
            if not jobs or any(not ds.regions for ds in selected.values()):
                raise ValueError('请导入或勾绘有效地块，并为组合选择数据集。')
            if any(ds.launch_point is None for ds in selected.values()):
                raise ValueError('请为参与实验的数据集分别标记起飞点。')
            cam = CameraParams.from_dict(camera)
            issues = [issue for ds in selected.values() for issue in validate_regions(ds, cam)]
            if issues:
                raise ValueError('\n'.join(issues))
        except ValueError as exc:
            QMessageBox.warning(self, '运行前检查', str(exc))
            return
        self._start_worker(jobs, 'combinations', seeds, camera)

    def _start_worker(self, jobs, mode, seeds, camera):
        self._run_datasets = []
        for job in jobs:
            if not any(ds.name == job.dataset.name for ds in self._run_datasets):
                self._run_datasets.append(Dataset.from_dict(deepcopy(job.dataset.to_dict())))
        unique = {job.combination['id']: job.combination for job in jobs if job.combination}
        self._run_combinations = [Combination(**item) for item in unique.values()]
        self.canvas.cancel_draw()
        self.runner.prepare()
        self.experiment_panel.set_running(True)
        self.left_tabs.setTabEnabled(0, False)
        self.left_tabs.setTabEnabled(1, False)
        self.algo_panel.btn_run.setEnabled(False)
        self.sb_progress.setVisible(True)
        self.sb_progress.setMaximum(len(jobs))
        self.sb_progress.setValue(0)

        # 注意：必须连接主窗口的绑定方法（QObject 接收者），PySide6 才会
        # 按 AutoConnection 排队到主线程；连接裸 lambda 会以 DirectConnection
        # 在工作线程执行 GUI 更新，导致崩溃。
        self._pending = (mode, seeds, camera)
        self._worker = RunWorker(self.runner, jobs)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_experiment_done)
        self._worker.failed.connect(self._on_experiment_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_worker_finished)
        self._thread.start()

    def _on_progress(self, done, total, msg):
        self.experiment_panel.set_progress(done, total, msg)
        self.sb_progress.setMaximum(max(total, 1))
        self.sb_progress.setValue(min(done, total))
        self.sb_stage.setText(msg)

    def _on_experiment_done(self, results):
        mode, seeds, camera = self._pending
        self.results = results
        state = 'cancelled' if self.runner.cancelled else 'completed'
        if state == 'completed' and any(r.get('error') for ds in results.values() for runs in ds.values() for r in runs):
            state = 'completed_with_errors'
        self.experiment_panel.append_log('实验已终止，已完成结果已保存' if self.runner.cancelled else '全部组合执行结束')
        self._record = make_record(self.project.name, self._run_datasets, camera,
            self._run_combinations, results, self.experiment_panel.log.toPlainText(), self._view_state(), state, seeds=seeds)
        self._sync_record_backgrounds(self._record)
        try:
            rec_path = os.path.join(EXPERIMENT_DIR, 'experiment_' + self._record['id'] + '.json')
            dump_json(rec_path, self._record)
        except Exception as exc:
            rec_path = '记录保存失败：' + str(exc)
            self.experiment_panel.append_log(rec_path)

        self._show_canvas_results(results)
        self._show_result_panel(results)
        self.compare_panel.set_data(
            results, self._run_datasets, camera,
            next(iter(next(iter(results.values()), {})), None),
            algos_meta=ALGORITHM_META,
            params_by_algo=self.algo_panel.get_all_params(),
            seeds=seeds, project_name=self.project.name)
        self.right_tabs.setCurrentWidget(self.result_panel)
        self.statusBar().showMessage(
            f"{'实验已终止' if self.runner.cancelled else '实验完成'}：{jobs_desc(mode)}，记录：{rec_path}", 8000)
        has_failures = any(run.get('error') for values in results.values()
                           for runs in values.values() for run in runs)
        self.sb_stage.setText("已终止" if self.runner.cancelled else
                              "完成（部分算法失败，见结果说明）" if has_failures else "完成")

    def _show_canvas_results(self, results):
        """在活动数据集上叠加各算法最优运行。"""
        ds = self.active_dataset
        if ds is None or ds.name not in results:
            return
        best_by_algo = {}
        for algo, runs in results[ds.name].items():
            runs = [run for run in runs if successful_run(run)]
            if runs:
                best_by_algo[algo] = min(
                    runs, key=lambda r: r.get("total_distance", float("inf")))
        self.canvas.set_results(best_by_algo)
        self._refresh_run_choices()

    def _show_result_panel(self, results):
        self.result_panel.clear()
        ds = self.active_dataset
        if ds is None or ds.name not in results:
            return
        runs_by_algo = results[ds.name]
        for algo in runs_by_algo:
            runs = runs_by_algo.get(algo) or []
            runs = [run for run in runs if successful_run(run)]
            if runs:
                best = min(runs, key=lambda r: r.get("total_distance",
                                                     float("inf")))
                self.result_panel.show_run(best)
                return

    def _on_experiment_failed(self, msg):
        self.experiment_panel.append_log("实验报错：" + msg)
        QMessageBox.critical(self, "实验失败", msg)
        self.sb_stage.setText("失败")

    def _on_worker_finished(self):
        self._thread = None
        self._worker = None
        self.experiment_panel.set_running(False)
        self.left_tabs.setTabEnabled(0, True)
        self.left_tabs.setTabEnabled(1, True)
        self.algo_panel.btn_run.setEnabled(True)
        self.sb_progress.setVisible(False)

    def _stop_experiment(self):
        self.runner.cancel()
        self.sb_stage.setText("正在终止…")
        self.statusBar().showMessage("已请求终止，正在停止当前任务…", 4000)

    def _clear_results(self):
        """清除本次实验产生的所有结果显示（画布路径叠加、右侧面板、比较面板），
        保留数据集、多边形、起飞点与卫星底图。"""
        self.results = {}
        self.canvas.set_results({})
        self.result_panel.clear()
        self.compare_panel.clear()
        self._refresh_run_choices()
        self._update_status("结果已清除")
        self.statusBar().showMessage(
            "已清除实验结果（数据集、多边形、起飞点与底图保留）", 4000)

    # ================================================================ 视图
    def _toggle_decomposed(self, on: bool):
        self.decomp_check.setChecked(on)
        self.canvas.set_decomposed(on)

    def _on_route_toggled(self, on: bool):
        """「显示路径」总开关：勾选显示移动路径与访问顺序，取消则一并隐藏；
        关闭时「显示子区域访问顺序」复选框从属禁用。"""
        self.canvas.set_layer("route", on)
        self.suborder_check.setEnabled(on)

    def _on_decomp_algo_changed(self, _idx: int):
        """分解预览切换为所选算法的分割方式，并自动打开分解预览。"""
        name = self.decomp_algo_combo.currentData()
        self.canvas.set_decomp_algorithm(name)
        if not self.decomp_check.isChecked():
            self.decomp_check.setChecked(True)   # 触发 set_decomposed

    def _open_decomp_compare(self):
        """弹出分割方式对比窗口：行=地块，列=各算法。"""
        ds = self.active_dataset
        if ds is None or not ds.regions:
            QMessageBox.information(self, "分解对比", "请先导入或勾绘地块后再进行分解对比。")
            return
        select = QDialog(self)
        select.setWindowTitle('选择参与对比的分割方式')
        layout = QVBoxLayout(select)
        checks = []
        for key, (label, cls) in DECOMPOSITIONS.items():
            check = QCheckBox(label)
            check.setChecked(self.experiment_panel.decomp_checks[key].isChecked())
            layout.addWidget(check)
            checks.append((check, key))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(select.accept)
        buttons.rejected.connect(select.reject)
        layout.addWidget(buttons)
        if select.exec() != QDialog.Accepted:
            return
        selected = [name for check, name in checks if check.isChecked()]
        if not selected:
            QMessageBox.information(self, '分解对比', '请至少选择一种分割方式。')
            return
        from core.combinations import component_defaults
        params_by_algo = {key: dict(component_defaults('decomposition', key), seed=42) for key in selected}
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            dlg = DecompCompareDialog(
                ds, selected, registry=self.registry,
                params_by_algo=params_by_algo, parent=self)
        finally:
            QApplication.restoreOverrideCursor()
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        self._decomp_dlg = dlg   # 保持引用，非模态打开
        dlg.show()

    def _layer_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("图层管理")
        v = QVBoxLayout(dlg)
        checks = {}
        labels = {"regions": "区域边界", "subregions": "分解子区域",
                  "internal": "内部覆盖路径", "transitions": "区域间连接",
                  "launch": "起飞点", "image": "底图"}
        for key, text in labels.items():
            c = QCheckBox(text)
            c.setChecked(self.canvas._layers.get(key, True))
            checks[key] = c
            v.addWidget(c)
        btn = QPushButton("应用")
        btn.clicked.connect(dlg.accept)
        v.addWidget(btn)
        if dlg.exec() == QDialog.Accepted:
            for key, c in checks.items():
                self.canvas.set_layer(key, c.isChecked())

    # ================================================================ 工具/帮助
    def _plugin_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("算法插件管理")
        v = QVBoxLayout(dlg)
        table = QTableWidget()
        names = self.registry.names()
        table.setRowCount(len(names))
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["算法", "显示名", "类型"])
        for i, name in enumerate(names):
            m = self.registry.meta(name)
            typ = "内置" if name in _BUILTIN_ALGOS else "插件"
            table.setItem(i, 0, QTableWidgetItem(name))
            table.setItem(i, 1, QTableWidgetItem(m.get("display_name", "")))
            table.setItem(i, 2, QTableWidgetItem(typ))
        table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(table)
        row = QHBoxLayout()
        btn_open = QPushButton("打开插件目录")
        btn_open.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(PLUGIN_DIR)))
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        row.addWidget(btn_open)
        row.addStretch(1)
        row.addWidget(btn_close)
        v.addLayout(row)
        hint = QLabel("新算法放入 plugins 目录（.py、继承 BaseCPPAlgorithm、"
                      "定义 name）重启后自动识别。")
        hint.setStyleSheet("color:#888;font-size:11px;")
        v.addWidget(hint)
        dlg.resize(560, 360)
        dlg.exec()

    def _algo_help_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("算法说明")
        dlg.resize(640, 480)
        v = QVBoxLayout(dlg)
        tb = QTextBrowser()
        lines = []
        for name in self.registry.names():
            m = self.registry.meta(name)
            lines.append(f"## {m.get('display_name', name)}")
            if m.get("description"):
                lines.append(m["description"])
            if m.get("citation"):
                lines.append(f"- 文献引用：{m['citation']}")
            if m.get("scope"):
                lines.append(f"- 适用范围：{m['scope']}")
            if m.get("params_note"):
                lines.append(f"- 参数说明：{m['params_note']}")
            lines.append("")
        lines += [
            "---",
            "## ACO-GTSP 默认参数（论文穷举最优组合）",
            "| 参数 | 值 | 说明 |",
            "| --- | --- | --- |",
            "| α | 0.5 | 信息素权重 |",
            "| β | 20 | 距离权重 |",
            "| ρ | 0.7 | 信息素挥发率 |",
            "| Q | 1 | 信息素沉积量 |",
            "| 最大迭代 | 500 | ACO 迭代次数 |",
            "| 蚂蚁数 | = 节点总数 | 自动 |",
            "",
            "对应基准文献：《A method for planning multirotor UAV flight "
            "paths to cover areas using the Ant Colony Optimization "
            "metaheuristic》",
        ]
        tb.setMarkdown("\n".join(lines))
        v.addWidget(tb)
        dlg.exec()

    def _about(self):
        QMessageBox.about(
            self, f"关于 {APP_NAME}",
            f"<b>{APP_NAME} v{APP_VERSION}</b><br><br>"
            "无人机覆盖路径规划（CPP）算法比较平台<br>"
            "内置三种切割/算法：ACO-GTSP（Bayazit，基准）、PSO-FA3ACO（PSO-DCAS）、"
            "Enhanced-ECD-ACO（增强精确单元分解，Li 2011），"
            "支持多算法 × 多数据集 × 多随机种子公平比较，"
            "一键导出论文图表与 LaTeX 表格。<br><br>"
            "技术栈：PySide6 · Shapely · pyproj · Matplotlib · NumPy · Pandas")

    # ================================================================ 工程
    def _save_project(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存工程", os.path.join(PROJECT_DIR,
                                       f"{self.project.name}.json"),
            "JSON (*.json)")
        if not path:
            return
        try:
            self.project.combinations = [c.to_dict() for c in self.experiment_panel.combinations]
            self.project.seeds = self.experiment_panel.seeds()
            self.project.experiment_mode = 'combinations'
            self.project.save(path)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"{type(e).__name__}: {e}")
            return
        self.settings.add_recent_project(path)
        self.statusBar().showMessage(f"工程已保存：{path}", 5000)

    def _load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载工程", PROJECT_DIR,
                                              "JSON (*.json)")
        if not path:
            return
        try:
            p = Project.load(path)
            combinations = [Combination(**c) for c in p.combinations]
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"{type(e).__name__}: {e}")
            return
        merged = {ds.id: ds for ds in self.project.datasets}
        merged.update({ds.id: ds for ds in p.datasets})
        p.datasets = list(merged.values())
        names = set()
        for ds in p.datasets:
            base, number = ds.name, 2
            while ds.name in names:
                ds.name = f'{base} ({number})'
                number += 1
            names.add(ds.name)
        self.project = p
        self.experiment_panel.combinations = combinations
        self.experiment_panel.refresh_table()
        self.camera_panel.set_camera(p.camera.as_dict())
        self._on_camera_changed()
        self.experiment_panel.set_mode(p.experiment_mode)
        self.experiment_panel.set_seeds_text(p.seeds or [42])
        self.algo_panel.refresh()
        for i in range(self.algo_panel.algo_list.count()):
            item = self.algo_panel.algo_list.item(i)
            item.setCheckState(
                Qt.Checked if item.data(Qt.UserRole) in p.selected_algorithms
                else Qt.Unchecked)
        self.results = {}
        self.canvas.set_results({})
        self.result_panel.clear()
        if p.datasets:
            self._set_active_dataset(p.datasets[0])
        self.settings.add_recent_project(path)
        self._update_status("工程已加载")
        self.statusBar().showMessage(f"工程已加载：{path}", 5000)

    # ================================================================ 状态
    def _update_status(self, stage: str = None):
        if stage is not None:
            self.sb_stage.setText(stage)
        self.sb_algo.setText(f"组合实验 · v{APP_VERSION}")

    def closeEvent(self, event):
        if self._thread is not None:
            self.runner.cancel()
            # Coordinator polls every50ms and kills a non-cooperating child.
            # Never destroy a running QThread or block the GUI for seconds.
            self._thread.finished.connect(self.close)
            self.sb_stage.setText("正在停止计算并关闭…")
            event.ignore()
            return
        if self._satellite_tasks:
            self.sb_stage.setText('正在结束底图加载…')
            for thread, _ in self._satellite_tasks:
                thread.requestInterruption()
                thread.finished.connect(self.close)
            event.ignore()
            return
        self._save_datasets()
        self.comparison_window.close()
        self.algo_panel.deleteLater()
        super().closeEvent(event)


def jobs_desc(mode: str) -> str:
    return {"single": "单算法快速验证", "repeated": "多次运行统计",
            "batch": "批量比较"}.get(mode, mode)
