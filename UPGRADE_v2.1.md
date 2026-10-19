# CPP Arena 2.1 升级与验收

后续源码修正以 [FOLLOWUP_FIXES.md](FOLLOWUP_FIXES.md) 为准；本次未重新打包 exe。

依据：用户提供的 `E:/workspace/fly/UPGRADE_PLAN_v1.8.md`，版本号按用户要求升级为 **2.1**。

## 程序入口

- 主程序：`dist/CPPArena-v2.1.exe`，或 `python main.py`。
- 独立历史平台：上级英文目录 `HistoryViewer/start.bat`。主程序源码不再包含历史平台或 `--history` 模式。
- 未覆盖旧版本 exe，源码目录名称保持原样。

## 功能对应

| 要求 | v2.1 实现 | 验证 |
|---|---|---|
| FR-1 分割/规划拆分 | 独立组件目录；三种分割 × 三种规划 | 9 种搭配均用真实独立进程求解成功 |
| FR-2 穷举与增删 | 穷举、手工添加、删除所选；重复搭配有独立编号 | 删除后只执行最终清单；重复搭配不会混合结果 |
| FR-3 独立参数 | 每行参数对话框；分割与规划参数分开保存；未设置使用默认值 | 默认值、参数隔离、工程序列化测试 |
| FR-4 实验日志 | 左侧实验日志含动态迭代行、持续进度记录、完成与错误事件 | 迭代进度、切换任务、失败继续、取消、界面响应测试 |
| FR-5 完整导出 | `.cppx` ZIP 包：全部运行、原始地块、分割、轨迹、KML、CSV、PNG、指标、相机/算法参数、时间、日志和底图 | 9 个运行各含完整文件；底图移除后仍能从包内还原 |
| FR-6 独立历史平台 | 独立启动、实验库、多文件导入、文件夹扫描；复用主程序画布、指标和比较组件 | 禁止调用分割/规划函数的测试中仍可逐组合回放 |
| FR-7 背景图 | 删除手动卫星按钮；导入 KML 后线程自动加载；显隐开关 | 通过下载桩验证导入、线程、显示和隐藏；网络服务实连未纳入自动验收 |
| FR-8 选择分解对比 | 打开比较前勾选参与的分割方法，避免同一分割重复列出 | 界面选择入口及原分割实现复用 |
| FR-9 米制勾绘 | 设置中心经纬度与可见范围；米制轴、实时坐标/边长；等比尺寸校准及运行前检查 | 小尺度识别、校准、非法几何、工程回读测试 |
| FR-10 UI | 主程序和历史平台统一样式、字体、控件；可滚动清单与路径显隐，组合/种子选择器 | Qt 窗口启动与截图检查 |

## 实验包结构

```text
experiment.json          完整输入/结果/组合/种子/视图快照
metrics.csv / .json      评价指标、实验时间、运行耗时和错误
experiment.log           运行日志
assets/                  包内底图
runs/dN_cN_rN/
  result.json            该运行的全部结果及元数据
  segmentation.json      米制分割几何、原始地块及 EPSG
  segmentation.kml       地理坐标分割多边形
  waypoints.kml / .csv    航点、路径与飞行高度
  trajectory.png         路径规划轨迹图
  segmentation.png       图形分割结果图
```

失败任务保存错误、参数、时间和输入，不生成虚假的 KML/轨迹。终止实验保留已完成结果与原计划组合/种子。
导出采用临时文件写完后替换，导出失败不会破坏已有文件。回放直接绘制保存的轨迹/分割，不调用算法，不请求卫星服务。
本机自动 JSON 历史保存原底图路径；跨电脑或长期归档请导出完整实验包。

## 验证命令

```powershell
python -m pytest test_upgrade_v21.py test_paper_alignment.py test_responsiveness.py -q -p no:cacheprovider
python test_li_dp.py
python test_fa3aco.py
```

新增验证使用缩短的迭代预算检验全部组合、独立参数和数据流；正式默认的 PSO 120 代、ACO/FA3ACO 500 代保持原值。
Li-DP 的子区上限、邻接遍历约束，以及论文实现的已有边界见 `PAPER_ALIGNMENT.md`。不满足规划前提的组合会记录错误并继续执行下一任务，不自动更换算法。

## 构建

```powershell
python -m PyInstaller --noconfirm --workpath build/v21 CPPArena.spec
```

发行文件名为 `CPPArena-v2.1.exe`，Windows 文件版本为 `2.1.0.0`。
