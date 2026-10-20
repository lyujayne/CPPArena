# 源码验证

在仓库根目录运行 `python -m pytest -q -p no:cacheprovider`，覆盖算法、界面、统计、导出及独立历史平台。

- `verify_workflow_v21.py` 保留v2.1界面、真实路线JPEG、批量导出示例与实验摘要的验收流程，输出到 `verification/review`。
- `verify_v22.py` 验证覆盖率和非零漏扫、实际命名对话框、完整文件夹导出及历史平台回放，输出到 `verification/v2.2`，使用隔离验收库。
- `verify_v24.py` 验证固定区域、运行中滚动、失败列标红及324条记录（24次真实成功运行、300条模拟失败）的后台完整导出，包含48张高清JPEG，输出到`verification/v2.4`，使用隔离实验库。
- `verify_followup_ui.py` 和 `verify_v21.py` 保留前几轮验收流程。
- `sync_history_runtime.py` 同步仓库内独立 `HistoryViewer` 的共享显示代码；存在本机上级同名部署时也同步其运行库。历史窗口本身由独立平台维护，主程序不导入该窗口或调用它运行算法。

生成的截图、实验结果、临时数据集库及缓存不提交。正常使用产生的数据集库、图片、工程、实验记录、构建产物与日志也保留在本地。

## v2.3 新增算法验收

`python verification/verify_v23.py`：真实运行新增规划、查看分割与组合界面、导出四张JPEG路线图、完整实验文件夹，并在独立历史平台回放。产物在`verification/v2.3`，验收数据集库和实验库隔离，不写用户默认库。所有63种组合及几何/目标函数核验由`test_upgrade_v23.py`覆盖。
