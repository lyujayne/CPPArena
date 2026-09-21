# 插件目录说明（README for plugin authors）

将新的覆盖路径规划算法写入本目录即可被平台自动识别，无需修改平台核心代码。

## 编写方法

复制 `horizontal_scan.py` 并修改：

```python
from core.base_algorithm import BaseCPPAlgorithm, CPPInput, CPPResult

class MyAlgorithm(BaseCPPAlgorithm):
    name = "我的算法"              # 唯一标识（注册名）
    display_name = "我的算法（说明）"
    description = "算法描述（自动生成论文素材）"
    default_params = {"seed": 42, "param_a": 1.0}   # 参数表单自动生成

    def solve(self, cpp_input: CPPInput, **params) -> CPPResult:
        # cpp_input.regions        : 区域列表（Region，vertices 为 UTM 米制坐标）
        # cpp_input.launch_point   : 起飞点 (x, y)
        # cpp_input.camera         : 相机参数（line_spacing 为航线间距）
        # 返回统一结果结构 CPPResult（含 waypoints / total_distance / ...）
        ...
        return CPPResult(waypoints=..., total_distance=..., total_turns=...,
                         region_order=..., internal_paths=...)
```

## 要求

1. 类必须继承 `BaseCPPAlgorithm` 并实现 `solve()`；
2. 类必须定义 `name` 属性（唯一）；
3. 文件以 `.py` 结尾且不以 `_` 开头；
4. 所有坐标使用 UTM 平面米制；多随机种子运行时应遵循传入的 `seed` 参数以保证可复现。
