# 独立算法组件

在“实验”页点击“新增分割方法”或“新增路径规划算法”，选择实际实现的 `.py` 文件。需要接口示例时，在对话框中点击“另存接口模板”，修改函数实现后导入。

安装后的文件分别保存在 `decomposition/` 和 `planning/`。重启主程序及后台计算进程会自动发现，损坏或不符合接口的文件会记录到实验日志。界面只导入实现，不会根据名字自动生成算法。

最小分割实现：

```python
MODULE_KIND = 'decomposition'
MODULE_ID = 'my_split'
MODULE_NAME = '我的分割方法'
DEFAULT_PARAMS = {}

def decompose(vertices, params, seed):
    # 替换为自己的凸分割实现，返回 (pieces, metadata)。
    from algorithms.aco.polygon_decomp import convex_decompose
    return convex_decompose(vertices, seed=seed), {'segmentation': MODULE_NAME}
```

规划接口、参数、返回结构、单文件导入限制与操作方法见上级 [WORKFLOW_v2.1.md](../WORKFLOW_v2.1.md)。上述示例仅复用内置分割，不代表新的科学算法。
