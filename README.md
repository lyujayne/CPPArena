# CPP Arena —— 无人机覆盖路径规划算法比较平台

面向学位论文的多算法覆盖路径规划（Coverage Path Planning, CPP）实验与比较平台。
内置算法严格对齐论文 [Kato et al. (2025)] *A method for planning multirotor UAV flight paths to
cover areas using the Ant Colony Optimization metaheuristic*, Computers and Electronics in
Agriculture 231:109983 的三步法：

**Bayazit 凹多边形凸分解 → 各凸子区域牛耕式内部路径 → ACO 求解 E-GTSP 区域访问顺序**

## 一键启动

双击 **`start.bat`**（Windows）。

启动脚本会自动：
1. 优先使用 `E:\anaconda\python.exe`（已预装全部依赖）；
2. 检查依赖，缺失时自动 pip 安装（首次约 1-2 分钟）；
3. 运行 `main.py` 打开图形界面。

也可手动运行：

```bash
cd "CPP _Arena_v1.0"
python main.py
```

## 快速上手

1. **导入地块**：点击"导入 KML"选择 Google Earth 导出的 KML 文件，
   或"加载卫星底图"自动拉取 Esri 卫星影像作为背景；
2. **标记起飞点**：点击"▲ 标记起飞点"在画布上单击放置；
3. **运行算法**：点击"▶ 运行选中算法"，路径自动叠加显示在画布上；
4. **查看结果**：右侧面板显示总距离、转弯次数、运行耗时等指标。

## 功能总览

| 模块 | 说明 |
| --- | --- |
| 数据输入 | KML 导入（WGS84→UTM 自动转换）、卫星底图自动拉取、手动勾绘多边形 |
| 凹多边形分解 | Mark Bayazit 算法（poly_decomp 移植），与论文 3.2 节一致 |
| 牛耕覆盖 | Boustrophedon 扫描线，同端 U 形转弯连接 |
| ACO-GTSP | 蚁群算法求解广义 TSP，α=0.5 β=20 ρ=0.7（论文穷举最优） |
| 卫星底图 | Esri World Imagery 瓦片自动下载拼接，无需 API key |
| 结果可视化 | 路径叠加画布、分解预览、区域间连接线 |
| 航点导出 | KML / CSV / TXT 格式，可导入 Mission Planner |
| 实验记录 | 每次实验自动落盘 JSON 至 `experiments/` |
| 工程保存 | 数据集+相机+算法+种子一键保存/加载 |

## 目录结构

```
CPP _Arena_v1.0/
├── main.py                     # 程序入口
├── start.bat                   # 一键启动
├── requirements.txt
├── CHANGELOG.md                # 更新日志
├── core/                       # 统一算法接口 / 注册表 / 实验调度
├── algorithms/                 # ACO-GTSP 三步法
│   ├── aco/
│   │   ├── polygon_decomp.py   # Bayazit 凸分解（论文复刻）
│   │   ├── boustrophedon.py    # 牛耕扫描
│   │   └── aco_gtsp.py         # 蚁群 E-GTSP
│   └── plugins/                # 插件目录（_ 开头不自动加载）
├── compare/                    # 指标 / 统计 / 报告
├── data/                       # 数据集 / KML / 坐标转换
│   ├── dataset.py              # 数据集管理
│   ├── coord_transform.py      # WGS84 ↔ UTM
│   ├── satellite_tiles.py      # Esri 卫星瓦片下载
│   └── samples/示例农田.kml     # 示例数据
├── gui/                        # PySide6 主窗口 / 画布 / 面板
└── config/                     # 默认参数
```

## 扩展新算法（插件机制）

在 `algorithms/plugins/` 下新建 `.py` 文件，继承 `BaseCPPAlgorithm`：

```python
from core.base_algorithm import BaseCPPAlgorithm, CPPInput, CPPResult

class MyAlgorithm(BaseCPPAlgorithm):
    name = "my-algo"
    display_name = "我的算法"
    default_params = {"seed": 42}

    def solve(self, cpp_input: CPPInput, **params) -> CPPResult:
        ...
```

重启程序即被自动识别。文件名以 `_` 开头则不加载。

## ACO 默认参数（论文穷举最优）

| 参数 | 值 | 说明 |
| --- | --- | --- |
| α | 0.5 | 信息素权重 |
| β | 20 | 距离权重 |
| ρ | 0.7 | 信息素挥发率 |
| Q | 1 | 信息素沉积量 |
| 最大迭代 | 500 | ACO 迭代次数 |

## 环境要求

- Windows 10+，Python 3.10+
- 依赖：PySide6 / Shapely / pyproj / Matplotlib / NumPy / Pandas / lxml / Pillow / requests

