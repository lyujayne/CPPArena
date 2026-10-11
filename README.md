# CPP Arena —— 无人机覆盖路径规划算法比较平台

面向学位论文的多算法覆盖路径规划（Coverage Path Planning, CPP）实验与比较平台。
内置算法严格对齐论文 [Kato et al. (2025)] *A method for planning multirotor UAV flight paths to
cover areas using the Ant Colony Optimization metaheuristic*, Computers and Electronics in
Agriculture 231:109983 的三步法：

**Bayazit 凹多边形凸分解 → 各凸子区域牛耕式内部路径 → ACO 求解 E-GTSP 区域访问顺序**

另完整复刻论文 Wu et al. (2025, *Scientific Reports* 15:37227) 的两阶段
**PSO-FA3ACO**（算法 **PSO-FA3ACO（文献完整算法）**），与基准 ACO-GTSP 并列对比：

1. **粒子群动态凹区域分割（PSO-DCAS，论文 §3.1 / Algorithm 2）**：叉积法识别
   凹点，每个凹点一个切割方向角粒子维度，粒子群以各凸子区旋转卡壳最小宽度
   之和 min Σw(R_i) 为适应度全局优化切割方向（w: 0.9→0.2，c1=c2=2）；
2. 各凸子区牛耕式往复扫描（4 种进出点方案）；
3. **FA3ACO 分数阶蚁群求解区域访问顺序（论文 §4 / Algorithm 3-4）**：
   - 分数阶状态转移（Eq.16，Grünwald–Letnikov 历史记忆，阶数 μ）；
   - 自适应信息素蒸发率 ρ(t)=ρ_min+(ρ_max−ρ_min)e^{−kt}（Eq.18，前期强探索、
     后期强利用）；
   - 逐蚂蚁 3-opt 局部搜索（Algorithm 3，8 种断边重连；E-GTSP 段反转时
     切换同子区反向进出方案节点）。

三个改进均有 0/1 开关（`fractional_order` / `adaptive_rho` / `use_three_opt`），
可复现论文 Table 2 的 ACO / 3opt-ACO / fractional-ACO / Hybrid-ACO / FA3ACO
消融对比。

## 一键启动

双击 **`start.bat`**（Windows）。

启动脚本会自动：
1. 优先使用 `E:\anaconda\python.exe`（已预装全部依赖）；
2. 检查依赖，缺失时自动 pip 安装（首次约 1-2 分钟）；
3. 运行 `main.py` 打开图形界面。

也可手动运行：

```bash
cd "CPP _Arena_v1.4"
python main.py
```

## 快速上手

1. **导入地块**：点击"导入 KML"选择 Google Earth 导出的 KML 文件（仅导入多边形
   地块，KML 中的 Point 地标不会自动设为起飞点），或"加载卫星底图"自动拉取
   Esri 卫星影像作为背景；
2. **标记起飞点**：点击"▲ 标记起飞点"在画布上单击放置；
3. **运行算法**：点击"▶ 运行选中算法"，路径自动叠加显示在画布上；
4. **查看结果**：右侧面板显示总距离、转弯次数、运行耗时等指标。

## 功能总览

| 模块 | 说明 |
| --- | --- |
| 数据输入 | KML 导入（仅多边形地块，WGS84→UTM 自动转换，起飞点手动标记）、卫星底图自动拉取、手动勾绘多边形 |
| 凹多边形分解 | ① Mark Bayazit 算法（poly_decomp 移植，基准）；② PSO 动态凹区域分割 PSO-DCAS（Wu et al. 2025 论文方式，粒子群优化切割方向、旋转卡壳宽度为目标） |
| 牛耕覆盖 | Boustrophedon 扫描线，同端 U 形转弯连接 |
| ACO-GTSP | 基准：标准蚁群（ANT-cycle + GRASP 探索 + 精英沉积）求解广义 TSP，α=0.5 β=20 ρ=0.7（Kato et al. 2025 论文穷举最优） |
| FA3ACO | Wu et al. 2025 完整算法：分数阶状态转移（Eq.16）+ 自适应蒸发率（Eq.18）+ 3-opt（Algorithm 3），蚂蚁 20 / 迭代 500 |
| 卫星底图 | Esri World Imagery 瓦片自动下载拼接，无需 API key |
| 结果可视化 | 路径叠加画布、分解预览、区域间连接线 |
| 航点导出 | KML / CSV / TXT 格式，可导入 Mission Planner |
| 实验记录 | 每次实验自动落盘 JSON 至 `experiments/` |
| 工程保存 | 数据集+相机+算法+种子一键保存/加载 |

## 目录结构

```
CPP _Arena_v1.4/
├── main.py                     # 程序入口
├── start.bat                   # 一键启动
├── requirements.txt
├── CHANGELOG.md                # 更新日志
├── core/                       # 统一算法接口 / 注册表 / 实验调度
├── algorithms/                 # ACO-GTSP 三步法
│   ├── aco/
│   │   ├── polygon_decomp.py   # Bayazit 凸分解（基准分割方式）
│   │   ├── pso_decomp.py       # PSO 动态凹区域分割 PSO-DCAS（Wu et al. 2025 §3.1）
│   │   ├── pso_fa3aco.py       # PSO-FA3ACO 算法类（PSO-DCAS 分割 + FA3ACO 求解）
│   │   ├── boustrophedon.py    # 牛耕扫描
│   │   ├── aco_gtsp.py         # 基准蚁群 E-GTSP（Kato et al. 2025）
│   │   └── fa3aco_gtsp.py      # FA3ACO 求解器：分数阶转移/自适应ρ/3-opt（Wu et al. 2025 §4）
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

## ACO-GTSP 默认参数（Kato et al. 2025 论文穷举最优）

| 参数 | 值 | 说明 |
| --- | --- | --- |
| α | 0.5 | 信息素权重 |
| β | 20 | 距离权重 |
| ρ | 0.7 | 信息素挥发率 |
| Q | 1 | 信息素沉积量 |
| 最大迭代 | 500 | ACO 迭代次数 |

## PSO-FA3ACO 默认参数（Wu et al. 2025）

PSO-DCAS 分割（论文 Table 1）：

| 参数 | 值 | 说明 |
| --- | --- | --- |
| 粒子群规模 / 迭代 | 40 / 120 | 切割方向角粒子（每凹点一维） |
| c1, c2 | 2, 2 | 个体/社会学习因子 |
| ω_max → ω_min | 0.9 → 0.2 | 惯性权重线性递减 |

FA3ACO 区域间求解（论文 §4-5；论文仅给出蚂蚁数、迭代数与 μ∈(0,1)，
其余参数论文未列具体值，取经典/标定值并可在面板调整）：

| 参数 | 值 | 说明 |
| --- | --- | --- |
| 蚂蚁数 / 迭代 | 20 / 500 | 论文 §5.1 |
| α, β | 1, 1 | 信息素/距离权重；CPP 子区进出点距离比远大于 TSPLIB 城市点距比，β 过高会首代即贪心锁死，取 1 配合 3-opt 保证全局采样 |
| μ | 0.5 | 分数阶阶数（论文限定 μ∈(0,1)） |
| ρ_max → ρ_min | 0.9 → 0.05 | 自适应蒸发率上下界（Eq.18，k=3） |
| Q | 1 | ANT-cycle 沉积量（τ0 自动取 Q/L_nn） |
| fractional_order / adaptive_rho / use_three_opt | 1 / 1 / 1 | 三大改进开关，置 0 可做论文 Table 2 消融 |

验证脚本 `test_fa3aco.py` 覆盖分数阶系数理论值、分割完整性、两种算法对比
与全部消融组合（`python test_fa3aco.py`，约 20 秒）。

## 环境要求

- Windows 10+，Python 3.10+
- 依赖：PySide6 / Shapely / pyproj / Matplotlib / NumPy / Pandas / lxml / Pillow / requests

