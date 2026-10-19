"""Regression coverage for durable datasets, assigned jobs and actual UI exports."""
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication, QGroupBox

from core.combinations import Combination, build_combination_jobs
from core.experiment_runner import ExperimentRunner
from test_upgrade_v21 import metric_dataset


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def results():
    ds = metric_dataset()
    combos = [Combination('Bayazit', 'ACO', planning_params={'max_iterations': 2}),
              Combination('Enhanced-ECD', 'Li-DP')]
    runner = ExperimentRunner()
    runner.registry.load_builtins()
    runs = runner.run_jobs_isolated(build_combination_jobs(combos, [ds], [42], {}))
    for group in runs[ds.name].values():
        assert not group[0].get('error'), group[0].get('traceback')
    return ds, combos, runs


def test_comparison_and_markdown_use_real_coverage_without_tabulate(results, monkeypatch):
    import pandas as pd
    from compare.statistics import build_comparison_table
    from compare.report_gen import generate_report
    ds, combos, runs = results
    def forbidden(*args, **kwargs):
        raise AssertionError('Optional tabulate dependency must not be needed')
    monkeypatch.setattr(pd.DataFrame, 'to_markdown', forbidden)
    table = build_comparison_table(runs[ds.name], baseline=combos[0].label)
    assert table.loc['有效运行次数', combos[0].label] == 1
    assert table.loc['扫描足迹覆盖率均值 (%)', combos[0].label] > 99
    assert table.loc['未覆盖面积均值 (m²)', combos[0].label] >= 0
    report = generate_report('工作流验收', {}, runs[ds.name], combos[0].label,
                             {}, {}, [42], ['summary_assets/convergence.png'])
    assert all(combo.label in report for combo in combos)
    assert 'max_iterations' in report and '扫描足迹覆盖率' in report
    assert '(summary_assets/convergence.png)' in report


def test_ui_exports_selected_combination_and_portable_summary(app, results, tmp_path, monkeypatch):
    from PIL import Image
    from gui.compare_panel import ComparePanel
    from config.default_params import PICTURE_DIR
    import core.experiment_bundle as bundle
    ds, combos, runs = results
    panel = ComparePanel()
    panel.set_data(runs, [ds], {}, combos[0].label, seeds=[42])
    assert panel.table.columnCount() == 2 and panel.table.rowCount() > 8
    assert not any('统计失败' in panel.table.item(i, j).text()
                   for i in range(panel.table.rowCount()) for j in range(2))
    assert not panel.scatter_check.isChecked()
    panel.tabs.setCurrentIndex(2)
    assert len(panel._stat_fig.axes) == 2
    panel.scatter_check.setChecked(True)
    assert len(panel._stat_fig.axes) == 3
    warnings = []
    monkeypatch.setattr('gui.compare_panel.QMessageBox.warning', lambda *a: warnings.append(a[-1]))
    monkeypatch.setattr('gui.compare_panel.QMessageBox.information', lambda *a: None)
    defaults, rendered = [], []
    output = tmp_path / 'selected.jpg'
    def save_dialog(parent, title, default, filters):
        defaults.append(default)
        return str(output), ''
    original = bundle._plot_run
    def plot(path, dataset, run, *args, **kwargs):
        rendered.append(run['algorithm'])
        return original(path, dataset, run, *args, **kwargs)
    monkeypatch.setattr(bundle, '_plot_run', plot)
    monkeypatch.setattr('gui.compare_panel.QFileDialog.getSaveFileName', save_dialog)
    panel.wp_algo_combo.setCurrentIndex(1)
    panel.export_route_image()
    assert rendered == [combos[1].label]
    assert Path(defaults[0]).parent == Path(PICTURE_DIR)
    with Image.open(output) as image:
        assert image.width > 500 and image.height > 500
    output = tmp_path / 'summary.md'
    panel.generate_report()
    assert not warnings, warnings
    report = output.read_text(encoding='utf-8')
    assert '(summary_assets/convergence.jpg)' in report
    assert '(summary_assets/statistics.jpg)' in report
    assert (tmp_path / 'summary_assets/convergence.jpg').is_file()
    panel.close()


def test_partition_and_route_remain_visible_with_opaque_halo():
    from matplotlib.figure import Figure
    from core.path_annotations import draw_partition, draw_route
    ax = Figure().subplots()
    draw_route(ax, {'internal_paths': [[(0, 0), (2, 2)]], 'waypoints': [(0, 0), (2, 2)]}, 'blue')
    boundary = draw_partition(ax, [(0, 0), (2, 0), (2, 2)], 'blue')
    assert boundary.get_zorder() < max(line.get_zorder() for line in ax.lines)
    assert boundary.get_linewidth() > ax.lines[0].get_linewidth()
    assert boundary.get_joinstyle() == 'round'
    assert boundary.get_edgecolor()[-1] == 1
    assert len(boundary.get_path_effects()) == 2


def test_multi_kml_import_and_restart_do_not_depend_on_source_files(app, tmp_path, monkeypatch):
    from PIL import Image
    from config.default_params import RESOURCE_DIR
    from gui.main_window import MainWindow
    source = Path(RESOURCE_DIR) / 'data/samples/示例农田.kml'
    paths = [tmp_path / 'field_a.kml', tmp_path / 'field_b.kml']
    for path in paths:
        path.write_bytes(source.read_bytes())
    monkeypatch.setattr(MainWindow, '_load_satellite', lambda self: None)
    library = tmp_path / 'persistent'
    window = MainWindow(dataset_library_dir=library)
    loaded = window.import_kml_paths([str(path) for path in paths])
    assert len(loaded) == 2 and window.dataset_combo.count() == 2
    image = tmp_path / 'background.png'
    Image.new('RGB', (8, 8), 'green').save(image)
    loaded[0].bg_image_path = str(image)
    loaded[0].launch_point = loaded[0].regions[0].vertices[0]
    window._save_datasets()
    snapshot = [ds.to_dict() for ds in loaded]
    window.close()
    for path in paths + [image]:
        path.unlink()
    restored = MainWindow(dataset_library_dir=library)
    assert [ds.to_dict() for ds in restored.project.datasets] == snapshot
    assert Path(restored.project.datasets[0].bg_image_path).is_file()
    assert len(restored.experiment_panel.datasets) == 2
    assert restored.result_panel.log is restored.experiment_panel.log
    assert not any('算法细节' in box.title() for box in restored.findChildren(QGroupBox))
    restored.experiment_panel.append_log('keep log on result selection')
    restored.result_panel.clear()
    assert 'keep log' in restored.result_panel.log.toPlainText()
    restored.close()


def test_explicit_dataset_assignment_overrides_global_scope():
    a, b, unused = [metric_dataset() for _ in range(3)]
    for ds, name in zip((a, b, unused), ('A', 'B', 'unused')):
        ds.name = name
    ca = Combination('Bayazit', 'ACO', dataset_ids=[a.id])
    cb = Combination('Enhanced-ECD', 'Li-DP', dataset_ids=[b.id])
    jobs = build_combination_jobs([ca, cb], [a, b, unused], [1, 2], {}, [unused.id])
    assert [(job.dataset.name, job.algorithm, job.seed) for job in jobs] == [
        ('A', ca.label, 1), ('A', ca.label, 2), ('B', cb.label, 1), ('B', cb.label, 2)]
    assert Combination(**ca.to_dict()).dataset_ids == [a.id]
    with pytest.raises(ValueError, match='已不存在'):
        build_combination_jobs([ca], [b], [1], {})
    ca.dataset_ids = []
    with pytest.raises(ValueError, match='没有选择'):
        build_combination_jobs([ca], [a], [1], {})


def test_installed_components_execute_in_spawned_worker_and_preserve_params(tmp_path, monkeypatch):
    from core.component_plugins import component_template, install_component, read_component
    from core.combinations import DECOMPOSITIONS, PLANNERS
    monkeypatch.setenv('CPP_ARENA_COMPONENT_DIR', str(tmp_path / 'components'))
    d = tmp_path / 'split.py'
    d.write_text(component_template('decomposition').replace('custom_decomposition', 'test_split')
                 .replace('DEFAULT_PARAMS = {}', 'DEFAULT_PARAMS = {"cut_budget": 7}'), encoding='utf-8')
    p = tmp_path / 'plan.py'
    p.write_text(component_template('planning').replace('custom_planning', 'test_plan')
                 .replace('"max_iterations": 100', '"max_iterations": 2'), encoding='utf-8')
    try:
        assert install_component(d, 'decomposition') == 'test_split'
        assert install_component(p, 'planning') == 'test_plan'
        combo = Combination('test_split', 'test_plan')
        assert combo.effective_params()['decomposition'] == {'cut_budget': 7}
        ds = metric_dataset()
        runner = ExperimentRunner()
        runner.registry.load_builtins()
        runs = runner.run_jobs_isolated(build_combination_jobs([combo], [ds], [42], {}))
        run = runs[ds.name][combo.label][0]
        assert not run.get('error'), run.get('traceback')
        assert run['params']['decomposition']['cut_budget'] == 7
        assert run['params']['planning']['max_iterations'] == 2
        assert all(len(v['sha256']) == 64 for v in run['metadata']['component_sources'].values())
        installed = Path(DECOMPOSITIONS['test_split'][1].source_path)
        before = installed.stat()
        changed = installed.read_text(encoding='utf-8').replace('"cut_budget": 7', '"cut_budget": 9')
        installed.write_text(changed, encoding='utf-8')
        os.utime(installed, (before.st_atime, before.st_mtime))
        install_component(installed, 'decomposition')
        assert Combination('test_split', 'test_plan').effective_params()['decomposition']['cut_budget'] == 9
        with pytest.raises(ValueError, match='MODULE_KIND'):
            read_component(d, 'planning')
        d.write_text(d.read_text(encoding='utf-8').replace('test_split', 'Bayazit'), encoding='utf-8')
        with pytest.raises(ValueError, match='冲突'):
            install_component(d, 'decomposition')
    finally:
        DECOMPOSITIONS.pop('test_split', None)
        PLANNERS.pop('test_plan', None)
