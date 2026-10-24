# CPP Arena v2.9

Windows x64 可在 [GitHub Releases v2.9](https://github.com/lyujayne/CPPArena/releases/tag/v2.9) 下载，无需安装 Python 即可运行主程序。

- [下载独立 EXE](https://github.com/lyujayne/CPPArena/releases/download/v2.9/CPPArena-v2.9.exe)：放在可写文件夹中，双击启动。
- [下载便携包 ZIP](https://github.com/lyujayne/CPPArena/releases/download/v2.9/CPPArena-v2.9-windows-x64.zip)：完整解压后启动同名 EXE，附带历史平台源码、说明与许可证。
- 发布页提供 SHA256 校验文件及对应源码，可从页面的 Source code 下载本次代码。

已发布到 [PyPI cpp-arena 2.9](https://pypi.org/project/cpp-arena/2.9/)，可执行 `python -m pip install cpp-arena` 后使用 `cpp-arena` 启动；支持 Windows x64、64 位 Python 3.10+。发布记录及构建步骤见 [PUBLISH_PYPI.md](PUBLISH_PYPI.md)。项目整体采用 [GPL-3.0-or-later](LICENSE)，第三方声明见 [NOTICE](NOTICE)。

无人机覆盖路径规划算法比较平台：多边形导入、区域分割、牛耕扫描、区域间连接、路径显示、实验记录及航点导出。

**当前发布版本为 v2.9，提供 Windows x64 单文件 EXE、便携包和源码。仅发布现有版本，不另增版本号。**
本轮更新六种分割：TD改为局部首次边界射线和多方向搜索；HM与Greene直接使用CGAL 6.0.1参考实现；IEE采用首次边界射线、论文平衡候选及最小宽度IP；RGS逐候选递归比较；TD-DP采用邻接集合重组与宽度目标。暂不添加有风时间、凸包外扩或外部可选单元。实现范围、未对齐部分、参数和验证见 [v2.9实现报告](UPGRADE_v2.9.md)。
v2.8改进组合参数方案显示：默认方案显示“默认参数”，修改后显示“已修改N项”，悬停列出分割/规划参数的“默认值→当前值”；恢复默认后清除修改标记。
v2.7新增“统一设置所有组合的数据集”：在实验页一次勾选多个数据集并应用到当前清单的全部组合，支持全选、恢复全局范围及后续逐行调整。
v2.6修复 IEE-MILP 扫描凸性误判、统一无漏扫覆盖率尾数，新增勾选组合的收敛曲线 JPEG 导出及指标优劣方向说明。
v2.5修复历史平台导入大规模 JSON 实验时无响应的问题：直接保存原始快照和底图，不再自动重生成全部高清图片；恢复保存的视图后再绘制结果，批量绘制入口/出口标记。
v2.4修复失败组合显示、固定滚动区域、运行中列表滚动以及大规模完整导出。导出在后台和独立进程中执行，可查看进度并取消。
本轮新增6种分割和4种规划算法，总计9种分割×7种规划，可自由组成63种组合。实现范围和预算说明见 [v2.9实现报告](UPGRADE_v2.9.md)。新模块初始未勾选，可自行勾选或“添加组合”，每行独立配置参数。
v2.2引入覆盖率定义、命名文件夹导出及历史平台升级。完整导出会要求填写实验名，自动保存到历史平台默认实验库。
新增/修正内容见 [FOLLOWUP_FIXES.md](FOLLOWUP_FIXES.md)。仓库附带可单独复制运行的 [HistoryViewer](HistoryViewer/README.md)；本机现有独立部署仍保留在上级同名英文目录。
历次界面、数据集、指标、JPEG批量导出与动态日志更新见 [CHANGELOG.md](CHANGELOG.md)。

2026-10-18版本依据三篇论文重新核对并修改代码。**可确认的原文内容、实现假设与无法严格复现的部分见 [PAPER_ALIGNMENT.md](PAPER_ALIGNMENT.md)**。不将工程改动统称为完整复刻。

源码根目录的版本名随当前交付版本同步。

## 后续版本规则

每完成一轮程序更新或修复，递增一个小版本：**2.1 → 2.2 → 2.3 → 2.4 → 2.5…**。同一轮多项改动使用同一个版本号，同步更新版本信息、更新日志及源码文件夹名。仅登记规则、查询状态或推送已有更新不另增版本；当前为2.9，后续按同一规则递增。

仅历史实验显示平台的优化与修复不递增实验主平台版本，也不改变源码根目录的版本名（2026-10-20确认）。

当前源码位置：`E:\workspace\fly\CPP Arena\CPP _Arena_v2.9`，默认图片目录随之为其下的`pictures`。数据集库和原有本地资料随源码目录保留；底图及最近工程支持从同级旧版本路径定位到新目录。独立历史实验库仍为同级`HistoryViewer/experiments`。

## 启动

Windows x64 推荐使用发布页的 `CPPArena-v2.9.exe`。首次启动需要解压内嵌运行环境，可能比后续启动稍慢；请选择有写入权限的目录。

EXE 的数据集库、工程、自动实验记录、图片和设置保存在 EXE 所在目录下的 `dataset_library`、`projects`、`experiments`、`pictures` 和 `settings.json`。升级时将新 EXE 放到原来的数据目录，或先复制这些目录；不要把尚未解压的 ZIP 当作运行目录。

便携包中的 `HistoryViewer` 是可独立运行的 Python 历史平台，仍需按其 `requirements.txt` 安装 Python 依赖，再运行 `HistoryViewer/start.bat`；主程序 EXE 不需要这些依赖。历史平台的默认实验库为其下的 `experiments`，可导入旧实验文件夹或 JSON。

从源码启动：

双击 `start.bat`，或在本目录执行：

```powershell
python main.py
```

启动脚本优先使用 `E:\anaconda\python.exe`。依赖见 `requirements.txt`。

## 使用

1. 导入 KML 支持一次选择多个文件；数据集与底图自动保存到本程序 `dataset_library`，下次启动自动恢复。后台自动加载卫星底图；通过“显示背景图”控制显隐。离线或下载失败时，日志显示原因，地块仍可使用。
2. 手动勾绘时设置画布中心经纬度与范围（米），按坐标轴与实时边长勾绘；已有尺度错误可用“尺寸校准”。
3. 为各数据集标记起飞点，设置相机参数、航高及重叠率。
4. 在“实验”页分别勾选分割与规划模块，点击“穷举组合”。可以添加、删除组合。每行参数按钮显示“默认参数”或“已修改N项”，悬停查看默认值与当前值的差异；修改仅作用于该行。
5. “统一设置所有组合的数据集”可将一次勾选应用到当前全部组合；每行“数据集”也可独立选择该组合的输入；未单独选择的行沿用当前/全部数据集范围。设置随机种子并运行，右侧实验日志显示迭代、完成与错误。
6. 画布选择组合/种子或叠加显示，查看分割、轨迹、访问顺序、绿圆入口与橙方出口；实线为区内扫描，虚线为起降和转场。点击“比较分析”在独立界面查看表格、收敛曲线和统计图。
7. 点击“完整导出实验”，填写实验名称，保存为“时间_实验名称”文件夹，包含KML、原始几何、全部已产生的结果、指标、日期/耗时、JPEG图片、相机/算法参数、日志及底图。默认直接存入历史平台的 `experiments` 实验库。
8. 历史平台已从主程序剥离。双击 `HistoryViewer/start.bat` 后自动显示默认库中的实验文件夹；外部实验用“导入实验文件夹”复制入库，旧 `.cppx/.zip/.json` 用“导入旧实验包”。本机上级目录的独立部署与仓库副本共享默认库；整份平台复制到其他位置后可独立运行。
9. “导出路线图”和“导出收敛曲线”支持勾选组合分别导出、叠加导出及一键全部导出，采用高清JPEG；比较分析里可用“数据集/结果组合”选择导出目标。图片默认保存到本程序 `pictures`。路线图在多种子时使用该组合航程最短的有效结果；收敛图汇总全部有效曲线的均值与标准差，不同目标分图。
10. “新增分割方法 / 新增路径规划算法”支持导入独立 Python 实现，或先另存接口模板；安装后的模块可与已有模块自由组合。

旧工程可加载。含原始几何和相机快照的v2.1实验包/JSON仍可导入，来源版本保留；更早的记录若缺少输入快照，无法补齐完整回放。跨电脑复盘请复制整个v2.2实验文件夹。

## 算法

实验模块可自由组合9种分割与7种规划，共63种组合。下表记录原有三种分割与三种规划的论文组合来源；新增六种分割的当前范围见 [v2.9实现报告](UPGRADE_v2.9.md)。DP默认通用转场，参数 `li_adjacency_mode=1` 使用严格论文邻接约束；通用模式是工程扩展。

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

已按用户要求移除各版本测试用例、验证脚本、测试输出及测试缓存，保留程序源码和实际实验记录。`verification/sync_history_runtime.py` 为独立历史平台的运行库同步工具，继续保留。历史升级说明中的验证结果为当时的执行记录。论文对齐细节和未解决的原文歧义见 [PAPER_ALIGNMENT.md](PAPER_ALIGNMENT.md)。

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

## 构建 Windows EXE

在 Windows x64、已安装 `requirements.txt` 依赖和 PyInstaller 的 Python 环境中执行：

```powershell
python -m PyInstaller --noconfirm CPPArena.spec
```

产物为 `dist/CPPArena-v2.9.exe`。构建配置包含 CGAL 原生DLL、投影数据和程序资源，示例只收录仓库自带KML；不收录本机数据集库、工程或实验记录。原生库源码、固定参考版本及重建步骤见 [algorithms/native/README.md](algorithms/native/README.md)。
