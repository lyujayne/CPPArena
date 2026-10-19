# CPP Arena v1.7.2

无人机覆盖路径规划算法比较平台：多边形导入、区域分割、牛耕扫描、区域间连接、路径显示、实验记录及航点导出。

2026-10-18版本依据三篇论文重新核对并修改代码。**可确认的原文内容、实现假设与无法严格复现的部分见 [PAPER_ALIGNMENT.md](PAPER_ALIGNMENT.md)**。不将工程改动统称为完整复刻。

## 启动

Windows 10/11（64位）用户可从 [GitHub Release](https://github.com/lyujayne/CPPArena/releases/latest) 下载 `CPPArena.exe`，无需安装Python。将exe放在可写文件夹后双击运行；首次启动需等待单文件资源解压。工程、实验记录及设置保存在exe旁，请保留这些文件夹。

从源码启动：

双击 `start.bat`，或在本目录执行：

```powershell
python main.py
```

启动脚本优先使用 `E:\anaconda\python.exe`。依赖见 `requirements.txt`；运行测试另需 `pytest`。

## 使用

1. 导入KML或勾绘多边形；可加载卫星底图。
2. 在画布标记起飞点，设置相机参数、航高及重叠率。
3. 选中算法，在参数面板查看和修改其参数。
4. 运行后查看分割、扫描路径、访问顺序、任务距离和扫描足迹覆盖率。
5. 导出KML/CSV/TXT航点或保存实验结果。

旧参数方案在新模型下不再有相同含义，重新实验前请在参数面板点“恢复默认”。已有实验记录保留，勿将新旧版本结果混作同一算法实验。

## 算法

| 选项 | 分割 | 区域间连接 |
| --- | --- | --- |
| ACO-GTSP | Kato 2025描述的Bayazit型凸分解 | 随机节点起点、全未访问节点随机探索、常数Q沉积ACO，闭环E-GTSP |
| PSO-FA3ACO | Wu 2025每凹点一维切割角PSO，以凸子区宽度和为目标 | 论文FA3ACO框架、作者时间信息素积分记忆核、Eq.18挥发、完整闭环3-opt |
| Enhanced-ECD-ACO | Li 2011增强精确单元分解与同向子区合并 | Kato ACO组合对照，非Li完整算法 |
| Enhanced-ECD-DP | Li 2011增强分割 | 仅邻接子区建边，指定起终子区的开放精确DP |

各凸片统一按最小宽度方向牛耕扫描，先统一航段方向再交替。为覆盖有限相机足迹下的尖角，航段覆盖整个条带的纵向投影范围，端点可能在地块外。程序按无禁飞区假设工作。

## 关键参数与限制

- Kato ACO：alpha=.5、beta=20、rho=.7、Q=1、500迭代；蚂蚁数等于图节点数。探索概率=.1与tau0=1为原文未给定的实现取值。没有RCL、余弦探索或精英沉积。
- Wu：80只蚂蚁、500迭代按论文第14页；20表示独立运行次数。alpha=1、beta=5及积分参数参考作者代码。分割默认40粒子、120迭代，属于实现预算。
- `fractional_mode=1` 默认使用作者信息素积分核。论文Eq.16与作者代码不同，无法同时逐式对齐。模式0核验原式，产生负概率就明确报错；不截断后伪装成原算法。
- 自适应挥发按实际迭代编号使用 `exp(-k*t)`，当前k=.006是实现取值，与旧版归一化时间中的k=3不同。
- Li起终子区参数0表示自动选择，正数可固定对应子区。邻接图无合法遍历、或超过默认16子区的精确DP上限时明确报错，不自动换算法或跳过子区。
- Li优化开放子区连接距离；起降段和内部扫描另计入任务总距离。收敛图按目标函数分开显示。
- 足迹覆盖率是固定相机航向、垂直拍摄的连续几何模型结果。实际飞控需正确设置拍照触发、相机航向和首末端拍摄；普通航点文件不包含相机触发命令。

## 指标

- 总距离：完整执行航点折线长度，包含起降段。
- 航向拐点：大于5度的航向变化；为兼容旧记录，字段仍叫 `total_turns`。
- 换行次数、扫描条带数：另存在 `metadata.turn_metrics`，不冒充同一种转弯指标。
- 分割覆盖率：子区并集与原区域交集面积/原面积。
- 扫描足迹覆盖率：扫描航段相机足迹并集与待覆盖区域的实际几何比较。

## 验证

v1.7.2修复计算期间窗口卡顿及PSO进度停留问题：界面通过独立进程运行算法，
阶段进度包含区域编号、PSO/FA3ACO迭代和耗时；终止会停止当前计算。
完整3-opt和信息素计算已优化，原有80只蚂蚁、500代及全部邻域保持不变。
默认大算例仍可能需要数分钟，进度持续更新时表示正在计算。
详情见 [PERFORMANCE.md](PERFORMANCE.md)。修改代码后需退出旧进程并重新启动。

```powershell
python -m pytest test_paper_alignment.py -q
python -m pytest test_responsiveness.py -q
python test_li_dp.py
python test_fa3aco.py
```

独立测试覆盖几何完整性、边界漏扫、交替方向、邻接DP穷举、完整3-opt邻域、参数与随机复现。论文对齐细节和未解决的原文歧义见 [PAPER_ALIGNMENT.md](PAPER_ALIGNMENT.md)。

## 主要文件

- `algorithms/aco/polygon_decomp.py`：Bayazit分割。
- `algorithms/aco/pso_decomp.py`：PSO分割及对跖点宽度算法。
- `algorithms/aco/enhanced_decomp.py`：增强分割及合并。
- `algorithms/aco/boustrophedon.py`：条带覆盖、四变体、足迹几何。
- `algorithms/aco/aco_gtsp.py`：Kato风格ACO。
- `algorithms/aco/fa3aco_gtsp.py`：分数阶模式、挥发及3-opt。
- `algorithms/aco/li_dp_connection.py`：Li邻接开放遍历DP。
- `core/experiment_runner.py`：实验运行与有效参数记录。

## 文献

- Kato et al. (2025), *A method for planning multirotor Unmanned aerial vehicle flight paths to cover areas using the Ant Colony Optimization metaheuristic*, Computers and Electronics in Agriculture 231:109983。
- Li et al. (2011), *Coverage path planning for UAVs based on enhanced exact cellular decomposition method*, Mechatronics 21:876–885, DOI 10.1016/j.mechatronics.2010.10.009。
- Wu et al. (2025), *An efficient coverage path planning method for UAV in complex concave regions*, Scientific Reports 15:37227, DOI 10.1038/s41598-025-20978-8。作者代码：[FA3ACO](https://github.com/wu457120325/FA3ACO)，核对commit为 `b9579cc203d1b0588f79a6391bee834c05a06f2e`。
