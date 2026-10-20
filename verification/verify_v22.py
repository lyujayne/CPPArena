"""Reviewable v2.2 coverage and named-folder replay from real solver results."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from core.base_algorithm import CameraParams
    from core.combinations import Combination, build_combination_jobs
    from core.experiment_runner import ExperimentRunner
    from core.experiment_bundle import load_experiment_directory
    from data.dataset import Dataset
    from gui.theme import apply_theme
    from verification.history_location import history_viewer_directory
    import gui.main_window as module

    output = root / 'verification/v2.2'
    output.mkdir(parents=True, exist_ok=True)
    module.EXPERIMENT_DIR = str(output)
    module.HISTORY_EXPERIMENT_DIR = str(output / 'experiments')
    camera = CameraParams(side_overlap_pct=0).as_dict()
    ds = Dataset('尖角漏扫验收')
    ds.add_region('尖三角形', [(500000, 4400000), (501000, 4400000), (500000, 4400090)])
    ds.launch_point = (499960, 4399960)
    combos = [Combination('Bayazit', 'ACO', planning_params={'max_iterations': 3}),
              Combination('Enhanced-ECD', 'Li-DP')]
    results = ExperimentRunner().run_jobs(build_combination_jobs(combos, [ds], [42], camera))
    assert all(not run.get('error') for runs in results[ds.name].values() for run in runs)
    assert all(run['metadata']['coverage']['uncovered_area_m2'] > 0 for runs in results[ds.name].values() for run in runs)
    app = QApplication([])
    apply_theme(app)
    with TemporaryDirectory(prefix='cpp_v22_datasets_') as datasets:
        window = module.MainWindow(dataset_library_dir=datasets)
        window._append_dataset(ds)
        window._set_active_dataset(ds)
        window.camera_panel.set_camera(camera)
        window.experiment_panel.combinations = combos
        window.experiment_panel.refresh_table()
        window._run_datasets, window._run_combinations = [ds], combos
        window._pending = ('combinations', [42], camera)
        window._on_experiment_done(results)
        window.run_combo.setCurrentIndex(1)
        window.decomp_check.setChecked(True)
        window.canvas.fit_view()
        window.show()
        app.processEvents()
        window.grab().save(str(output / 'main_coverage.jpg'), 'JPG', 98)

        def name_dialog():
            dialog = app.activeModalWidget()
            dialog.setTextValue('v2.2 覆盖率与文件夹验收')
            dialog.grab().save(str(output / 'experiment_name.jpg'), 'JPG', 98)
            dialog.accept()
        QTimer.singleShot(100, name_dialog)
        with patch('gui.main_window.QMessageBox.information'), patch('gui.main_window.QMessageBox.critical') as error:
            window._export_experiment()
            from PySide6.QtCore import QEventLoop
            loop = QEventLoop()
            window._export_thread.finished.connect(loop.quit)
            QTimer.singleShot(60000, loop.quit)
            loop.exec()
            assert window._export_thread is None
            assert not error.called, error.call_args
        folder = max((output / 'experiments').iterdir(), key=lambda p: p.stat().st_mtime_ns)
        record = load_experiment_directory(folder)
        assert record['experiment_name'] == 'v2.2 覆盖率与文件夹验收'
        assert record['app_version'] == '2.2'
        window._open_comparison()
        app.processEvents()
        window.comparison_window.grab().save(str(output / 'comparison_coverage.jpg'), 'JPG', 98)
        window.comparison_window.close()

        spec = importlib.util.spec_from_file_location('_history_v22_verify',
            history_viewer_directory() / 'runtime/gui/history_window.py')
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        viewer = history.HistoryWindow(library_dir=output / 'experiments')
        viewer.show()
        viewer.open_path(folder)
        app.processEvents()
        viewer.grab().save(str(output / 'history_folder_replay.jpg'), 'JPG', 98)
        assert viewer._record['experiment_name'] == record['experiment_name']
        viewer._open_comparison()
        app.processEvents()
        viewer.comparison_window.grab().save(str(output / 'history_comparison.jpg'), 'JPG', 98)
        viewer.close()
        window.close()
        summary = {'version': '2.2', 'named_folder': folder.name,
                   'coverage': {label: runs[0]['metadata']['coverage'] for label, runs in results[ds.name].items()},
                   'verified': ['name prompt', 'complete directory', 'permanent library', 'offline folder replay', 'positive uncovered area']}
        (output / 'verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Verified real v2.2 named-folder export and replay:', output)


if __name__ == '__main__':
    main()
