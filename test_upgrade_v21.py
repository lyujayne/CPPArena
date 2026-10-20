"""v2.1 cross-component acceptance tests (real solvers, archive and Qt replay)."""
import json
import os
import zipfile
from copy import deepcopy

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest


def external_history_module():
    import importlib.util
    import sys
    from pathlib import Path
    name = '_independent_history_test'
    if name not in sys.modules:
        from verification.history_location import history_viewer_directory
        path = history_viewer_directory() / 'runtime/gui/history_window.py'
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]
from core.base_algorithm import CameraParams
from core.combinations import (Combination, DECOMPOSITIONS, PLANNERS,
    build_combination_jobs, enumerate_combinations)
from core.experiment_runner import ExperimentRunner
from core.experiment_bundle import make_record, export_bundle, load_bundle
from core.drawing_scale import calibrate_dataset, validate_regions
from data.dataset import Dataset, Project


def metric_dataset():
    ds = Dataset('组合验收')
    ds.add_region('L形地块', [(500000, 4400000), (500300, 4400000),
        (500300, 4400100), (500100, 4400100), (500100, 4400300), (500000, 4400300)])
    ds.launch_point = (499970, 4399970)
    return ds


@pytest.fixture(scope='module')
def experiment():
    ds = metric_dataset()
    # Keep this historical v2.1 acceptance fixture at its original nine pairs.
    # Later built-ins have their own full catalog integration checks.
    combos = enumerate_combinations(('Bayazit', 'PSO-DCAS', 'Enhanced-ECD'), ('ACO', 'FA3ACO', 'Li-DP'))
    for combo in combos:
        if combo.decomposition == 'PSO-DCAS':
            combo.decomposition_params.update(pso_swarm_size=10, pso_iterations=4)
        if combo.planning != 'Li-DP':
            combo.planning_params['max_iterations'] = 3
        if combo.planning == 'FA3ACO':
            combo.planning_params['ants_count'] = 4
    camera = CameraParams().as_dict()
    jobs = build_combination_jobs(combos, [ds], [42], camera)
    runner = ExperimentRunner()
    runner.registry.load_builtins()
    progress = []
    results = runner.run_jobs_isolated(jobs, lambda d, t, m: progress.append((d, t, m)))
    return ds, combos, camera, results, progress


def test_all_nine_pairs_execute_with_independent_hooks(experiment):
    ds, combos, camera, results, progress = experiment
    assert len(combos) == len(results[ds.name]) == 9
    for combo in combos:
        runs = results[ds.name][combo.label]
        assert len(runs) == 1
        run = runs[0]
        assert not run.get('error'), run.get('traceback')
        assert run['combination'] == combo.to_dict()
        assert run['params'] == combo.effective_params()
        assert run['metadata']['execution']['backend'] == 'spawn-process'
        assert run['metadata']['coverage']['covered_ratio'] > .999999
        assert run['waypoints'][0] == run['waypoints'][-1] == ds.launch_point
        assert run['started_at'] <= run['finished_at']
        assert run['subregion_sequence']
        metrics = run['metadata']['route_metrics']
        assert metrics['scan_distance_m'] + metrics['non_scan_distance_m'] == pytest.approx(run['total_distance'])
        assert 0 <= metrics['outside_distance_m'] <= run['total_distance'] + 1e-6
        assert 0 <= metrics['redundancy_pct'] <= 100
        if combo.planning == 'Li-DP':
            assert metrics['subregion_transfer_m'] == pytest.approx(run['metadata']['gtsp']['objective_value'])
    messages = '\n'.join(m for _, _, m in progress)
    assert '4/4' in messages and '3/3' in messages
    assert sum('：完成' in m for _, _, m in progress) == 9
    assert progress[-1][0:2] == (9, 9)


def test_duplicate_pairs_remain_distinct_and_params_do_not_leak():
    a = Combination('PSO-DCAS', 'ACO')
    b = Combination('PSO-DCAS', 'ACO')
    a.decomposition_params['pso_iterations'] = 2
    a.planning_params['max_iterations'] = 3
    assert a.id != b.id
    assert b.effective_params()['decomposition']['pso_iterations'] == 120
    assert b.effective_params()['planning']['max_iterations'] == 500
    jobs = build_combination_jobs([a, b], [metric_dataset()], [1, 2], {})
    assert len(jobs) == 4 and len({job.algorithm for job in jobs}) == 2
    jobs[0].combination['planning_params']['max_iterations'] = 99
    assert a.planning_params['max_iterations'] == 3


def test_failure_keeps_identity_and_next_combination_runs():
    bad = Combination('Bayazit', 'Li-DP', planning_params={'dp_max_groups': 1})
    good = Combination('Enhanced-ECD', 'ACO', planning_params={'max_iterations': 2})
    ds = metric_dataset()
    runner = ExperimentRunner()
    runner.registry.load_builtins()
    results = runner.run_jobs_isolated(build_combination_jobs([bad, good], [ds], [42], {}))
    assert results[ds.name][bad.label][0]['error']
    assert results[ds.name][bad.label][0]['combination']['id'] == bad.id
    assert results[ds.name][bad.label][0]['params'] == bad.effective_params()
    assert not results[ds.name][good.label][0].get('error')


def test_export_is_portable_and_replay_never_runs_algorithms(experiment, tmp_path, monkeypatch):
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    HistoryWindow = external_history_module().HistoryWindow
    from gui.theme import apply_theme
    from core.combinations import ComposedAlgorithm
    ds, combos, camera, results, progress = experiment
    ds = Dataset.from_dict(ds.to_dict())
    image = tmp_path / 'original.png'
    Image.new('RGB', (16, 16), '#e4efd9').save(image)
    ds.bg_image_path = str(image)
    ds.bg_bounds_utm = (499900, 4399900, 500400, 4400400)
    record = make_record('验收实验', [ds], camera, combos, results, '完成日志',
                         {'decomposed': True, 'layers': {'image': False}})
    target = tmp_path / 'experiment.cppx'
    export_bundle(target, record)
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        for suffix in ('waypoints.kml', 'segmentation.kml', 'segmentation.json',
                       'trajectory.jpg', 'segmentation.jpg', 'result.json'):
            assert sum(name.endswith(suffix) for name in names) == 9
        for name in ('experiment.json', 'metrics.csv', 'metrics.json', 'experiment.log'):
            assert name in names
        assert b'NaN' not in archive.read('experiment.json')
    image.unlink()  # Prove the bundle does not depend on the original asset.
    assets = tmp_path / 'assets'
    assets.mkdir()
    restored = load_bundle(target, assets)
    original_results = json.loads(json.dumps(record['results']))
    restored_results = deepcopy(restored['results'])
    for values in restored_results.values():
        for runs in values.values():
            for run in runs:
                assert run.pop('artifacts').startswith('runs/')
    assert restored_results == original_results
    assert restored['combinations'] == record['combinations']
    assert os.path.isfile(restored['datasets'][0]['bg_image_path'])
    def must_not_solve(*args, **kwargs):
        raise AssertionError('History tried to run an algorithm')
    monkeypatch.setattr(ComposedAlgorithm, 'solve', must_not_solve)
    monkeypatch.setattr('algorithms.common.decompose_region_with', must_not_solve)
    monkeypatch.setattr('algorithms.aco.polygon_decomp.convex_decompose', must_not_solve)
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = HistoryWindow(library_dir=tmp_path / 'history-library')
    window.set_record(restored)
    assert window.run_combo.count() == 10
    assert not window.image_check.isChecked()
    for i in range(1, window.run_combo.count()):
        window.run_combo.setCurrentIndex(i)
        window.canvas.set_decomposed(True)
        window.canvas.redraw()
        label, index = window.run_combo.currentData()
        assert window.canvas._results[label] == restored['results'][ds.name][label][index]
    window.close()


def test_metric_drawing_calibration_and_project_roundtrip():
    ds = Dataset('tiny')
    ds.add_region('tiny', [(0, 0), (.5, 0), (.5, .3), (0, .3)])
    ds.launch_point = (-.1, -.1)
    camera = CameraParams()
    assert validate_regions(ds, camera)
    calibrate_dataset(ds, 500)
    assert not validate_regions(ds, camera)
    assert max(p[0] for p in ds.regions[0].vertices)-min(p[0] for p in ds.regions[0].vertices) == 500
    project = Project()
    project.datasets = [ds]
    combo = Combination('PSO-DCAS', 'FA3ACO', planning_params={'max_iterations': 3})
    project.combinations = [combo.to_dict()]
    restored = Project.from_dict(project.to_dict())
    assert restored.combinations == project.combinations
    assert restored.datasets[0].to_dict() == ds.to_dict()
    with pytest.raises(ValueError):
        ds.add_region('bowtie', [(0, 0), (1, 1), (0, 1), (1, 0)])


def test_combination_ui_delete_selection_and_seed_validation():
    from PySide6.QtWidgets import QApplication
    from gui.experiment_panel import ExperimentPanel
    app = QApplication.instance() or QApplication([])
    panel = ExperimentPanel()
    panel.planner_checks['Li-DP'].setChecked(False)
    panel.enumerate()
    assert len(panel.combinations) == 6
    panel.table.selectRow(2)
    panel.remove_selected()
    assert len(panel.combinations) == 5
    panel.seeds_edit.setText('1-3,42')
    assert panel.seeds() == [1, 2, 3, 42]
    panel.seeds_edit.setText('abc')
    with pytest.raises(ValueError):
        panel.seeds()
    panel.close()


def test_kml_triggers_background_in_worker_and_toggle_hides_image(tmp_path, monkeypatch):
    import time
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    from gui.main_window import MainWindow
    from config.default_params import RESOURCE_DIR
    image = tmp_path / 'satellite.png'
    Image.new('RGB', (32, 32), '#dce9ca').save(image)
    calls = []
    def fake_fetch(lon0, lat0, lon1, lat1, **kwargs):
        calls.append((lon0, lat0, lon1, lat1))
        return str(image), (lon0, lat0, lon1, lat1)
    monkeypatch.setattr('gui.main_window.fetch_satellite_basemap', fake_fetch)
    monkeypatch.setattr('gui.main_window.QFileDialog.getOpenFileNames', lambda *a, **kw:
        ([os.path.join(RESOURCE_DIR, 'data', 'samples', '示例农田.kml')], ''))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._import_kml()
    deadline = time.monotonic()+5
    while window._satellite_tasks and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert calls and not window._satellite_tasks
    from pathlib import Path
    saved_image = Path(window.active_dataset.bg_image_path)
    assert saved_image.is_file() and saved_image.read_bytes() == image.read_bytes()
    assert saved_image.parent == window.dataset_library.directory / 'assets'
    assert len(window.canvas.ax.images) == 1
    window.background_check.setChecked(False)
    assert len(window.canvas.ax.images) == 0
    assert not hasattr(window, 'btn_sat')
    window.close()


def test_gui_runs_final_list_and_saves_full_snapshot(tmp_path, monkeypatch):
    import time
    from PySide6.QtWidgets import QApplication
    from gui.main_window import MainWindow
    monkeypatch.setattr('gui.main_window.EXPERIMENT_DIR', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    ds = metric_dataset()
    window.project.datasets = [ds]
    window._set_active_dataset(ds)
    kept = Combination('Bayazit', 'ACO', planning_params={'max_iterations': 2})
    removed = Combination('PSO-DCAS', 'FA3ACO')
    panel = window.experiment_panel
    panel.combinations = [kept, removed]
    panel.refresh_table()
    panel.table.selectRow(1)
    panel.remove_selected()
    window.run_experiment()
    assert panel.configuration.isEnabled()
    assert panel.table.isEnabled()
    assert not panel.seeds_edit.isEnabled()
    deadline = time.monotonic()+12
    while window._thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    try:
        assert window._thread is None
        assert list(window.results[ds.name]) == [kept.label]
        assert window._record['combinations'] == [kept.to_dict()]
        assert window._record['datasets'][0]['regions'] == json.loads(json.dumps([r.to_dict() for r in ds.regions]))
        assert list(tmp_path.glob('experiment_*.json'))
        assert '完成' in panel.log.toPlainText()
        assert panel.configuration.isEnabled()
        window.run_combo.setCurrentIndex(1)
        assert window.result_panel.lbl_algo.text() == kept.label
    finally:
        window.runner.cancel()
        cleanup = time.monotonic()+4
        while window._thread is not None and time.monotonic() < cleanup:
            app.processEvents()
            time.sleep(.01)
        window.close()


def test_background_finishing_after_snapshot_is_included_without_mixing_geometry(tmp_path):
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    from gui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    ds = metric_dataset()
    window.project.datasets = [ds]
    record = make_record('late background', [ds], {}, [], {})
    image = tmp_path / 'late.png'
    Image.new('RGB', (8, 8)).save(image)
    ds.bg_image_path = str(image)
    ds.bg_bounds_utm = (499900, 4399900, 500400, 4400400)
    window._sync_record_backgrounds(record)
    assert record['datasets'][0]['bg_image_path'] == str(image)
    record['datasets'][0]['bg_image_path'] = None
    ds.regions[0].vertices[0] = (500001, 4400000)
    window._sync_record_backgrounds(record)
    assert record['datasets'][0]['bg_image_path'] is None
    window.close()


def test_history_scan_ignores_unrelated_json_lists(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    HistoryWindow = external_history_module().HistoryWindow
    (tmp_path / 'metrics.json').write_text('[{"distance":100}]', encoding='utf-8')
    (tmp_path / 'unrelated.json').write_text('null', encoding='utf-8')
    (tmp_path / 'broken.json').write_text('{', encoding='utf-8')
    monkeypatch.setattr(external_history_module(), 'EXPERIMENT_DIR', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = HistoryWindow()
    assert window.library.count() == 0
    window.close()
