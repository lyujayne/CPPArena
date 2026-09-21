# CPPBench —— 无人机覆盖路径规划算法比较平台

面向论文写作的多算法覆盖路径规划（Coverage Path Planning, CPP）实验与比较平台。
内置基准算法严格对齐论文《A method for planning multirotor UAV flight paths to
cover areas using the Ant Colony Optimization metaheuristic》的三步法：

**凹多边形贪心凸分解 → 各凸子区域牛耕式内部路径（每区域 4 种进出点方案）→ ACO 求解 E-GTSP 区域访问顺序**

## 一键启动

双击 **`start.bat`**（Windows）。

启动脚本会自动：
1. 优先使用 `E:\anaconda\python.exe`（已预装全部依赖）；
2. 检查依赖，缺失时自动 pip 安装（首次约 1-2 分钟）；
3. 运行 `main.py` 打开图形界面。

也可手动运行：

```bash
cd "E:\workspace\fly\CPP Arena\CPP _Arena_v1.0"
python main.py
```

## 快速上手（3 分钟体验）

1. 启动后点击菜单 **文件 → 加载示例数据**（或直接导入自己的 Google Earth KML）；
2. 左侧「算法」页勾选参与比较的算法（默认 ACO-GTSP / 贪心最近邻 / 导入顺序），
   可用「基线算法」下拉指定相对改善率基准；
3. 左侧「实验」页选择运行模式（单次 / 多次统计 / 批量比较）与随机种子；
4. 点击 **▶ 运行实验**，结果自动呈现：
   - 中央画布：多算法路径叠加对比（可勾选「分解预览」查看凸子区域）；
   - 右侧「比较分析」：对比表格、收敛曲线（均值±标准差带）、柱状/箱线/散点图；
   - 一键导出：**LaTeX 表格（booktabs）**、CSV/JSON、PNG(300dpi)/SVG/PDF 图表、
     Markdown 实验报告、KML/CSV/TXT 航点（可导入 Mission Planner）。

## 功能总览

| 模块 | 说明 |
| --- | --- |
| 数据输入 | KML 导入（WGS84→UTM 自动转换）、图片底图 + 手动勾绘（四角经纬度校准）、区域增删改 |
| 相机参数 | 焦距/传感器/飞行高度/重叠率，实时计算 GSD、覆盖宽高、航线间距（全局共享，公平比较） |
| 算法管理 | 勾选多算法参与比较、动态参数表单、参数方案保存/加载、基线设置、插件自动识别 |
| 实验调度 | 单次 / 多次（统计稳定性）/ 批量（算法×数据集×种子全组合），后台线程不卡 UI，可终止 |
| 结果可视化 | 路径叠加画布、收敛曲线（多算法同图+均值±标准差带）、柱状/箱线/散点图、对比表 |
| 论文辅助 | LaTeX booktabs 表格、300dpi PNG / SVG / PDF 矢量图、实验报告（Methods 素材）、复现记录 |
| 实验记录 | 每次实验自动落盘 JSON 至 `experiments/`，可回溯 |
| 工程保存 | 数据集+相机+算法+种子一键保存/加载（`projects/`） |

## 目录结构

```
CPP _Arena_v1.0/
├── main.py                     # 程序入口
├── start.bat                   # 一键启动
├── requirements.txt
├── core/                       # 统一算法接口 / 注册表 / 实验调度 / 记录
├── algorithms/                 # ACO-GTSP（三步法）+ 贪心最近邻 + 导入顺序
│   └── plugins/                # 插件目录：放入新算法即被自动识别
├── compare/                    # 指标 / 统计 / 报告（LaTeX 导出）
├── data/                       # 数据集 / KML / 坐标转换 / 航点导出
│   └── samples/示例农田.kml     # 示例数据
├── gui/                        # 主窗口 / 各面板 / 画布
└── config/                     # 默认参数（ACO 采用论文最优 α=0.5 β=20 ρ=0.7 Q=1）
```

## 扩展新算法（插件机制）

复制 `algorithms/plugins/horizontal_scan.py` 并修改：

```python
from core.base_algorithm import BaseCPPAlgorithm, CPPInput, CPPResult

class MyAlgorithm(BaseCPPAlgorithm):
    name = "我的算法"
    display_name = "我的算法（说明）"
    description = "算法描述（自动生成论文素材）"
    default_params = {"seed": 42, "param_a": 1.0}

    def solve(self, cpp_input: CPPInput, **params) -> CPPResult:
        # 返回统一结果结构即可参与公平比较与论文导出
        ...
```

保存后重启程序即被自动识别并参与比较，无需修改平台核心代码。

## ACO-GTSP 默认参数（论文穷举最优组合）

| 参数 | 值 | 说明 |
| --- | --- | --- |
| α | 0.5 | 信息素权重 |
| β | 20 | 距离权重 |
| ρ | 0.7 | 信息素挥发率 |
| Q | 1 | 信息素沉积量 |
| 最大迭代 | 500 | ACO 迭代次数 |
| 蚂蚁数量 | = 节点总数 | 自动 |

## 环境要求

- Windows 10+ / macOS 11+ / Linux，Python 3.8+（推荐 3.10+）
- 依赖见 `requirements.txt`（PySide6 / Shapely / pyproj / Matplotlib / NumPy / Pandas / lxml）
