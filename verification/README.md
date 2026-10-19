# 源码验证

在仓库根目录运行 `python -m pytest -q -p no:cacheprovider`，覆盖算法、界面、统计、导出及独立历史平台。

- `verify_workflow_v21.py` 生成最新界面截图、真实路线 JPEG、批量导出示例与实验摘要，输出到 `verification/review`。
- `verify_followup_ui.py` 和 `verify_v21.py` 保留前几轮验收流程。
- `sync_history_runtime.py` 同步仓库内独立 `HistoryViewer` 的共享显示代码；存在本机上级同名部署时也同步其运行库。历史窗口本身由独立平台维护，主程序不导入该窗口或调用它运行算法。

生成的截图、实验结果、临时数据集库及缓存不提交。正常使用产生的数据集库、图片、工程、实验记录、构建产物与日志也保留在本地。
