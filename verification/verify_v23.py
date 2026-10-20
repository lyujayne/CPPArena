"""Real new algorithms, Qt UI, JPEG export and offline v2.3 history replay."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QComboBox, QDialog
    from core.base_algorithm import CameraParams
    from core.combinations import Combination, build_combination_jobs
    from core.experiment_runner import ExperimentRunner
    from core.experiment_bundle import make_record, export_experiment_directory
    from gui.main_window import MainWindow
    from gui.decomp_compare import DecompCompareDialog
    from gui.route_export_dialog import export_route_images
    from gui.theme import apply_theme
    from data.dataset import Dataset
    from verification.history_location import history_viewer_directory

    output = root/'verification/v2.3'
    output.mkdir(parents=True, exist_ok=True)
    ds = Dataset('v2.3新增算法验收')
    ds.add_region('凹形任务区域', [(685000, 8805000), (685300, 8805000), (685300, 8805120),
        (685180, 8805120), (685180, 8805300), (685000, 8805300)])
    ds.launch_point = (684950, 8804950)
    combos = [Combination(d, p, planning_params={'population_size': 16, 'max_iterations': 12})
        for d, p in zip(('IEE-MILP', 'Greene', 'RGS', 'TD-DP'), ('DBO', 'SSA', 'GS-IPSO', 'IDGWO-VNS'))]
    camera = CameraParams().as_dict()
    runs = ExperimentRunner().run_jobs_isolated(build_combination_jobs(combos, [ds], [42], camera))
    assert all(not r.get('error') for values in runs[ds.name].values() for r in values)
    app = QApplication([])
    apply_theme(app)
    with TemporaryDirectory(prefix='cpp_v23_dataset_') as library:
        window = MainWindow(dataset_library_dir=library)
        window._append_dataset(ds)
        window._set_active_dataset(ds)
        window.experiment_panel.combinations = combos
        window.experiment_panel.refresh_table()
        window._run_datasets, window._run_combinations = [ds], combos
        window._pending = ('combinations', [42], camera)
        # Avoid the completion handler's automatic raw snapshot in the user's library.
        import gui.main_window as main_module
        main_module.EXPERIMENT_DIR = str(output)
        window._on_experiment_done(runs)
        window.run_combo.setCurrentIndex(1)
        window.decomp_algo_combo.setCurrentIndex(window.decomp_algo_combo.findData('IEE-MILP'))
        window.decomp_check.setChecked(True)
        window.canvas.fit_view()
        window.show()
        app.processEvents()
        window.grab().save(str(output/'main_new_algorithms.jpg'), 'JPG', 98)

        def inspect_add_dialog():
            dialog = app.activeModalWidget()
            assert isinstance(dialog, QDialog)
            selectors = dialog.findChildren(QComboBox)
            selectors[0].setCurrentIndex(selectors[0].findData('IEE-MILP'))
            selectors[1].setCurrentIndex(selectors[1].findData('GS-IPSO'))
            app.processEvents()
            dialog.grab().save(str(output/'add_combination.jpg'), 'JPG', 98)
            dialog.reject()
        QTimer.singleShot(100, inspect_add_dialog)
        window.experiment_panel.add_dialog()
        dialog = DecompCompareDialog(ds, ['TD', 'Hertel-Mehlhorn', 'IEE-MILP', 'Greene', 'RGS', 'TD-DP'])
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(output/'decompositions.jpg'), 'JPG', 98)
        dialog.close()
        window._open_comparison()
        app.processEvents()
        window.comparison_window.grab().save(str(output/'comparison.jpg'), 'JPG', 98)
        window.comparison_window.close()
        best = {label: values[0] for label, values in runs[ds.name].items()}
        exports = export_route_images(output/'routes', ds, best)
        assert len(exports) == 4 and all(p.suffix == '.jpg' for p in exports)
        record = make_record('v2.3', [ds], camera, combos, runs, '四种新增规划实际运行完成')
        folder = export_experiment_directory(output/'experiments', record, '新增分割与群智能规划')
        spec = importlib.util.spec_from_file_location('_history_v23_verify',
            history_viewer_directory()/'runtime/gui/history_window.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        viewer = module.HistoryWindow(library_dir=output/'experiments')
        viewer.open_path(folder)
        viewer.show()
        app.processEvents()
        viewer.grab().save(str(output/'history_replay.jpg'), 'JPG', 98)
        assert viewer._record['app_version'] == '2.3'
        viewer.close()
        window.close()
        (output/'verification.json').write_text(json.dumps({
            'app_version': '2.3', 'experiment_folder': str(folder),
            'combinations': [c.to_dict() for c in combos],
            'distances': {label: r['total_distance'] for label, r in best.items()},
            'operator_counts': {label: r['metadata']['gtsp']['operator_counts'] for label, r in best.items()},
            'verified': ['actual spawned algorithms', 'Qt UI', 'new decomposition comparison',
                         'four JPEG exports', 'complete folder', 'offline replay']},
            ensure_ascii=False, indent=2), encoding='utf-8')
    print('Verified v2.3 UI/export/history:', output)


if __name__ == '__main__':
    main()
