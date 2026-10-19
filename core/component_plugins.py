"""Install separately selectable decomposition and route-planning implementations."""
import hashlib
import importlib.util
import math
import os
from pathlib import Path
import re
import shutil
import sys

from config.default_params import COMPONENT_DIR


def component_directory():
    return Path(os.environ.get('CPP_ARENA_COMPONENT_DIR', COMPONENT_DIR))


def read_component(path, expected_kind=None):
    path = Path(path).resolve()
    name = '_cpp_component_' + hashlib.sha256(str(path).encode()).hexdigest()[:20]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError('无法读取 Python 组件文件')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    # Read source directly: replacing an implementation within one filesystem
    # timestamp must not execute stale bytecode with a new recorded source hash.
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    kind = getattr(module, 'MODULE_KIND', None)
    if kind not in ('decomposition', 'planning') or (expected_kind and kind != expected_kind):
        raise ValueError('MODULE_KIND 必须与分割/规划入口对应')
    key = getattr(module, 'MODULE_ID', '')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', key):
        raise ValueError('MODULE_ID 须以英文字母开头，仅使用字母、数字、下划线或短横线，最多64字符')
    if not callable(getattr(module, 'decompose' if kind == 'decomposition' else 'plan', None)):
        raise ValueError('分割组件须提供 decompose(vertices, params, seed)；规划组件须提供 plan(nodes, params, seed)')
    defaults = getattr(module, 'DEFAULT_PARAMS', {})
    if not isinstance(defaults, dict) or any(not isinstance(k, str) or not isinstance(v, (int, float))
                                            or not math.isfinite(v) for k, v in defaults.items()):
        raise ValueError('DEFAULT_PARAMS 须为参数名到有限整数/小数的字典')
    if not isinstance(getattr(module, 'PARAM_LABELS', {}), dict):
        raise ValueError('PARAM_LABELS 须为参数名到标签的字典')
    return module


def register_component(module, path):
    from core.combinations import DECOMPOSITIONS, PLANNERS
    catalog = DECOMPOSITIONS if module.MODULE_KIND == 'decomposition' else PLANNERS
    key = module.MODULE_ID
    if key in catalog and not getattr(catalog[key][1], 'component_plugin', False):
        raise ValueError('组件编号与内置模块冲突：' + key)

    class Adapter:
        component_plugin = True
        default_params = dict(getattr(module, 'DEFAULT_PARAMS', {}))
        source_path = str(Path(path).resolve())
        source_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()

        def get_param_spec(self):
            labels = getattr(module, 'PARAM_LABELS', {})
            return [(k, labels.get(k, k), 'int' if isinstance(v, int) else 'float', v)
                    for k, v in self.default_params.items() if k != 'seed']

        def decompose_region(self, vertices, params):
            return module.decompose(vertices, dict(params), int(params.get('seed', 42)))

        def solve_region_order(self, nodes, params, seed):
            return module.plan(nodes, dict(params), seed)

        def plan_subregion(self, vertices, line_spacing):
            mode = getattr(self, '_scan_boundary_mode', 'inside')
            custom = getattr(module, 'make_scan_plans', None)
            if custom:
                return custom(vertices, line_spacing, mode)
            from algorithms.aco.boustrophedon import plan_region_variants
            return plan_region_variants(vertices, line_spacing, boundary_mode=mode)

    catalog[key] = (str(getattr(module, 'MODULE_NAME', key)), Adapter)
    return key


def load_component_plugins():
    errors = []
    root = component_directory()
    for kind in ('decomposition', 'planning'):
        for path in sorted((root / kind).glob('*.py')):
            if path.name.startswith('_'):
                continue
            try:
                register_component(read_component(path, kind), path)
            except Exception as exc:
                errors.append(f'{path.name}：{exc}')
    return errors


def install_component(source, kind):
    source = Path(source).resolve()
    module = read_component(source, kind)
    # Check built-in conflicts before saving anything to the component library.
    from core.combinations import DECOMPOSITIONS, PLANNERS
    catalog = DECOMPOSITIONS if kind == 'decomposition' else PLANNERS
    if module.MODULE_ID in catalog and not getattr(catalog[module.MODULE_ID][1], 'component_plugin', False):
        raise ValueError('编号与内置组件冲突，请修改 MODULE_ID')
    destination = component_directory() / kind / (module.MODULE_ID + '.py')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source != destination.resolve():
        shutil.copy2(source, destination)
    return register_component(read_component(destination, kind), destination)


def component_template(kind):
    if kind == 'decomposition':
        return '''# 修改 MODULE_ID / MODULE_NAME，并用自己的分割实现替换函数体。
MODULE_KIND = "decomposition"
MODULE_ID = "custom_decomposition"
MODULE_NAME = "自定义分割示例（请替换实现）"
DEFAULT_PARAMS = {}
PARAM_LABELS = {}

def decompose(vertices, params, seed):
    from algorithms.aco.polygon_decomp import convex_decompose
    # 返回 (凸子区顶点列表, 描述字典)；程序会验证覆盖完整性和重叠。
    return convex_decompose(vertices, seed=seed), {"segmentation": MODULE_NAME}
'''
    return '''# 修改 MODULE_ID / MODULE_NAME，并用自己的规划实现替换函数体。
MODULE_KIND = "planning"
MODULE_ID = "custom_planning"
MODULE_NAME = "自定义规划示例（请替换实现）"
DEFAULT_PARAMS = {"max_iterations": 100, "alpha": .5, "beta": 20., "rho": .7, "Q": 1., "tau0": 1., "exploration_prob": .1}
PARAM_LABELS = {"max_iterations": "最大迭代次数"}

def plan(nodes, params, seed):
    from algorithms.aco.aco_gtsp import solve_aco_gtsp
    # 返回 (选中的节点索引序列, 收敛列表, 统计字典)，每个子区恰好选一个节点。
    return solve_aco_gtsp(nodes, params=params, seed=seed)
'''
