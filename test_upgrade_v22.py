"""v2.2 area coverage, named folder archives and permanent history imports."""
import json
import os
import subprocess
import sys
import zipfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication, QLabel
from compare.coverage_metrics import evaluate_coverage, format_area
from compare.statistics import build_comparison_table
from core.base_algorithm import CameraParams
from core.combinations import Combination
from core.experiment_bundle import (make_record, export_bundle, export_experiment_directory,
                                    load_experiment_directory, import_experiment)
from core.experiment_runner import ExperimentRunner, ExperimentJob
from data.dataset import Dataset, Project
from config.default_params import APP_VERSION
from test_upgrade_v21 import metric_dataset, external_history_module


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def experiment():
    ds = metric_dataset()
    combo = Combination('Bayazit', 'ACO', planning_params={'max_iterations': 2})
    camera = CameraParams().as_dict()
    run = ExperimentRunner()._run_single(ExperimentJob(combo.label, ds, 42, camera=camera, combination=combo.to_dict()))
    return ds, make_record('原工程', [ds], camera, [combo], {ds.name: {combo.label: [run]}}, '实验完成\n测试错误：红色日志')


def test_coverage_is_scanned_target_union_divided_by_total_task_union():
    ds = Dataset()
    ds.add_region('a', [(0, 0), (4, 0), (4, 2), (0, 2)])
    ds.add_region('overlap', [(2, 0), (6, 0), (6, 2), (2, 2)])
    # The camera scans beyond both ends; outside area must not inflate coverage.
    values = evaluate_coverage(ds.regions, [[(-2, 1), (8, 1)]]*2, 1, 2)
    assert values['target_area_m2'] == 12
    assert values['covered_area_m2'] == 6
    assert values['covered_ratio'] == .5 and values['uncovered_area_m2'] == 6
    assert values['covered_area_m2'] + values['uncovered_area_m2'] == values['target_area_m2']


def test_tiny_uncovered_area_is_not_rounded_to_zero_in_table_or_details(app):
    from gui.compare_panel import ComparePanel
    from gui.result_panel import ResultPanel
    run = dict(total_distance=100., total_turns=2, runtime=.1,
               metadata={'coverage': {'covered_ratio': .999999999, 'uncovered_area_m2': .00002,
                                      'covered_area_m2': 19999.99998, 'target_area_m2': 20000.}})
    df = build_comparison_table({'sample': [run]})
    assert '扫描足迹覆盖率均值 (%)' not in df.index
    assert df.loc['未覆盖面积均值 (m²)', 'sample'] == .00002
    panel = ComparePanel()
    panel.set_data({'d': {'sample': [run]}}, [], {}, None)
    row = next(i for i in range(panel.table.rowCount()) if panel.table.verticalHeaderItem(i).text() == '未覆盖面积均值 (m²)')
    assert float(panel.table.item(row, 0).text()) > 0
    detail = ResultPanel()
    detail.show_run(run)
    assert float(detail.lbl_uncovered.text()) > 0 and '仍有微小未覆盖' in detail.lbl_coverage.text()
    assert any(label.text() == '覆盖率' for label in detail.findChildren(QLabel))
    assert '20000' in detail.lbl_coverage.toolTip()
    assert format_area(0) == '0'
    panel.close()
    detail.close()


def test_named_folder_contains_complete_portable_inputs_results_and_jpeg(experiment, tmp_path):
    from PIL import Image
    ds, source = experiment
    record = deepcopy(source)
    image = tmp_path / 'source.png'
    Image.new('RGB', (16, 16), '#e4efd9').save(image)
    record['datasets'][0].update(bg_image_path=str(image), bg_bounds_utm=(499900, 4399900, 500400, 4400400))
    before = deepcopy(record)
    folder = export_experiment_directory(tmp_path / 'library', record, '覆盖率核对', datetime(2026, 10, 20, 9, 10, 11))
    assert folder.name == '20261020_091011_覆盖率核对'
    assert record == before  # Export never rewrites the in-memory run or original paths.
    raw = json.loads((folder / 'experiment.json').read_text(encoding='utf-8'))
    assert raw['app_version'] == APP_VERSION and raw['experiment_name'] == '覆盖率核对'
    assert raw['project'] == '原工程' and raw['camera'] == source['camera']
    assert raw['combinations'] == source['combinations'] and raw['logs'] == source['logs']
    for name in ('metrics.csv', 'metrics.json', 'experiment.log', 'README.txt', 'assets/background_0.jpg'):
        assert (folder / name).is_file()
    for name in ('result.json', 'segmentation.json', 'segmentation.kml', 'waypoints.csv', 'waypoints.kml',
                 'entry_exit.csv', 'trajectory.jpg', 'segmentation.jpg'):
        assert (folder / 'runs/d0_c0_r0' / name).is_file()
    with Image.open(folder / 'runs/d0_c0_r0/trajectory.jpg') as rendered:
        assert rendered.format == 'JPEG' and rendered.width > 3000
    image.rename(tmp_path / 'source_moved.png')
    moved = folder.rename(tmp_path / 'portable_experiment')
    restored = load_experiment_directory(moved)
    assert Path(restored['datasets'][0]['bg_image_path']).parent == moved / 'assets'
    assert Path(restored['datasets'][0]['bg_image_path']).is_file()
    assert restored['results'][ds.name].keys() == source['results'][ds.name].keys()


def test_folder_export_collisions_and_invalid_names_do_not_overwrite(experiment, tmp_path):
    _, record = experiment
    clock = datetime(2026, 10, 20, 9, 10, 11)
    first = export_experiment_directory(tmp_path, record, '同名实验', clock)
    second = export_experiment_directory(tmp_path, record, '同名实验', clock)
    assert second.name == first.name + ' (2)'
    assert (first / 'experiment.json').read_bytes() == (second / 'experiment.json').read_bytes()
    with pytest.raises(ValueError, match='实验名称'):
        export_experiment_directory(tmp_path, record, '   ')


def test_failed_folder_export_leaves_no_half_record_and_keeps_existing_files(experiment, tmp_path, monkeypatch):
    _, record = experiment
    marker = tmp_path / 'existing.txt'
    marker.write_text('keep', encoding='utf-8')
    def fail(root, data):
        (root / 'partial.json').write_text('{}', encoding='utf-8')
        raise OSError('simulated export failure')
    monkeypatch.setattr('core.experiment_bundle._write_experiment_files', fail)
    with pytest.raises(OSError, match='simulated'):
        export_experiment_directory(tmp_path, record, '失败实验')
    assert list(tmp_path.iterdir()) == [marker] and marker.read_text(encoding='utf-8') == 'keep'


def test_import_copies_full_folder_and_survives_source_move_and_viewer_restart(app, experiment, tmp_path, monkeypatch):
    from core.combinations import ComposedAlgorithm
    _, record = experiment
    source = export_experiment_directory(tmp_path / 'external', record, '外部实验')
    library = tmp_path / 'history'
    stored = import_experiment(source, library)
    assert stored.parent == library
    assert sorted(p.relative_to(source) for p in source.rglob('*') if p.is_file()) == sorted(p.relative_to(stored) for p in stored.rglob('*') if p.is_file())
    source.rename(source.with_name('source_moved'))
    def forbidden(*args, **kwargs):
        raise AssertionError('History viewer attempted to solve an algorithm')
    monkeypatch.setattr(ComposedAlgorithm, 'solve', forbidden)
    HistoryWindow = external_history_module().HistoryWindow
    first = HistoryWindow(library_dir=library)
    assert first.library.count() == 1
    assert first.open_path(stored) == stored
    assert first.info.text().startswith('外部实验')
    assert f'v{APP_VERSION}' in first.windowTitle()
    first.close()
    second = HistoryWindow(library_dir=library)
    assert second.library.count() == 1
    assert second.open_path(stored) == stored and second.run_combo.count() == 2
    second.close()


def test_history_refresh_discovers_new_export_in_default_library(app, experiment, tmp_path):
    _, record = experiment
    window = external_history_module().HistoryWindow(library_dir=tmp_path)
    assert window.library.count() == 0 and window.library_timer.isActive()
    folder = export_experiment_directory(tmp_path, record, '自动发现')
    window.refresh_library()
    assert window.library.count() == 1
    assert window.open_path(folder) == folder
    assert len(list(tmp_path.glob('*/experiment.json'))) == 1  # Opening a stored record does not duplicate it.
    window.close()


@pytest.mark.parametrize('legacy', ['.cppx', '.json'])
def test_legacy_experiments_import_as_permanent_folders(experiment, tmp_path, legacy):
    _, original = experiment
    record = deepcopy(original)
    record['app_version'] = '2.1'
    source = tmp_path / ('legacy' + legacy)
    if legacy == '.cppx':
        export_bundle(source, record)
    else:
        source.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    stored = import_experiment(source, tmp_path / 'history')
    assert stored.is_dir()
    loaded = load_experiment_directory(stored)
    assert loaded['app_version'] == '2.1'  # Historical origin version is preserved.
    assert loaded['results'].keys() == record['results'].keys()
    assert (stored / 'runs/d0_c0_r0/trajectory.jpg').is_file()


def test_invalid_archive_paths_do_not_escape_the_history_library(experiment, tmp_path):
    _, record = experiment
    archive = tmp_path / 'bad.cppx'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('experiment.json', json.dumps(record))
        bundle.writestr('../escaped.txt', 'bad')
    with pytest.raises(ValueError, match='无效文件路径'):
        import_experiment(archive, tmp_path / 'history')
    assert not (tmp_path / 'escaped.txt').exists()
    assert not list((tmp_path / 'history').iterdir())


def test_main_export_prompts_for_name_and_saves_to_history_library(app, experiment, tmp_path, monkeypatch):
    from gui.main_window import MainWindow
    _, record = experiment
    library = tmp_path / 'history'
    monkeypatch.setattr('gui.main_window.HISTORY_EXPERIMENT_DIR', str(library))
    monkeypatch.setattr('gui.main_window.QMessageBox.information', lambda *a: None)
    monkeypatch.setattr('gui.main_window.QMessageBox.warning', lambda *a: None)
    monkeypatch.setattr('gui.main_window.QMessageBox.critical', lambda *a: pytest.fail(str(a)))
    window = MainWindow(dataset_library_dir=tmp_path / 'datasets')
    window._record = deepcopy(record)
    monkeypatch.setattr('gui.main_window.QInputDialog.getText', lambda *a, **kw: ('', False))
    window._export_experiment()
    assert not library.exists()
    monkeypatch.setattr('gui.main_window.QInputDialog.getText', lambda *a, **kw: ('   ', True))
    window._export_experiment()
    assert not library.exists()
    monkeypatch.setattr('gui.main_window.QInputDialog.getText', lambda *a, **kw: ('命名导出测试', True))
    window.experiment_panel.append_log('完整实验日志应保存')
    window._export_experiment()
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    window._export_thread.finished.connect(loop.quit)
    QTimer.singleShot(30000, loop.quit)
    loop.exec()
    assert window._export_thread is None
    folders = list(library.iterdir())
    assert len(folders) == 1 and folders[0].name.endswith('_命名导出测试')
    assert '完整实验日志应保存' in (folders[0] / 'experiment.log').read_text(encoding='utf-8')
    assert window._record['experiment_name'] == '命名导出测试'
    window.close()


def test_copied_standalone_viewer_opens_directory_without_algorithm_sources(experiment, tmp_path):
    import shutil
    from verification.history_location import history_viewer_directory
    _, record = experiment
    experiment_folder = export_experiment_directory(tmp_path / 'exports', record, '纯离线文件夹')
    viewer = tmp_path / 'CopiedViewer'
    shutil.copytree(history_viewer_directory(), viewer, ignore=shutil.ignore_patterns('__pycache__', 'experiments', 'pictures', 'projects'))
    output = tmp_path / 'check.json'
    result = subprocess.run([sys.executable, str(viewer / 'viewer.py'), str(experiment_folder), '--check', str(output)],
        cwd=tmp_path, env=dict(os.environ, PYTHONPATH='', QT_QPA_PLATFORM='offscreen'), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    checked = json.loads(output.read_text(encoding='utf-8'))
    assert checked['standalone'] and not checked['algorithm_modules_loaded'] and checked['experiment_loaded']
    assert Path(checked['library_directory']) == viewer / 'experiments'
    assert len(list((viewer / 'experiments').glob('*/experiment.json'))) == 1


def test_version_is_consistent_in_app_project_and_independent_viewer():
    assert APP_VERSION == Project().to_dict()['version']
    config = Path(__file__).parent / 'HistoryViewer/runtime/config/default_params.py'
    assert f'APP_VERSION = "{APP_VERSION}"' in config.read_text(encoding='utf-8')
