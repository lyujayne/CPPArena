"""v2.4 failure visibility, fixed panels, live scrolling and isolated export."""
import json
import os
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import time
import weakref

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from compare.statistics import build_comparison_table
from core.combinations import Combination
from core.experiment_bundle import make_record
from gui.compare_panel import ComparePanel
from gui.experiment_panel import ExperimentPanel
from gui.experiment_export import ExperimentExportWorker
from test_review_v21 import example
from test_upgrade_v21 import external_history_module


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def failed(seed=1):
    return dict(seed=seed, error='ValueError: cannot plan', total_distance=float('nan'))


def record(count=2):
    from core.base_algorithm import CameraParams
    ds, run = example()
    runs = []
    for seed in range(count):
        current = deepcopy(run)
        current['seed'] = seed
        runs.append(current)
    combo = Combination('Bayazit', 'ACO')
    return make_record('export regression', [ds], CameraParams().as_dict(), [combo],
                       {ds.name: {combo.label: runs}}, 'complete experiment log')


def wait_for_export(app, window, timeout=60000):
    loop = QEventLoop()
    window._export_thread.finished.connect(loop.quit)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout)
    loop.exec()
    assert window._export_thread is None, 'export did not stop before timeout'


def test_statistics_include_failed_and_partial_combinations_without_fake_distances():
    _, good = example()
    values = {'good': [good], 'bad': [failed()], 'mixed': [good, failed()], 'empty': []}
    df = build_comparison_table(values, baseline='good')
    assert list(df.columns) == list(values)
    assert df.loc['运行状态'].to_dict() == dict(good='成功', bad='运行失败', mixed='部分失败', empty='无运行结果')
    assert df.loc['有效运行次数', 'bad'] == 0 and df.loc['失败运行次数', 'mixed'] == 1
    assert df.loc['总距离均值 (m)', 'bad'] != df.loc['总距离均值 (m)', 'bad']
    assert df.loc['总距离均值 (m)', 'mixed'] == good['total_distance']


def test_all_failed_table_red_and_error_area_stays_fixed(app):
    panel = ComparePanel()
    panel.resize(1100, 800)
    panel.show()
    panel.set_data({'d': {'bad': [failed()]}}, [], {}, None)
    app.processEvents()
    position, height = panel.failure_label.pos(), panel.failure_label.height()
    assert panel.table.columnCount() == 1
    assert panel.table.horizontalHeaderItem(0).foreground().color().name() == '#b91c1c'
    row = next(i for i in range(panel.table.rowCount()) if panel.table.verticalHeaderItem(i).text() == '总距离均值 (m)')
    assert panel.table.item(row, 0).text() == '--'
    assert panel.table.item(row, 0).foreground().color().name() == '#b91c1c'
    panel.set_data({'d': {'bad': [failed(seed) for seed in range(150)]}}, [], {}, None)
    app.processEvents()
    assert panel.failure_label.pos() == position and panel.failure_label.height() == height == 94
    assert panel.failure_label.verticalScrollBar().maximum() > 0
    panel.failure_label.verticalScrollBar().setValue(panel.failure_label.verticalScrollBar().maximum())
    assert panel.failure_label.verticalScrollBar().value() > 0
    panel.tabs.setCurrentIndex(1)
    panel.tabs.setCurrentIndex(2)
    app.processEvents()
    assert panel._active_runs() == {} and panel.baseline_combo.count() == 1
    panel.close()


def test_partial_failures_red_and_no_failed_waypoint_selection(app):
    ds, good = example()
    panel = ComparePanel()
    panel.set_data({ds.name: {'mixed': [good, failed()], 'bad': [failed()], 'ok': [good]}}, [ds], {}, 'ok')
    assert panel.table.columnCount() == 3
    assert panel.table.horizontalHeaderItem(0).foreground().color().name() == '#b91c1c'
    assert panel.table.horizontalHeaderItem(1).foreground().color().name() == '#b91c1c'
    assert panel.table.horizontalHeaderItem(2).foreground().color().name() != '#b91c1c'
    assert [panel.wp_algo_combo.itemData(i) for i in range(panel.wp_algo_combo.count())] == ['mixed', 'ok']
    panel.close()


def test_algorithm_choices_and_combination_table_keep_scrolling_while_running(app):
    from PySide6.QtWidgets import QCheckBox
    panel = ExperimentPanel()
    panel.resize(600, 850)
    panel.combinations = [Combination('Bayazit', 'ACO') for _ in range(80)]
    panel.refresh_table()
    panel.show()
    app.processEvents()
    table_top = panel.table.pos()
    for i in range(60):
        panel.decomposition_layout.insertWidget(panel.decomposition_layout.count()-1, QCheckBox(f'plugin {i}'))
    app.processEvents()
    assert panel.table.pos() == table_top
    panel.set_running(True)
    app.processEvents()
    assert panel.configuration.isEnabled() and panel.table.isEnabled()
    for scroll in panel.algorithm_scrolls:
        assert scroll.parentWidget().height() == 210
        assert scroll.verticalScrollBar().maximum() > 0
        scroll.verticalScrollBar().setValue(50)
        assert scroll.verticalScrollBar().value() == 50
    bar = panel.table.verticalScrollBar()
    assert bar.isEnabled() and bar.maximum() > 0
    bar.setValue(bar.maximum())
    assert bar.value() > 0
    assert not panel.table.cellWidget(79, 2).isEnabled()
    assert not panel.seeds_edit.isEnabled()
    panel.set_running(False)
    assert panel.table.cellWidget(79, 2).isEnabled() and panel.seeds_edit.isEnabled()
    panel.close()


def test_async_export_keeps_gui_alive_and_exports_every_run(app, tmp_path, monkeypatch):
    from gui.main_window import MainWindow
    from core.experiment_bundle import load_experiment_directory
    monkeypatch.setattr('gui.main_window.HISTORY_EXPERIMENT_DIR', str(tmp_path/'history'))
    monkeypatch.setattr('gui.main_window.QInputDialog.getText', lambda *a, **kw: ('bulk complete', True))
    monkeypatch.setattr('gui.main_window.QMessageBox.information', lambda *a: None)
    monkeypatch.setattr('gui.main_window.QMessageBox.critical', lambda *a: pytest.fail(str(a)))
    window = MainWindow(dataset_library_dir=tmp_path/'datasets')
    original = record(5)
    window._record = original
    results_reference = original['results']
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(15)
    start = time.perf_counter()
    window._export_experiment()
    assert time.perf_counter()-start < 1.5
    assert window._export_worker.record['results'] is results_reference
    assert not window.experiment_panel.btn_run.isEnabled()
    progress = []
    window._export_worker.progress.connect(lambda *args: progress.append(args))
    wait_for_export(app, window)
    timer.stop()
    assert len(ticks) > 8 and len(progress) > 5
    folders = list((tmp_path/'history').iterdir())
    assert len(folders) == 1
    exported = load_experiment_directory(folders[0])
    assert exported['results'].keys() == original['results'].keys()
    assert len(list(folders[0].glob('runs/*/trajectory.jpg'))) == 5
    assert len(list(folders[0].glob('runs/*/segmentation.jpg'))) == 5
    assert len(list(folders[0].glob('runs/*/result.json'))) == 5
    metrics = json.loads((folders[0]/'metrics.json').read_text(encoding='utf-8'))
    expected_label = next(iter(next(iter(results_reference.values()))))
    assert all(row['combination'] == expected_label for row in metrics)
    assert window.experiment_panel.btn_export.isEnabled()
    saved_run = next(iter(next(iter(results_reference.values())).values()))[0]
    assert 'artifacts' not in saved_run
    window.close()


def test_export_cancel_cleans_staging_and_restores_controls(app, tmp_path, monkeypatch):
    from gui.main_window import MainWindow
    monkeypatch.setattr('gui.main_window.HISTORY_EXPERIMENT_DIR', str(tmp_path/'history'))
    monkeypatch.setattr('gui.main_window.QInputDialog.getText', lambda *a, **kw: ('cancel bulk', True))
    window = MainWindow(dataset_library_dir=tmp_path/'datasets')
    window._record = record(30)
    window._export_experiment()
    QTimer.singleShot(120, window._cancel_export)
    wait_for_export(app, window)
    assert list((tmp_path/'history').iterdir()) == []
    assert window.experiment_panel.btn_export.isEnabled()
    assert '已取消导出' in window.experiment_panel.log.toPlainText()
    window.close()


def test_native_child_failure_is_reported_and_does_not_publish_incomplete_folder(tmp_path, monkeypatch):
    import gui.experiment_export as module
    real_popen = subprocess.Popen
    def broken_child(*args, **kwargs):
        # Exercise a real nonzero child exit, not an exception in the GUI.
        return real_popen([os.sys.executable, '-c', 'raise SystemExit(37)'], **kwargs)
    monkeypatch.setattr(module.subprocess, 'Popen', broken_child)
    worker = ExperimentExportWorker(tmp_path/'library', record(), 'broken')
    errors, successes = [], []
    worker.failed.connect(errors.append)
    worker.succeeded.connect(successes.append)
    worker.run()
    assert not successes and '37' in errors[0]
    assert list((tmp_path/'library').iterdir()) == []


def test_window_close_waits_for_export_worker_cleanup(app, tmp_path, monkeypatch):
    from gui.main_window import MainWindow
    monkeypatch.setattr('gui.main_window.HISTORY_EXPERIMENT_DIR', str(tmp_path/'history'))
    monkeypatch.setattr('gui.main_window.QInputDialog.getText', lambda *a, **kw: ('close export', True))
    window = MainWindow(dataset_library_dir=tmp_path/'datasets')
    window._record = record(20)
    window.show()
    window._export_experiment()
    QTimer.singleShot(120, window.close)
    wait_for_export(app, window)
    app.processEvents()
    assert not window.isVisible()
    assert list((tmp_path/'history').iterdir()) == []


def test_cancel_during_rendering_discards_completed_and_partial_staged_runs(app, tmp_path, monkeypatch):
    from gui.main_window import MainWindow
    monkeypatch.setattr('gui.main_window.HISTORY_EXPERIMENT_DIR', str(tmp_path/'history'))
    monkeypatch.setattr('gui.main_window.QInputDialog.getText', lambda *a, **kw: ('mid-export cancel', True))
    window = MainWindow(dataset_library_dir=tmp_path/'datasets')
    window._record = record(25)
    window._export_experiment()
    completed = []
    window._export_worker.progress.connect(lambda done, total, stage: completed.append(done))
    timer = QTimer()
    def cancel_after_first():
        if any(done >= 1 for done in completed):
            window._cancel_export()
            timer.stop()
    timer.timeout.connect(cancel_after_first)
    timer.start(15)
    wait_for_export(app, window)
    timer.stop()
    assert any(done >= 1 for done in completed)
    assert list((tmp_path/'history').iterdir()) == []
    window.close()


def test_headless_plot_releases_agg_renderer_after_every_image(tmp_path, monkeypatch):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from core.experiment_bundle import _plot_run
    import matplotlib.backends.backend_agg as agg
    canvas_refs = []
    class TrackingCanvas(FigureCanvasAgg):
        def __init__(self, figure):
            super().__init__(figure)
            canvas_refs.append(weakref.ref(self))
    monkeypatch.setattr(agg, 'FigureCanvasAgg', TrackingCanvas)
    ds, run = example()
    for i in range(4):
        import warnings
        with warnings.catch_warnings(record=True) as emitted:
            warnings.simplefilter('always')
            _plot_run(tmp_path/f'{i}.jpg', ds, run)
        assert not any('Glyph' in str(w.message) and 'missing' in str(w.message) for w in emitted)
        assert canvas_refs[-1]() is None


@pytest.mark.skipif(os.name != 'nt', reason='Windows inherited ACL regression')
def test_published_folder_keeps_library_permission_inheritance(tmp_path):
    from core.experiment_bundle import export_experiment_directory
    value = record()
    for values in value['results'].values():
        for label in values:
            values[label] = [dict(seed=1, error='test failure', total_distance=None)]
    folder = export_experiment_directory(tmp_path, value, 'inherited access')
    # Check with a separate native reader, independently of Python's owner access.
    result = subprocess.run([shutil.which('pwsh') or 'powershell', '-NoProfile', '-Command',
        '(Get-Acl -LiteralPath $env:CPP_TEST_EXPORT_FOLDER).AreAccessRulesProtected'],
        env=dict(os.environ, CPP_TEST_EXPORT_FOLDER=str(folder)), capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'False'


def test_relative_dataset_assets_survive_whole_library_move(tmp_path):
    from PIL import Image
    from data.dataset_library import DatasetLibrary
    ds, _ = example()
    image = tmp_path/'background.jpg'
    Image.new('RGB', (12, 12)).save(image)
    ds.bg_image_path = str(image)
    old = tmp_path/'old_library'
    DatasetLibrary(old).save([ds])
    payload = json.loads((old/'library.json').read_text(encoding='utf-8'))
    assert payload['datasets'][0]['bg_image_path'].startswith('assets/')
    new = old.rename(tmp_path/'new_library')
    loaded = DatasetLibrary(new).load()[0]
    assert Path(loaded.bg_image_path).is_file()
    assert new in Path(loaded.bg_image_path).parents


def test_versioned_source_move_rebases_existing_backgrounds_and_projects(tmp_path, monkeypatch):
    import config.default_params as config
    from data.dataset import Dataset
    old, new = tmp_path/'CPP _Arena_v1.4', tmp_path/'CPP _Arena_v2.4'
    (new/'dataset_library/assets').mkdir(parents=True)
    (new/'dataset_library/assets/background.jpg').write_bytes(b'asset')
    monkeypatch.setattr(config, 'BASE_DIR', str(new))
    saved = record()['datasets'][0]
    saved['bg_image_path'] = str(old/'dataset_library/assets/background.jpg')
    ds = Dataset.from_dict(saved)
    assert ds.bg_image_path == str(new/'dataset_library/assets/background.jpg')
    (new/'algorithms/plugins').mkdir(parents=True)
    assert config.resolve_versioned_path(str(old/'algorithms/plugins')) == str(new/'algorithms/plugins')
    # Do not reinterpret unrelated external sources as local copies.
    unrelated = str(tmp_path/'other'/'CPP _Arena_v1.4/dataset_library/assets/background.jpg')
    assert config.resolve_versioned_path(unrelated) == unrelated


def test_history_uses_same_failed_table_and_fixed_error_area(app, tmp_path):
    viewer = external_history_module().HistoryWindow(library_dir=tmp_path/'history')
    value = record()
    ds_name = value['datasets'][0]['name']
    value['results'][ds_name]['bad combo'] = [dict(failed(), total_distance=None)]
    viewer.set_record(value)
    comparison = viewer.comparison
    col = next(i for i in range(comparison.table.columnCount()) if comparison.table.horizontalHeaderItem(i).text() == 'bad combo')
    assert comparison.table.horizontalHeaderItem(col).foreground().color().name() == '#b91c1c'
    assert comparison.failure_label.height() == 94
    viewer.close()
