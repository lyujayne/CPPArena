"""Generate reviewable UI, selected-route and Markdown artifacts from real jobs."""
import os
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QListWidget, QCheckBox
    from gui.theme import apply_theme
    from gui.component_dialog import ComponentInstallDialog
    import gui.main_window as module
    from core.combinations import Combination
    from data.dataset import Dataset
    output = root / 'verification/review'
    output.mkdir(parents=True, exist_ok=True)
    module.EXPERIMENT_DIR = str(output)
    app = QApplication([])
    apply_theme(app)
    with TemporaryDirectory(prefix='cpp_workflow_') as library:
        window = module.MainWindow(dataset_library_dir=library)
        datasets = []
        for name, offset in [('验收田块 A', 0), ('验收田块 B', 500)]:
            ds = Dataset(name)
            ds.add_region('L 形田块', [(500000+offset+x, 4400000+y) for x, y in
                [(0, 0), (400, 0), (400, 140), (140, 140), (140, 400), (0, 400)]])
            ds.launch_point = (499970+offset, 4399970)
            window._append_dataset(ds)
            datasets.append(ds)
        window._set_active_dataset(datasets[0])
        combos = [Combination('Bayazit', 'ACO', planning_params={'max_iterations': 3}, dataset_ids=[datasets[0].id]),
                  Combination('Enhanced-ECD', 'Li-DP', dataset_ids=[datasets[0].id, datasets[1].id])]
        panel = window.experiment_panel
        panel.combinations = combos
        panel.refresh_table()
        window.show()
        window.run_experiment()
        deadline = time.monotonic()+30
        while window._thread is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert window._thread is None
        assert len(window._record['combinations']) == 2
        assert list(window.results[datasets[1].name]) == [combos[1].label]
        assert all(not run.get('error') for algos in window.results.values() for runs in algos.values() for run in runs)
        window.run_combo.setCurrentIndex(1)
        window.decomp_check.setChecked(True)
        window.canvas.fit_view()
        panel.append_log('验收示例：错误信息以红色显示', error=True)
        app.processEvents()
        window.grab().save(str(output / 'main_window.jpg'), 'JPG', 98)
        window._open_comparison()
        app.processEvents()
        comparison = window.compare_panel
        assert comparison.table.columnCount() == 2 and comparison.table.rowCount() > 8
        window.comparison_window.grab().save(str(output / 'comparison_table.jpg'), 'JPG', 98)
        comparison.tabs.setCurrentIndex(1)
        app.processEvents()
        window.comparison_window.grab().save(str(output / 'convergence.jpg'), 'JPG', 98)
        comparison.tabs.setCurrentIndex(2)
        app.processEvents()
        window.comparison_window.grab().save(str(output / 'statistics.jpg'), 'JPG', 98)
        with patch('gui.compare_panel.QMessageBox.information'), patch('gui.compare_panel.QMessageBox.warning') as error:
            with patch('gui.compare_panel.QFileDialog.getSaveFileName', return_value=(str(output / 'selected_route.jpg'), '')):
                comparison.wp_algo_combo.setCurrentIndex(1)
                comparison.export_route_image()
            with patch('gui.compare_panel.QFileDialog.getSaveFileName', return_value=(str(output / 'summary.md'), '')):
                comparison.generate_report()
            assert not error.called, error.call_args
        window.comparison_window.close()
        from gui.route_export_dialog import RouteExportDialog, export_route_images
        runs = {label: comparison._best_run(label) for label in comparison._active_runs()}
        export_route_images(output / 'batch', datasets[0], runs)
        export_route_images(output / 'batch', datasets[0], runs, overlay=True)
        chooser = RouteExportDialog(list(runs), parent=window)
        chooser.show()
        app.processEvents()
        chooser.grab().save(str(output / 'batch_export.jpg'), 'JPG', 98)
        chooser.close()
        from gui.decomp_compare import DecompCompareDialog
        ds = datasets[0]
        for i in range(3):
            ds.add_region(f'分页验证地块 {i+2}', [(500500+i*150+x, 4400000+y) for x, y in [(0, 0), (100, 0), (100, 120), (0, 120)]])
        decomp = DecompCompareDialog(ds, ['Bayazit', 'Enhanced-ECD'], parent=window)
        decomp.show()
        app.processEvents()
        decomp.grab().save(str(output / 'decomposition.jpg'), 'JPG', 98)
        decomp._show_metrics()
        app.processEvents()
        decomp.grab().save(str(output / 'decomposition_metrics.jpg'), 'JPG', 98)
        decomp.close()
        def dataset_dialog():
            dialog = app.activeModalWidget()
            dialog.findChild(QCheckBox).setChecked(False)
            dialog.grab().save(str(output / 'dataset_selection.jpg'), 'JPG', 98)
            dialog.findChild(QDialogButtonBox).accepted.emit()
        QTimer.singleShot(100, dataset_dialog)
        panel.edit_datasets(combos[0])
        installer = ComponentInstallDialog('planning', window)
        installer.show()
        app.processEvents()
        installer.grab().save(str(output / 'add_algorithm.jpg'), 'JPG', 98)
        installer.close()
        window.close()
    print('Verified assigned jobs, exports and UI:', output)


if __name__ == '__main__':
    main()
