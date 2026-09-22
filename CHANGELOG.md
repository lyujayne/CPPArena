# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [1.1.0] - 2026-09-22

本版聚焦 KML 导入流程的修正：将起飞点识别从 KML 中剥离、改为画布手动标记，
并修复跨地区 KML 导致 UTM 投影带选错、多边形被压成竖线的问题。功能与算法
均无变化，仅影响数据导入环节。

### 新增

- **清除实验结果**：工具栏新增「🧹 清除结果」按钮（或实验菜单 → 清除实验结果，
  快捷键 F5）。一键清空画布上的路径叠加、右侧单算法结果与比较面板的表格/曲线/
  统计图表，无需重启程序；数据集、多边形、起飞点与卫星底图保留。
- **子区域访问顺序显示**：左侧面板新增「显示子区域访问顺序」复选框（默认开启）。
  在 Bayazit 分解出的每个凸子区中心，按 ACO-E-GTSP 求解出的实际访问先后
  标注蓝色圈数字（1、2、3…），勾选即可开/关。

### 修复

- **KML 跨地区坐标 bug**：当 KML 中的 `<Point>` 地标与 `<Polygon>` 地块不在同一
  UTM 带时，旧逻辑优先用 Point（起飞点）经纬度选投影带，把远在另一半球的多边形
  硬塞进错误的 UTM 带投影，导致多边形被压成一根竖线、坐标量级达 1e7 米（实测
  起飞点在沈阳 123°E/41.5°N、多边形在巴西 -55°W/-10.8°S 时复现）。
- **牛耕扫描方向选反**：`choose_sweep_direction` 旧代码选「顶点到边最大距离最大」
  的边（最短轴），与论文 Algorithm 1「选该距离最小的边（多边形最长轴）、沿其
  平行方向扫」相反，导致不规则地块被斜向扫描。已改为选最小距离边，扫描线沿
  最长轴、转弯最少（与论文 Fig.6/Fig.7 一致）。

### 变更

- **KML 导入仅加载多边形地块**：不再把 KML 中的 `<Point>` 地标自动识别为起飞点。
  起飞点统一由用户在画布上点击「▲ 标记起飞点」手动放置。
- UTM 投影带改按多边形自身位置选择，与起飞点解耦，避免跨地区 KML 投影错位。
- 导入 KML 成功后状态栏提示「请点击 ▲ 标记起飞点」。
- **画布重绘保留缩放视图**：切换图层、开/关子区域序号时，不再把用户已放大的
  视图重置回全图；仅在导入/新建数据集时重新自适应取景。
- 单算法结果面板移除「区域访问顺序」一行显示（数据内部仍保留，仅不展示）。

### 涉及文件

- `data/kml_handler.py`：`parse_kml` 移除 `<Point>` 解析，仅返回多边形列表。
- `data/dataset.py`：`load_kml` 不再从 KML 读取起飞点，UTM 带按多边形首点选择。
- `gui/main_window.py`：导入 KML 后状态栏补充标记起飞点提示；新增子区域访问顺序复选框。
- `gui/path_canvas.py`：新增 `suborder` 图层绘制子区访问序号；重绘时保存/恢复视图范围。
- `gui/result_panel.py`：移除「区域访问顺序」行。
- `algorithms/aco/boustrophedon.py`：`choose_sweep_direction` 修正为选最小距离边（最长轴）。
- `algorithms/aco/__init__.py`：记录每个被访问凸子区的多边形顶点与访问序号。
- `core/base_algorithm.py`：`CPPResult` 新增 `subregion_sequence` 字段。
- `core/experiment_runner.py`：结果字典补传 `subregion_sequence`。
- `config/default_params.py`：版本号升至 1.1.0。

## [2.0.0] - 2026-09-21

### 新增

- **凹多边形分解**：移植 Mark Bayazit 算法（`poly_decomp` 0.0.1），与 Kato et al. (2025)
  *Computers and Electronics in Agriculture* 所用分解方式一致，支持生成 Steiner 点。
- **卫星底图**：一键从 Esri World Imagery 自动下载瓦片拼接，按地块 UTM 范围对齐，
  无需手动截图校准。
- **ACO-GTSP 算法**：蚁群算法求解广义旅行商问题，结合凸分解 + 牛耕扫描覆盖。
- **批量实验**：支持多算法、多种子批量运行，结果对比分析。
- **工程保存/加载**：数据集、相机参数、算法选择一键存档。
- **航点导出**：生成 KML 航点文件，可导入 Mission Planner。
- **KML 导入**：支持 WGS84 经纬度 → UTM 自动转换，自动识别 UTM 分区。

### 修复

- 牛耕扫描 Z 形连接 bug：每条扫描线补充 entry 点，连接线改为同端垂直连接。
- 航线长度计算：修复 `_seg_len` 只算扫描线、漏算连接线的问题。
- KML 索引 bug：纯地形 KML（无 Point 地标）导入时经纬度解包错误导致崩溃。

### 变更

- 算法面板精简为仅保留 ACO-GTSP。
- 插件目录 `horizontal_scan.py` 重命名为 `_horizontal_scan.py`（不被自动扫描）。

### 技术栈

- Python 3.13 + PySide6 GUI
- shapely 几何计算
- pyproj 坐标转换（WGS84 ↔ UTM）
- matplotlib 路径可视化
