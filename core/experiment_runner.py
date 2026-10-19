# -*- coding: utf-8 -*-
"""实验调度层：批量运行、随机种子管理、超时控制、进度回调。

GUI使用独立spawn进程运行每个任务，QThread只协调消息和生命周期。
保留进程内接口用于脚本；两种接口均支持阶段进度、取消和超时。
"""
import random
import multiprocessing
import os
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np

from core.base_algorithm import CPPInput
from core.registry import AlgorithmRegistry
from data.dataset import Dataset
from core.execution_control import execution_context, ExperimentCancelled

ProgressCB = Callable[[int, int, str], None]  # (done, total, message)
_spawn_lock = threading.Lock()


def _run_isolated_job(job, plugin_dirs, connection, cancelled, timeout):
    """Top-level spawn target: never import or manipulate Qt widgets."""
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.windll.kernel32
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            kernel.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel.SetPriorityClass.restype = wintypes.BOOL
            try:
                kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x00004000)
            except OSError:
                pass  # Optional scheduling hint; isolation still works.
        registry = AlgorithmRegistry.instance()
        registry.load_builtins()
        for directory in plugin_dirs:
            registry.add_plugin_dir(directory)
        registry.refresh()
        runner = ExperimentRunner(registry)
        with execution_context(cancelled.is_set,
                lambda message: connection.send(('progress', message)), timeout):
            result = runner._run_single(job)
        result.setdefault('metadata', {})['execution'] = {
            'worker_pid': os.getpid(), 'backend': 'spawn-process'}
        connection.send(('result', result))
    except ExperimentCancelled:
        connection.send(('cancelled', None))
    except Exception as exc:
        connection.send(('error', (f'{type(exc).__name__}: {exc}', traceback.format_exc())))
    finally:
        connection.close()


def _start_process(process):
    # Small matrix operations should not start a large BLAS thread pool.
    # Only the spawned child's environment inherits these limits.
    keys = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')
    with _spawn_lock:
        previous = {key: os.environ.get(key) for key in keys}
        try:
            os.environ.update({key: '1' for key in keys})
            process.start()
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _failed_run(job, error, trace=''):
    return {'algorithm': job.algorithm, 'seed': job.seed, 'dataset': job.dataset.name,
            'error': error, 'traceback': trace, 'total_distance': float('nan'),
            'total_turns': -1, 'runtime': 0., 'convergence': []}


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
    def prepare(self):
        """Called on the UI thread before starting the coordinator thread."""
        self._cancel.clear()

    def run_jobs_isolated(self, jobs, progress=None, stop_requested=None, reset_cancel=True):
        if reset_cancel:
            self.prepare()
        context = multiprocessing.get_context('spawn')
        results = {}
        total = len(jobs)
        stopping = lambda: self._cancel.is_set() or bool(stop_requested and stop_requested())
        for index, job in enumerate(jobs):
            if stopping():
                break
            label = f'{job.algorithm} @ {job.dataset.name} (seed={job.seed})'
            if progress:
                progress(index, total, '启动计算进程：'+label)
            receive, send = context.Pipe(duplex=False)
            cancelled = context.Event()
            process = context.Process(target=_run_isolated_job,
                args=(job, list(self.registry._plugin_dirs), send, cancelled, self._timeout_per_job),
                name='CPP-'+job.algorithm, daemon=True)
            started = time.monotonic()
            value, stage, last_update = None, '启动/导入算法', 0.
            try:
                _start_process(process)
                send.close()
                while True:
                    if stopping():
                        cancelled.set()
                        break
                    elapsed = time.monotonic()-started
                    if self._timeout_per_job is not None and elapsed >= self._timeout_per_job:
                        cancelled.set()
                        value = _failed_run(job, 'TimeoutError: 当前算法超过运行时间上限')
                        break
                    if receive.poll(.05):
                        try:
                            kind, payload = receive.recv()
                        except EOFError:
                            value = _failed_run(job, f'计算进程意外退出（exitcode={process.exitcode}）')
                            break
                        if kind == 'progress':
                            stage = payload
                            if progress:
                                progress(index, total, f'{label}：{stage}，已用 {elapsed:.1f}s')
                                last_update = time.monotonic()
                        elif kind == 'result':
                            value = payload
                            break
                        elif kind == 'error':
                            value = _failed_run(job, *payload)
                            break
                        elif kind == 'cancelled':
                            break
                    elif not process.is_alive():
                        value = _failed_run(job, f'计算进程意外退出（exitcode={process.exitcode}）')
                        break
                    now = time.monotonic()
                    if progress and now-last_update >= .2:
                        progress(index, total, f'{label}：{stage}，已用 {elapsed:.1f}s')
                        last_update = now
            finally:
                send.close()
                if process.pid is not None:
                    process.join(.25)
                    if process.is_alive():
                        process.terminate()
                        process.join(1.)
                    if process.is_alive():
                        process.kill()
                        process.join(1.)
                    process.close()
                receive.close()
            if stopping():
                break
            if value is None:
                value = _failed_run(job, '计算任务被终止，未返回完整结果')
            value['elapsed_total'] = round(time.monotonic()-started, 3)
            results.setdefault(job.dataset.name, {}).setdefault(job.algorithm, []).append(value)
            if progress:
                progress(index+1, total, label+('：完成' if 'error' not in value else '：'+value['error']))
        return results

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
                with execution_context(
                        lambda: self._cancel.is_set() or bool(stop_requested and stop_requested()),
                        (lambda message: progress(idx, total, f'{job.algorithm}：{message}')) if progress else None,
                        self._timeout_per_job):
                    run_dict = self._run_single(job)
                run_dict["elapsed_total"] = round(time.perf_counter() - t_start, 3)
            except ExperimentCancelled:
                break
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

        effective_params = dict(algo.default_params, **job.params)
        result = algo.solve(cpp_input, **effective_params)
        from compare.metrics import summarize_run
        run_dict = summarize_run(result)
        run_dict["dataset"] = job.dataset.name
        run_dict["convergence"] = list(result.convergence or [])
        run_dict["waypoints"] = result.waypoints
        run_dict["region_order"] = result.region_order
        run_dict["internal_paths"] = result.internal_paths
        run_dict["subregion_sequence"] = result.subregion_sequence
        run_dict["metadata"] = result.metadata
        run_dict["params"] = {k: v for k, v in effective_params.items() if k != "seed"}
        return run_dict

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()
