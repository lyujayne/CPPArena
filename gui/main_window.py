# -*- coding: utf-8 -*-
"""主窗口：菜单栏 / 工具栏 / 左侧配置面板 / 中央画布 / 右侧结果面板 / 底部状态栏。

对应需求规格第四章：数据输入与区域管理、相机参数面板、算法管理、
实验调度、结果可视化、论文写作辅助，全部在主窗口集成。
"""
import os
import traceback

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QProgressBar, QProgressDialog, QPushButton,
                               QSplitter, QTabWidget, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout,
                               QWidget, QApplication)

from core.base_algorithm import CameraParams
from core.experiment_record import ExperimentRecorder
from core.experiment_runner import ExperimentRunner
from core.registry import AlgorithmRegistry
from config.app_settings import AppSettings
from config.default_params import (ALGORITHM_DEFAULTS, ALGORITHM_META,
                                   APP_NAME, APP_VERSION, BASE_DIR,
                                   CAMERA_DEFAULTS, EXPERIMENT_DIR,
                                   PLUGIN_DIR, PROJECT_DIR)
from data.coord_transform import CoordTransform
from data.satellite_tiles import fetch_satellite_basemap
from data.dataset import Dataset, Project
from gui.algorithm_panel import AlgorithmPanel
from gui.camera_panel import CameraPanel
from gui.compare_panel import ComparePanel
from gui.experiment_panel import ExperimentPanel
from gui.path_canvas import PathCanvas
from gui.result_panel import ResultPanel

_BUILTIN_ALGOS = {"ACO-GTSP"}


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
            results = self._runner.run_jobs(
                self._jobs,
                progress=lambda d, t, m: self.progress.emit(d, t, m))
            self.finished.emit(results)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


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

    def __init__(self):
        super().__init__()
        self.setWindowTitle(
            f"{APP_NAME} v{APP_VERSION} —— 无人机覆盖路径规划算法比较平台")
        self.resize(1440, 900)

        self.settings = AppSettings.instance()
        self.registry = AlgorithmRegistry.instance()
        self.registry.refresh()          # 内置算法 + 插件目录扫描

        self.project = Project()
        self.active_dataset: Dataset = None
        self.results: dict = {}          # dataset_name -> {algo: [run]}
        self.runner = ExperimentRunner(self.registry)
        self._worker = None
        self._thread = None
        self._ds_counter = 0

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

    # ================================================================ UI
    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)

        # ---- 左侧配置面板 ----
        left_tabs = QTabWidget()
        left_tabs.addTab(self._build_data_panel(), "数据")
        self.camera_panel = CameraPanel()
        left_tabs.addTab(self.camera_panel, "相机参数")
        self.algo_panel = AlgorithmPanel(self.registry)
        left_tabs.addTab(self.algo_panel, "算法")
        self.experiment_panel = ExperimentPanel()
        left_tabs.addTab(self.experiment_panel, "实验")
        left_tabs.setMinimumWidth(300)
        left_tabs.setMaximumWidth(380)

        # ---- 中央画布 ----
        self.canvas = PathCanvas()
        # 显示选项复选框：放在画布工具栏右侧（替代原来左侧面板的位置）
        self.decomp_check = QCheckBox("分解预览（凸子区域）")
        self.suborder_check = QCheckBox("显示子区域访问顺序")
        self.suborder_check.setChecked(True)
        self.canvas.add_toolbar_extra(self.decomp_check)
        self.canvas.add_toolbar_extra(self.suborder_check)

        # ---- 右侧结果面板 ----
        self.right_tabs = QTabWidget()
        self.result_panel = ResultPanel()
        self.compare_panel = ComparePanel()
        self.right_tabs.addTab(self.result_panel, "单算法结果")
        self.right_tabs.addTab(self.compare_panel, "比较分析")
        self.right_tabs.setMinimumWidth(480)

        splitter.addWidget(left_tabs)
        splitter.addWidget(self.canvas)
        splitter.addWidget(self.right_tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([300, 600, 520])
        self.setCentralWidget(splitter)

    def _build_data_panel(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)

        g = QGroupBox("数据输入")
        gv = QVBoxLayout(g)
        row = QHBoxLayout()
        self.btn_import_kml = QPushButton("导入 KML")
        self.btn_import_img = QPushButton("导入图片底图")
        self.btn_sat = QPushButton("加载卫星底图")
        row.addWidget(self.btn_import_kml)
        row.addWidget(self.btn_import_img)
        row.addWidget(self.btn_sat)
        gv.addLayout(row)
        v.addWidget(g)

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
        m_exp.addAction(self._act("运行单算法（快速验证）(&S)",
                                  lambda: self.run_experiment("single")))
        m_exp.addAction(self._act("运行批量比较(&B)...",
                                  lambda: self.run_experiment("batch")))
        m_exp.addSeparator()
        m_exp.addAction(self._act("终止当前实验(&T)", self.runner.cancel))
        m_exp.addAction(self._act("清除实验结果(&C)", self._clear_results, "F5"))
        m_exp.addAction(self._act("恢复默认参数(&D)", self._reset_all_params))

        m_tool = mb.addMenu("工具(&T)")
        m_tool.addAction(self._act("结果统计(&S)",
                                   lambda: self.right_tabs.setCurrentWidget(
                                       self.compare_panel)))
        m_tool.addAction(self._act("报告生成(&R)...", self.compare_panel.generate_report))
        m_tool.addAction(self._act("算法插件管理(&P)...", self._plugin_dialog))

        m_help = mb.addMenu("帮助(&H)")
        m_help.addAction(self._act("算法说明(&A)...", self._algo_help_dialog))
        m_help.addAction(self._act("关于(&B)", self._about))

    def _build_toolbar(self):
        tb = self.addToolBar("主工具栏")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        tb.addAction(self._act("▶ 运行选中算法", lambda: self.run_experiment("single")))
        tb.addAction(self._act("▶▶ 批量比较", lambda: self.run_experiment("batch")))
        tb.addSeparator()
        tb.addAction(self._act("🧹 清除结果", self._clear_results))
        tb.addAction(self._act("导出图表", self.compare_panel.export_figure))
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
        self.btn_sat.clicked.connect(self._load_satellite)
        self.btn_del_region.clicked.connect(self._delete_region)
        self.btn_rename_region.clicked.connect(self._rename_region)
        self.btn_draw.clicked.connect(self.canvas.start_draw_polygon)
        self.btn_finish.clicked.connect(self.canvas.finish_polygon)
        self.btn_launch.clicked.connect(self.canvas.start_set_launch)
        self.btn_cancel_draw.clicked.connect(self.canvas.cancel_draw)
        self.decomp_check.toggled.connect(self.canvas.set_decomposed)
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

    def _act(self, text, slot, shortcut=None):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(shortcut)
        a.triggered.connect(slot)
        return a

    # ================================================================ 数据
    def _new_dataset(self, activate: bool = True) -> Dataset:
        self._ds_counter += 1
        ds = Dataset(name=f"勾绘数据集{self._ds_counter}")
        self.project.datasets.append(ds)
        if activate:
            self._set_active_dataset(ds)
            self.canvas.start_draw_polygon()
        return ds

    def _import_kml(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 KML", "", "KML (*.kml);;所有文件 (*)")
        if not path:
            return
        try:
            ds = Dataset(name=os.path.splitext(os.path.basename(path))[0])
            ds.load_kml(path)
        except Exception as e:
            QMessageBox.critical(self, "导入失败",
                                 f"{type(e).__name__}: {e}")
            return
        self.project.datasets.append(ds)
        self._set_active_dataset(ds)
        self.statusBar().showMessage(
            f"已导入 KML：{os.path.basename(path)}"
            f"（{len(ds.regions)} 个区域，EPSG:{ds.epsg}）；"
            f"请点击 ▲ 标记起飞点", 8000)

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
        self.project.datasets.append(ds)
        self._set_active_dataset(ds)
        self.canvas.start_draw_polygon()
        self.statusBar().showMessage("图片底图已导入，请在画布上勾绘地块", 5000)

    def _load_satellite(self):
        """根据当前数据集的 UTM 范围自动下载 Esri 卫星瓦片作为底图。"""
        ds = self.active_dataset
        if ds is None or not ds.regions:
            QMessageBox.information(self, "提示", "请先导入 KML 或勾绘地块，再加载卫星底图。")
            return
        bounds = ds.bounds()
        if bounds is None:
            return
        minx, miny, maxx, maxy = bounds
        # 外扩 10% 余量
        pad_x = (maxx - minx) * 0.10
        pad_y = (maxy - miny) * 0.10
        minx -= pad_x; maxx += pad_x
        miny -= pad_y; maxy += pad_y

        # UTM -> 经纬度
        try:
            tf = CoordTransform(epsg=ds.epsg)
            lon_min, lat_min = tf.utm_to_lonlat(minx, miny)
            lon_max, lat_max = tf.utm_to_lonlat(maxx, maxy)
        except Exception as e:
            QMessageBox.critical(self, "坐标转换失败", str(e))
            return

        prog = QProgressDialog("正在下载卫星瓦片…", "取消", 0, 100, self)
        prog.setWindowTitle("卫星底图")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)

        def cb(done, total):
            prog.setMaximum(total)
            prog.setValue(done)
            QApplication.processEvents()

        try:
            img_path, (iln0, ila0, iln1, ila1) = fetch_satellite_basemap(
                lon_min, lat_min, lon_max, lat_max, progress_cb=cb)
        except Exception as e:
            QMessageBox.critical(self, "卫星底图下载失败",
                                 f"{type(e).__name__}: {e}")
            return
        finally:
            prog.close()

        # 瓦片实际覆盖的经纬度 -> UTM
        try:
            p0 = tf.lonlat_to_utm(iln0, ila0)
            p1 = tf.lonlat_to_utm(iln1, ila1)
            utm_bounds = (min(p0[0], p1[0]), min(p0[1], p1[1]),
                          max(p0[0], p1[0]), max(p0[1], p1[1]))
        except Exception:
            utm_bounds = (minx, miny, maxx, maxy)

        ds.bg_image_path = img_path
        ds.bg_bounds_utm = utm_bounds
        self._set_active_dataset(ds)
        self.statusBar().showMessage(
            f"卫星底图已加载：{os.path.basename(img_path)}", 6000)
    def _load_sample_data(self):
        sample = os.path.join(BASE_DIR, "data", "samples", "示例农田.kml")
        if not os.path.exists(sample):
            QMessageBox.information(self, "提示", "未找到示例数据文件：\n" + sample)
            return
        try:
            ds = Dataset(name="示例农田")
            ds.load_kml(sample)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"{type(e).__name__}: {e}")
            return
        self.project.datasets.append(ds)
        self._set_active_dataset(ds)
        self.statusBar().showMessage("已加载示例数据（含 1 个凹多边形地块，"
                                     "可直接运行 ACO-GTSP 验证）", 6000)

    # ---------------- 区域操作 ----------------
    def _set_active_dataset(self, ds: Dataset):
        self.active_dataset = ds
        self.canvas.set_dataset(ds, self.decomp_check.isChecked())
        self._refresh_region_list()

    def _refresh_region_list(self):
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
            self.project.datasets.append(ds)
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
        self.algo_panel._restore_defaults()
        self.camera_panel.set_camera(CAMERA_DEFAULTS)
        self._on_camera_changed()
        self.statusBar().showMessage("已恢复全部默认参数", 3000)

    # ================================================================ 实验
    def run_experiment(self, mode: str):
        if self._thread is not None:
            return
        algos = self.algo_panel.selected_names()
        if not algos:
            QMessageBox.warning(self, "提示", "请至少勾选一个算法参与比较")
            return
        if mode in ("single", "repeated") and self.active_dataset is None:
            QMessageBox.warning(self, "提示", "请先导入数据或新建数据集")
            return
        seeds = self.experiment_panel.seeds()
        params = self.algo_panel.get_all_params()
        camera = self.camera_panel.get_camera()
        jobs = ExperimentRunner.build_jobs(
            algos, self.project.datasets, seeds, mode=mode,
            active_dataset=self.active_dataset,
            params_by_algo=params, camera=camera)
        if not jobs:
            QMessageBox.warning(self, "提示",
                                "没有可运行的任务（检查数据集与算法选择）")
            return
        self._start_worker(jobs, mode, seeds, camera)

    def _start_worker(self, jobs, mode, seeds, camera):
        self.experiment_panel.set_running(True)
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
        # 实验记录自动落盘（JSON 历史库）
        try:
            rec = ExperimentRecorder()
            rec_path = rec.save_record(
                self.project.name, camera, seeds, mode, results,
                meta={"baseline": self.algo_panel.baseline_name()})
        except Exception as e:
            rec_path = f"记录保存失败：{e}"

        self._show_canvas_results(results)
        self._show_result_panel(results)
        self.compare_panel.set_data(
            results, self.project.datasets, camera,
            self.algo_panel.baseline_name(),
            algos_meta=ALGORITHM_META,
            params_by_algo=self.algo_panel.get_all_params(),
            seeds=seeds, project_name=self.project.name)
        self.right_tabs.setCurrentWidget(self.compare_panel)
        self.statusBar().showMessage(
            f"实验完成：{jobs_desc(mode)}，记录：{rec_path}", 8000)
        self.sb_stage.setText("完成")

    def _show_canvas_results(self, results):
        """在活动数据集上叠加各算法最优运行。"""
        ds = self.active_dataset
        if ds is None or ds.name not in results:
            return
        best_by_algo = {}
        for algo, runs in results[ds.name].items():
            if runs:
                best_by_algo[algo] = min(
                    runs, key=lambda r: r.get("total_distance", float("inf")))
        self.canvas.set_results(best_by_algo)

    def _show_result_panel(self, results):
        ds = self.active_dataset
        if ds is None or ds.name not in results:
            return
        runs_by_algo = results[ds.name]
        for algo in self.algo_panel.selected_names():
            runs = runs_by_algo.get(algo) or []
            if runs:
                best = min(runs, key=lambda r: r.get("total_distance",
                                                     float("inf")))
                self.result_panel.show_run(best)
                return

    def _on_experiment_failed(self, msg):
        QMessageBox.critical(self, "实验失败", msg)
        self.sb_stage.setText("失败")

    def _on_worker_finished(self):
        self._thread = None
        self._worker = None
        self.experiment_panel.set_running(False)
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
        self._update_status("结果已清除")
        self.statusBar().showMessage(
            "已清除实验结果（数据集、多边形、起飞点与底图保留）", 4000)

    # ================================================================ 视图
    def _toggle_decomposed(self, on: bool):
        self.decomp_check.setChecked(on)
        self.canvas.set_decomposed(on)

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
            "内置 ACO-GTSP 基准算法（严格对齐论文三步法），"
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
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"{type(e).__name__}: {e}")
            return
        self.project = p
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
        names = self.algo_panel.selected_names()
        self.sb_algo.setText("算法：" + ("、".join(names) if names else "--"))

    def closeEvent(self, event):
        if self._thread is not None:
            self.runner.cancel()
            self._thread.quit()
            self._thread.wait(3000)
        super().closeEvent(event)


def jobs_desc(mode: str) -> str:
    return {"single": "单算法快速验证", "repeated": "多次运行统计",
            "batch": "批量比较"}.get(mode, mode)
