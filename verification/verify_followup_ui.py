"""Generate source-only follow-up screenshots and an offline experiment example."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))


def main():
    import math
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from gui.theme import apply_theme
    import gui.main_window as main_module
    from core.base_algorithm import CameraParams
    from core.combinations import Combination, build_combination_jobs
    from core.experiment_runner import ExperimentRunner
    from core.experiment_bundle import export_bundle
    from data.dataset import Dataset
    output = root / 'verification' / 'followup'
    output.mkdir(exist_ok=True)
    main_module.EXPERIMENT_DIR = str(output)
    ds = Dataset('子区内扫描与入出口示例')
    angle = math.radians(19)
    rotate = lambda x, y: (500000+x*math.cos(angle)-y*math.sin(angle),
                            4400000+x*math.sin(angle)+y*math.cos(angle))
    ds.add_region('L形地块', [rotate(x, y) for x, y in [(0, 0), (400, 0), (400, 140), (140, 140), (140, 400), (0, 400)]])
    ds.launch_point = rotate(-40, -40)
    camera = CameraParams().as_dict()
    combos = [Combination('Bayazit', 'ACO', planning_params={'max_iterations': 3}),
              Combination('Bayazit', 'Li-DP', planning_params={'li_adjacency_mode': 0})]
    runner = ExperimentRunner()
    results = runner.run_jobs(build_combination_jobs(combos, [ds], [42], camera))
    assert all(not run.get('error') for values in results.values() for runs in values.values() for run in runs)
    app = QApplication([])
    apply_theme(app)
    window = main_module.MainWindow(dataset_library_dir=output / 'test_library')
    window.project.datasets = [ds]
    window.project.name = '后续修正验证'
    window._set_active_dataset(ds)
    window._run_datasets, window._run_combinations = [ds], combos
    window._pending = ('combinations', [42], camera)
    window.experiment_panel.combinations = combos
    window.experiment_panel.refresh_table()
    window._on_experiment_done(results)
    window.run_combo.setCurrentIndex(1)
    window.decomp_check.setChecked(True)
    window.canvas.fit_view()
    window.show()
    app.processEvents()
    window.grab().save(str(output / 'main_window.png'))
    assert window.right_tabs.count() == 1
    window._open_comparison()
    app.processEvents()
    assert window.comparison_window.isVisible()
    window.comparison_window.grab().save(str(output / 'comparison_window.png'))
    window.comparison_window.close()
    def capture_dialog():
        dialog = app.activeModalWidget()
        dialog.grab().save(str(output / 'add_combination.png'))
        dialog.reject()
    QTimer.singleShot(100, capture_dialog)
    window.experiment_panel.add_dialog()
    record = window._record
    record['view'] = window._view_state()
    export_bundle(output / 'entry_exit_demo.cppx', record)
    window.close()
    print('Screenshots and experiment saved to', output)


if __name__ == '__main__':
    main()
