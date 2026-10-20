# CPP Arena v2.4

无人机覆盖路径规划算法比较平台：多边形导入、区域分割、牛耕扫描、区域间连接、路径显示、实验记录及航点导出。

**当前为 v2.4 源码版，本次没有重新打包 exe。请使用 `CPP _Arena_v2.4/start.bat` 或 `python main.py` 启动；现有 `dist` 中 exe 不包含此次升级。**
本轮修复失败组合显示、固定滚动区域、运行中列表滚动以及大规模完整导出。导出在后台和独立进程中执行，可查看进度并取消；详见 [UPGRADE_v2.4.md](UPGRADE_v2.4.md)。
本轮新增6种分割和4种规划算法，总计9种分割×7种规划，可自由组成63种组合。实现范围、论文来源和预算说明见 [UPGRADE_v2.3.md](UPGRADE_v2.3.md)。新模块初始未勾选，可自行勾选或“添加组合”，每行独立配置参数。
v2.2覆盖率定义、指标解释、命名文件夹导出及历史平台升级见 [UPGRADE_v2.2.md](UPGRADE_v2.2.md)。完整导出会要求填写实验名，自动保存到历史平台默认实验库。
新增/修正内容见 [FOLLOWUP_FIXES.md](FOLLOWUP_FIXES.md)。仓库附带可单独复制运行的 [HistoryViewer](HistoryViewer/README.md)；本机现有独立部署仍保留在上级同名英文目录。
本次14项界面、导出、数据集及新增模块改进见 [WORKFLOW_v2.1.md](WORKFLOW_v2.1.md)，含相关指标解释。
本轮17项比较评价、JPEG批量导出、动态日志及分解对比改进见 [REVIEW_v2.1.md](REVIEW_v2.1.md)，其中新增指标已按您的最终确认添加。

2026-10-18版本依据三篇论文重新核对并修改代码。**可确认的原文内容、实现假设与无法严格复现的部分见 [PAPER_ALIGNMENT.md](PAPER_ALIGNMENT.md)**。不将工程改动统称为完整复刻。

v2.1按 `UPGRADE_PLAN_v1.8.md` 的 FR-1～FR-10 升级，历史说明及验收记录见 [UPGRADE_v2.1.md](UPGRADE_v2.1.md)。按用户最新要求，源码根目录的版本名随当前交付版本同步。

## 后续版本规则

每完成一轮程序更新或修复，递增一个小版本：**2.1 → 2.2 → 2.3 → 2.4…**。同一轮多项改动使用同一个版本号，同步更新版本信息、更新日志及源码文件夹名。仅登记规则、查询状态或推送已有更新不另增版本；当前为2.4，下一轮程序更新为2.5。

当前源码位置：`E:\workspace\fly\CPP Arena\CPP _Arena_v2.4`，默认图片目录随之为其下的`pictures`。数据集库和原有本地资料随源码目录保留；底图及最近工程支持从同级旧版本路径定位到新目录。独立历史实验库仍为同级`HistoryViewer/experiments`。

## 启动

Windows 本次请从源码启动。`dist/CPPArena-v2.1.exe` 是上一次打包版本，保留原样；未重新构建或发布。

从源码启动：

双击 `start.bat`，或在本目录执行：

```powershell
python main.py
```

启动脚本优先使用 `E:\anaconda\python.exe`。依赖见 `requirements.txt`；运行测试另需 `pytest`。

## 使用

1. 导入 KML 支持一次选择多个文件；数据集与底图自动保存到本程序 `dataset_library`，下次启动自动恢复。后台自动加载卫星底图；通过“显示背景图”控制显隐。离线或下载失败时，日志显示原因，地块仍可使用。
2. 手动勾绘时设置画布中心经纬度与范围（米），按坐标轴与实时边长勾绘；已有尺度错误可用“尺寸校准”。
3. 为各数据集标记起飞点，设置相机参数、航高及重叠率。
4. 在“实验”页分别勾选分割与规划模块，点击“穷举组合”。可以添加、删除组合，每行“参数设置”仅作用于该行。
5. 每行“数据集”可独立选择该组合的输入；未单独选择的行沿用当前/全部数据集范围。设置随机种子并运行，右侧实验日志显示迭代、完成与错误。
6. 画布选择组合/种子或叠加显示，查看分割、轨迹、访问顺序、绿圆入口与橙方出口；实线为区内扫描，虚线为起降和转场。点击“比较分析”在独立界面查看表格、收敛曲线和统计图。
7. 点击“完整导出实验”，填写实验名称，保存为“时间_实验名称”文件夹，包含KML、原始几何、全部已产生的结果、指标、日期/耗时、JPEG图片、相机/算法参数、日志及底图。默认直接存入历史平台的 `experiments` 实验库。
8. 历史平台已从主程序剥离。双击 `HistoryViewer/start.bat` 后自动显示默认库中的实验文件夹；外部实验用“导入实验文件夹”复制入库，旧 `.cppx/.zip/.json` 用“导入旧实验包”。本机上级目录的独立部署与仓库副本共享默认库；整份平台复制到其他位置后可独立运行。
9. “导出路线图”可选择组合；比较分析里也可用“数据集/结果组合”选择导出目标。图片默认保存到本程序 `pictures`。多种子时导出该组合航程最短的有效结果。
10. “新增分割方法 / 新增路径规划算法”支持导入独立 Python 实现，或先另存接口模板；安装后的模块可与已有模块自由组合。

旧工程可加载。含原始几何和相机快照的v2.1实验包/JSON仍可导入，来源版本保留；更早的记录若缺少输入快照，无法补齐完整回放。跨电脑复盘请复制整个v2.2实验文件夹。

## 算法

实验模块可自由组合三种分割（Bayazit、PSO-DCAS、Enhanced-ECD）与三种规划（ACO、FA3ACO、DP），共 9 种组合。DP 默认通用转场，参数 `li_adjacency_mode=1` 使用严格论文邻接约束；通用模式是工程扩展。下表记录论文组合来源。

| 选项 | 分割 | 区域间连接 |
| --- | --- | --- |
| ACO-GTSP | Kato 2025描述的Bayazit型凸分解 | 随机节点起点、全未访问节点随机探索、常数Q沉积ACO，闭环E-GTSP |
| PSO-FA3ACO | Wu 2025每凹点一维切割角PSO，以凸子区宽度和为目标 | 论文FA3ACO框架、作者时间信息素积分记忆核、Eq.18挥发、完整闭环3-opt |
| Enhanced-ECD-ACO | Li 2011增强精确单元分解与同向子区合并 | Kato ACO组合对照，非Li完整算法 |
| Enhanced-ECD-DP | Li 2011增强分割 | 仅邻接子区建边，指定起终子区的开放精确DP |

各凸片按最小宽度方向牛耕扫描，先统一航段方向再交替。默认“子区内扫描”将端点裁到边界，区内换行保持在凸子区内；尖角可能漏扫，覆盖率按实际相机足迹计算。相机页可显式选择旧“条带包络覆盖”模式，允许延长扫描端点。起降与子区间转场仍允许经过区外，显示为虚线；平台没有禁飞区避障模型。

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
- 覆盖率：扫描到的目标面积/总任务面积，按并集统计，区外不计、重复不累加；未覆盖面积为0不代表航程最优。

## 验证

v1.7.2修复计算期间窗口卡顿及PSO进度停留问题：界面通过独立进程运行算法，
阶段进度包含区域编号、PSO/FA3ACO迭代和耗时；终止会停止当前计算。
完整3-opt和信息素计算已优化，原有80只蚂蚁、500代及全部邻域保持不变。
默认大算例仍可能需要数分钟，进度持续更新时表示正在计算。
详情见 [PERFORMANCE.md](PERFORMANCE.md)。修改代码后需退出旧进程并重新启动。

```powershell
python -m pytest test_paper_alignment.py -q
python -m pytest test_responsiveness.py -q
python -m pytest test_upgrade_v21.py -q
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
