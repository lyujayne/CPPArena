# -*- coding: utf-8 -*-
"""实验记录落盘：每次实验自动保存为 JSON 实验记录，形成历史库。"""
import datetime
import json
import os
from typing import Dict, List, Optional

from config.default_params import EXPERIMENT_DIR


def _ts() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class ExperimentRecorder:
    """实验历史库（JSON 文件）。"""

    def __init__(self, base_dir: str = EXPERIMENT_DIR):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def save_record(self, project_name: str, camera: dict,
                    seeds: List[int], mode: str,
                    results: Dict[str, Dict[str, List[dict]]],
                    meta: Optional[dict] = None) -> str:
        """保存一次实验记录，返回记录文件路径。"""
        record = {
            "id": _ts(),
            "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "project": project_name,
            "mode": mode,
            "camera": camera,
            "seeds": seeds,
            "algorithms": sorted({a for ds in results.values() for a in ds}),
            "datasets": list(results.keys()),
            "results": results,
            "meta": meta or {},
        }
        path = os.path.join(self.base_dir, f"experiment_{record['id']}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        return path

    def list_records(self) -> List[dict]:
        out = []
        for fn in sorted(os.listdir(self.base_dir)):
            if not fn.endswith(".json"):
                continue
            p = os.path.join(self.base_dir, fn)
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                out.append({
                    "id": d.get("id"), "path": p,
                    "saved_at": d.get("saved_at"),
                    "project": d.get("project"),
                    "mode": d.get("mode"),
                    "algorithms": d.get("algorithms", []),
                    "datasets": d.get("datasets", []),
                })
            except Exception:
                continue
        return out

    def load_record(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
