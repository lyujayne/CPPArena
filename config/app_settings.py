# -*- coding: utf-8 -*-
"""全局设置（主题、插件目录、最近工程、导出参数），JSON 持久化。

非功能需求「数据安全 / 易用性」：设置本地存储于 settings.json，
工程文件可完整保存/加载（见 data.dataset.Project）。
"""
import json
import os

from config.default_params import BASE_DIR, PLUGIN_DIR

SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")

DEFAULT_SETTINGS = {
    "theme": "默认",
    "plugin_dir": PLUGIN_DIR,
    "recent_projects": [],      # 最近打开的工程文件路径
    "max_recent": 5,
    "export_dpi": 300,          # 矢量图导出 dpi（PNG 300dpi 满足期刊要求）
    "auto_save_record": True,   # 每次实验自动落盘 JSON 实验记录
}


class AppSettings:
    """全局设置单例。"""

    _instance = None

    def __init__(self):
        self.data = dict(DEFAULT_SETTINGS)
        self.load()

    @classmethod
    def instance(cls) -> "AppSettings":
        if cls._instance is None:
            cls._instance = AppSettings()
        return cls._instance

    # ---------------- 持久化 ----------------
    def load(self):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                self.data.update({k: v for k, v in saved.items()
                                  if k in DEFAULT_SETTINGS})
        except Exception:
            pass

    def save(self):
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------------- 读写 ----------------
    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value):
        self.data[key] = value
        self.save()

    # ---------------- 最近工程 ----------------
    def add_recent_project(self, path: str):
        rec = self.data.setdefault("recent_projects", [])
        if path in rec:
            rec.remove(path)
        rec.insert(0, path)
        self.data["recent_projects"] = rec[:self.data.get("max_recent", 5)]
        self.save()
