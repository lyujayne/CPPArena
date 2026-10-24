# 历史平台运行库同步

各版本测试用例、验证脚本、测试输出和测试缓存已按用户要求清理。

保留 `sync_history_runtime.py`：同步仓库内独立 `HistoryViewer` 的共享显示代码；存在上级同名部署时也同步其运行库。这是程序维护工具，不会运行算法实验或测试。

在源码根目录运行：

```powershell
python verification/sync_history_runtime.py
```
