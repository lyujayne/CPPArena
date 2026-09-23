# -*- coding: utf-8 -*-
"""算法注册表：插件扫描 + 手动注册。

新算法放入 algorithms/plugins/ 目录（.py 文件、类名为 BaseCPPAlgorithm
的子类且具有 name 属性）即被自动识别，无需修改平台核心代码。
"""
import importlib
import importlib.util
import inspect
import logging
import os
import traceback

from core.base_algorithm import BaseCPPAlgorithm

logger = logging.getLogger(__name__)


class AlgorithmRegistry:
    """全局算法注册表单例。"""

    _instance = None

    def __init__(self):
        self._algorithms: dict = {}      # name -> 算法类
        self._plugin_dirs: list = []
        self._builtins_loaded = False

    @classmethod
    def instance(cls) -> "AlgorithmRegistry":
        if cls._instance is None:
            cls._instance = AlgorithmRegistry()
        return cls._instance

    # ---------------- 注册 ----------------
    def register(self, algo_cls) -> type:
        """注册一个算法类（也可用作装饰器）。"""
        if not (inspect.isclass(algo_cls) and issubclass(algo_cls, BaseCPPAlgorithm)):
            raise TypeError("只能注册 BaseCPPAlgorithm 的子类")
        name = getattr(algo_cls, "name", None)
        if not name:
            raise ValueError("算法类必须定义 name 属性")
        self._algorithms[name] = algo_cls
        logger.info("已注册算法: %s", name)
        return algo_cls

    def register_class(self, algo_cls) -> type:
        return self.register(algo_cls)

    # ---------------- 查询 ----------------
    def get(self, name: str):
        return self._algorithms.get(name)

    def get_instance(self, name: str) -> BaseCPPAlgorithm:
        cls = self._algorithms.get(name)
        if cls is None:
            raise KeyError(f"算法未注册: {name}")
        return cls()

    def all(self) -> dict:
        return dict(self._algorithms)

    def names(self) -> list:
        return list(self._algorithms.keys())

    def meta(self, name: str) -> dict:
        cls = self._algorithms.get(name)
        if cls is None:
            return {}
        return {
            "name": name,
            "display_name": getattr(cls, "display_name", name),
            "description": getattr(cls, "description", ""),
            "author": getattr(cls, "author", ""),
            "citation": getattr(cls, "citation", ""),
            "scope": getattr(cls, "scope", ""),
            "params_note": getattr(cls, "params_note", ""),
            "default_params": dict(getattr(cls, "default_params", {})),
            "deterministic": bool(getattr(cls, "deterministic", False)),
        }

    # ---------------- 内置算法加载 ----------------
    def load_builtins(self):
        """导入 algorithms 包，触发内置算法注册。"""
        if self._builtins_loaded:
            return
        try:
            import algorithms  # noqa: F401   （__init__ 中导入各内置算法）
            import algorithms.aco  # noqa: F401
            self._builtins_loaded = True
        except Exception:
            logger.error("内置算法加载失败:\n%s", traceback.format_exc())
            raise

    # ---------------- 插件发现 ----------------
    def add_plugin_dir(self, path: str):
        if os.path.isdir(path) and path not in self._plugin_dirs:
            self._plugin_dirs.append(path)

    def discover_plugins(self, dirs=None) -> list:
        """扫描插件目录中的 .py 文件并注册其中的算法类。返回新注册的算法名。"""
        if dirs is None:
            dirs = self._plugin_dirs
        found = []
        for d in dirs:
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".py") or fn.startswith("_"):
                    continue
                mod_name = f"_cpp_arena_plugin_{os.path.splitext(fn)[0]}"
                try:
                    spec = importlib.util.spec_from_file_location(
                        mod_name, os.path.join(d, fn))
                    if spec is None or spec.loader is None:
                        continue
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    for _, obj in vars(mod).items():
                        if (inspect.isclass(obj) and obj is not BaseCPPAlgorithm
                                and issubclass(obj, BaseCPPAlgorithm)
                                and getattr(obj, "name", None)):
                            self.register(obj)
                            found.append(obj.name)
                except Exception:
                    logger.error("插件 %s 加载失败:\n%s", fn, traceback.format_exc())
        return found

    def refresh(self) -> list:
        """重新加载：清空插件算法（保留内置），重新扫描。"""
        builtin = self._algorithms
        self.load_builtins()
        # 插件目录默认
        from config.default_params import PLUGIN_DIR
        self.add_plugin_dir(PLUGIN_DIR)
        return self.discover_plugins()


# 模块级便捷接口
_registry = AlgorithmRegistry()


def register(algo_cls=None):
    """装饰器：@register 或 @register() 注册算法类。"""
    if algo_cls is None:
        return lambda cls: AlgorithmRegistry.instance().register(cls)
    return AlgorithmRegistry.instance().register(algo_cls)


def get_registry() -> AlgorithmRegistry:
    return AlgorithmRegistry.instance()
