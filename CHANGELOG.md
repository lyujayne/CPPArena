# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

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
