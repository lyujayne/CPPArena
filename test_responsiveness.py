"""Real spawn-process, cancellation and GUI responsiveness regressions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import multiprocessing
import time

import pytest
from core.base_algorithm import CameraParams
from core.execution_control import checkpoint, execution_context, ExperimentCancelled
from core.experiment_runner import ExperimentJob, ExperimentRunner
from core.registry import get_registry
from data.dataset import Dataset


def dataset():
    value = Dataset('responsiveness')
    value.add_region('U', [(0, 0), (300, 0), (300, 300), (220, 300),
                          (220, 90), (80, 90), (80, 300), (0, 300)])
    value.launch_point = (-60, -60)
    return value


def runner():
    registry = get_registry()
    registry.load_builtins()
    return ExperimentRunner(registry)


def test_force_reports_transition_and_terminal_progress():
    seen = []
    with execution_context(lambda: False, seen.append):
        checkpoint('PSO区域分割', 117, 120, force=True)
        checkpoint('PSO区域分割', 120, 120, force=True)
        checkpoint('FA3ACO迭代', 1, 500, force=True)
    assert seen == ['PSO区域分割 117/120', 'PSO区域分割 120/120', 'FA3ACO迭代 1/500']


def test_zero_heuristic_weight_has_no_nan_candidates():
    import numpy as np
    from algorithms.aco.aco_gtsp import transition_log_scores, probabilities_from_logs
    costs = np.array([[np.inf, 0., 2.], [0., np.inf, 3.], [2., 3., np.inf]])
    with np.errstate(invalid='raise'):
        logs = transition_log_scores(np.ones((3, 3)), costs, 0., 0.)
    assert np.isneginf(np.diag(logs)).all()
    assert np.allclose(probabilities_from_logs(logs[0, [1, 2]]), [.5, .5])


def test_failed_algorithm_does_not_break_result_charts(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from gui.compare_panel import ComparePanel
    from gui.result_panel import ResultPanel
    from compare.statistics import build_comparison_table
    app = QApplication.instance() or QApplication([])
    failed = {'algorithm': 'Enhanced-ECD-DP', 'error': '21个子区超过精确DP上限16',
              'total_distance': float('nan'), 'total_turns': -1, 'runtime': 0.}
    good = {'algorithm': 'ACO-GTSP', 'total_distance': 100., 'total_turns': 4,
            'runtime': .1, 'convergence': [110., 100.]}
    raw = {'ACO-GTSP': [good], 'Enhanced-ECD-DP': [failed]}
    table = build_comparison_table(raw)
    assert table.loc['总距离均值 (m)', 'ACO-GTSP'] == 100
    panel = ComparePanel()
    panel.set_data({'responsiveness': raw}, [dataset()], {}, None)
    assert '21个子区' in panel.failure_label.text()
    assert list(panel._active_runs()) == ['ACO-GTSP']
    detail = ResultPanel()
    detail.show_run(failed)
    assert detail.lbl_objective.text() == '运行失败'
    assert '21个子区' in detail.detail.toPlainText()


def test_execution_context_cancel_and_deadline():
    with pytest.raises(ExperimentCancelled):
        with execution_context(lambda: True):
            pass
    with pytest.raises(TimeoutError):
        with execution_context(lambda: False, timeout=0):
            pass


def test_all_four_algorithms_in_separate_processes_and_progress():
    run = runner()
    ds = dataset()
    params = {'max_iterations': 3, 'ants_count': 4,
              'pso_iterations': 4, 'pso_swarm_size': 10}
    names = ['ACO-GTSP', 'PSO-FA3ACO', 'Enhanced-ECD-ACO', 'Enhanced-ECD-DP']
    jobs = [ExperimentJob(name, ds, 42, params=dict(params)) for name in names]
    messages = []
    results = run.run_jobs_isolated(jobs, lambda d, t, m: messages.append(m))
    assert set(results[ds.name]) == set(names)
    for name in names:
        result = results[ds.name][name][0]
        assert 'error' not in result, str(result.get('error'))+'\n'+result.get('traceback', '')
        assert result['metadata']['execution']['worker_pid'] != os.getpid()
        assert result['metadata']['coverage']['covered_ratio'] > .999999
        assert len(result['internal_paths']) == result['metadata']['n_subregions_total']
    assert any('FA3ACO' in message and '迭代' in message for message in messages)
    assert not multiprocessing.active_children()


def test_cancellation_stops_current_algorithm_and_skips_remaining_jobs():
    run = runner()
    jobs = [ExperimentJob('ACO-GTSP', dataset(), 42, params={'max_iterations': 1000000}),
            ExperimentJob('Enhanced-ECD-DP', dataset(), 42)]
    first_iteration = []
    def progress(done, total, message):
        if 'ACO迭代' in message:
            first_iteration.append(time.monotonic())
            run.cancel()
    results = run.run_jobs_isolated(jobs, progress)
    assert first_iteration
    assert time.monotonic()-first_iteration[-1] < 2.5
    assert results == {}
    assert not multiprocessing.active_children()


def test_timeout_cleans_child_and_allows_next_job():
    run = runner()
    run._timeout_per_job = .01
    jobs = [ExperimentJob('ACO-GTSP', dataset(), 42) for _ in range(2)]
    results = run.run_jobs_isolated(jobs)
    values = results['responsiveness']['ACO-GTSP']
    assert len(values) == 2 and all('TimeoutError' in value['error'] for value in values)
    assert not multiprocessing.active_children()


def test_cancel_before_worker_start_is_not_cleared():
    run = runner()
    run.prepare()
    run.cancel()
    assert run.run_jobs_isolated([ExperimentJob('ACO-GTSP', dataset(), 42)],
                                  reset_cancel=False) == {}


def test_failed_job_does_not_block_later_algorithm():
    results = runner().run_jobs_isolated([
        ExperimentJob('does-not-exist', dataset(), 42),
        ExperimentJob('Enhanced-ECD-DP', dataset(), 42)])
    assert 'error' in results['responsiveness']['does-not-exist'][0]
    assert 'error' not in results['responsiveness']['Enhanced-ECD-DP'][0]


def test_qt_timer_remains_responsive_and_stop_finishes(monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from gui.main_window import MainWindow
    from core.experiment_record import ExperimentRecorder
    monkeypatch.setattr(ExperimentRecorder, 'save_record', lambda *a, **kw: 'not-written-by-gui-test.json')
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    ds = dataset()
    window.project.datasets = [ds]
    window.active_dataset = ds
    window.show()
    app.processEvents()
    ticks = []
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    job = ExperimentJob('PSO-FA3ACO', ds, 42,
        params={'max_iterations': 1000000, 'ants_count': 80, 'pso_iterations': 4, 'pso_swarm_size': 10})
    window._start_worker([job], 'single', [42], CameraParams().as_dict())
    deadline = time.monotonic()+15
    cancelled_at = None
    try:
        while window._thread is not None and time.monotonic() < deadline:
            app.processEvents()
            if ('FA3ACO迭代' in window.sb_stage.text() or '3-opt蚂蚁' in window.sb_stage.text()) and cancelled_at is None and len(ticks) >= 5:
                cancelled_at = time.monotonic()
                window._stop_experiment()
            time.sleep(.005)
        assert window._thread is None
        assert cancelled_at is not None
        assert time.monotonic()-cancelled_at < 3
        assert len(ticks) >= 5
        assert max(b-a for a, b in zip(ticks, ticks[1:])) < .5
        assert window.algo_panel.btn_run.isEnabled()
        assert window.sb_stage.text() == '已终止'
    finally:
        timer.stop()
        window.runner.cancel()
        stop = time.monotonic()+4
        while window._thread is not None and time.monotonic() < stop:
            app.processEvents()
            time.sleep(.01)
        window.close()
