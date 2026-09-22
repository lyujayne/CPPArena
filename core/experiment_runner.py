# -*- coding: utf-8 -*-
"""实验调度层：批量运行、随机种子管理、超时控制、进度回调。

以纯线程方式实现（不依赖 Qt），便于 GUI 通过 QThread 包装异步运行。
"""
import random
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np

from core.base_algorithm import CPPInput
from core.registry import AlgorithmRegistry
from data.dataset import Dataset

ProgressCB = Callable[[int, int, str], None]  # (done, total, message)


@dataclass
class ExperimentJob:
    """一次单算法单数据集单种子运行。"""
    algorithm: str
    dataset: Dataset
    seed: int
    params: dict = field(default_factory=dict)
    camera: dict = field(default_factory=dict)   # 全局相机参数（公平比较）
    index: int = 0

    def key(self) -> tuple:
        return (self.algorithm, self.dataset.name, self.seed)


class ExperimentRunner:
    """实验调度器：支持取消、超时、进度回调。"""

    def __init__(self, registry: Optional[AlgorithmRegistry] = None):
        self.registry = registry or AlgorithmRegistry.instance()
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._timeout_per_job: Optional[float] = None

    # ---------------- 任务构造 ----------------
    @staticmethod
    def build_jobs(algorithm_names: List[str], datasets: List[Dataset],
                   seeds: List[int], mode: str = "batch",
                   active_dataset: Optional[Dataset] = None,
                   params_by_algo: Optional[Dict[str, dict]] = None,
                   camera: Optional[dict] = None
                   ) -> List[ExperimentJob]:
        """按模式构造任务列表。

        - single: 每个算法 × 活动数据集 × 第 1 个种子
        - repeated: 每个算法 × 活动数据集 × 全部种子
        - batch: 每个算法 × 全部数据集 × 全部种子
        """
        jobs = []
        if mode == "batch":
            ds_list = datasets
        else:
            ds_list = [active_dataset] if active_dataset else []
        seeds_list = seeds if mode in ("repeated", "batch") else seeds[:1]
        for ds in ds_list:
            if ds is None:
                continue
            for algo in algorithm_names:
                for sd in seeds_list:
                    p = dict((params_by_algo or {}).get(algo, {}))
                    p.setdefault("seed", sd)
                    jobs.append(ExperimentJob(
                        algorithm=algo, dataset=ds, seed=sd, params=p,
                        camera=dict(camera or {})))
        return jobs

    # ---------------- 运行 ----------------
    def run_jobs(self, jobs: List[ExperimentJob],
                 progress: Optional[ProgressCB] = None,
                 stop_requested: Optional[Callable[[], bool]] = None
                 ) -> Dict[str, Dict[str, List[dict]]]:
        """顺序执行任务。

        :return: {dataset_name: {algo_name: [run_dict, ...]}}
        """
        self._cancel.clear()
        results: Dict[str, Dict[str, List[dict]]] = {}
        total = len(jobs)
        for idx, job in enumerate(jobs):
            if self._cancel.is_set() or (stop_requested and stop_requested()):
                break
            t_start = time.perf_counter()
            if progress:
                progress(idx, total, f"运行 {job.algorithm} @ {job.dataset.name} (seed={job.seed})")
            try:
                run_dict = self._run_single(job)
                run_dict["elapsed_total"] = round(time.perf_counter() - t_start, 3)
            except Exception as e:
                run_dict = {
                    "algorithm": job.algorithm, "seed": job.seed,
                    "error": f"{type(e).__name__}: {e}",
                    "traceback": traceback.format_exc(),
                    "total_distance": float("nan"), "total_turns": -1,
                    "runtime": 0.0, "convergence": [],
                }
            results.setdefault(job.dataset.name, {}).setdefault(job.algorithm, []).append(run_dict)
            if progress:
                progress(idx + 1, total, "完成" if "error" not in run_dict else f"失败: {run_dict['error']}")
        return results

    def _run_single(self, job: ExperimentJob) -> dict:
        algo = self.registry.get_instance(job.algorithm)
        from core.base_algorithm import CameraParams
        cam = CameraParams.from_dict(job.camera) if job.camera else CameraParams()
        cpp_input = CPPInput(
            regions=job.dataset.regions,
            launch_point=job.dataset.launch_point or (0.0, 0.0),
            camera=cam,
        )

        # 保证复现：全局种子重置
        random.seed(job.seed)
        np.random.seed(job.seed)

        result = algo.solve(cpp_input, **job.params)
        from compare.metrics import summarize_run
        run_dict = summarize_run(result)
        run_dict["dataset"] = job.dataset.name
        run_dict["convergence"] = list(result.convergence or [])
        run_dict["waypoints"] = result.waypoints
        run_dict["region_order"] = result.region_order
        run_dict["internal_paths"] = result.internal_paths
        run_dict["subregion_sequence"] = result.subregion_sequence
        run_dict["metadata"] = result.metadata
        run_dict["params"] = {k: v for k, v in job.params.items() if k != "seed"}
        return run_dict

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()
