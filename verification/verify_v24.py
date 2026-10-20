"""Fixed UI and real batch export; generated files stay in an isolated library."""
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
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    from core.base_algorithm import CameraParams
    from core.combinations import Combination, build_combination_jobs
    from core.experiment_runner import ExperimentRunner
    from gui.theme import apply_theme
    from test_upgrade_v21 import metric_dataset
    import gui.main_window as module

    output = root/'verification/v2.4'
    output.mkdir(parents=True, exist_ok=True)
    module.EXPERIMENT_DIR = str(output)
    module.HISTORY_EXPERIMENT_DIR = str(output/'experiments')
    ds = metric_dataset()
    combos = [Combination('Bayazit', 'ACO', planning_params={'max_iterations': 3}),
              Combination('TD', 'DBO', planning_params={'population_size': 8, 'max_iterations': 3})]
    camera, seeds = CameraParams().as_dict(), list(range(12))
    results = ExperimentRunner().run_jobs(build_combination_jobs(combos, [ds], seeds, camera))
    assert all(not run.get('error') for values in results[ds.name].values() for run in values)
    # Error-only records exercise the full table and export without inventing
    # successful trajectories. The 24 successful runs above are actual solves.
    results[ds.name]['完全失败组合'] = [dict(seed=i, error='模拟DP规模错误：子区超过精确上限',
                                           total_distance=None) for i in range(300)]
    app = QApplication([])
    apply_theme(app)
    with TemporaryDirectory(prefix='cpp_v24_') as datasets:
        window = module.MainWindow(dataset_library_dir=datasets)
        window._append_dataset(ds)
        window._set_active_dataset(ds)
        window.experiment_panel.combinations = [Combination('TD', 'DBO') for _ in range(100)]
        window.experiment_panel.refresh_table()
        window._run_datasets, window._run_combinations = [ds], combos
        window._pending = ('combinations', seeds, camera)
        window._on_experiment_done(results)
        window.show()
        window.experiment_panel.set_running(True)
        app.processEvents()
        window.experiment_panel.table.verticalScrollBar().setValue(1200)
        app.processEvents()
        window.grab().save(str(output/'running_scroll.jpg'), 'JPG', 98)
        assert window.experiment_panel.table.isEnabled()
        window.experiment_panel.set_running(False)
        window._open_comparison()
        app.processEvents()
        window.comparison_window.grab().save(str(output/'failure_table.jpg'), 'JPG', 98)
        window.compare_panel.failure_label.verticalScrollBar().setValue(900)
        app.processEvents()
        window.comparison_window.grab().save(str(output/'errors_scrolled.jpg'), 'JPG', 98)
        window.comparison_window.close()
        ticks, samples = [], []
        timer = QTimer()
        def heartbeat():
            ticks.append(1)
            if window._export_dialog and len(ticks) == 30:
                window._export_dialog.grab().save(str(output/'export_progress.jpg'), 'JPG', 98)
            # Optional diagnostics only; psutil is not a runtime dependency.
            try:
                import psutil
                children = psutil.Process().children()
                if children:
                    samples.append(max(child.memory_info().rss for child in children)/1024**2)
            except (ImportError, OSError):
                pass
        timer.timeout.connect(heartbeat)
        timer.start(20)
        with patch('gui.main_window.QInputDialog.getText', return_value=('v2.4大规模完整导出验收', True)), \
                patch('gui.main_window.QMessageBox.information'), \
                patch('gui.main_window.QMessageBox.critical') as errors:
            window._export_experiment()
            loop = QEventLoop()
            window._export_thread.finished.connect(loop.quit)
            QTimer.singleShot(180000, loop.quit)
            loop.exec()
            assert window._export_thread is None and not errors.called, errors.call_args
        timer.stop()
        assert len(ticks) > 20
        folder = max((output/'experiments').iterdir(), key=lambda p: p.stat().st_mtime_ns)
        assert len(list(folder.glob('runs/*/result.json'))) == 324
        assert len(list(folder.glob('runs/*/trajectory.jpg'))) == 24
        assert len(list(folder.glob('runs/*/segmentation.jpg'))) == 24
        (output/'verification.json').write_text(json.dumps({
            'version': '2.4', 'folder': str(folder), 'successful_runs': 24, 'failure_records': 300,
            'jpeg_images': 48, 'ui_heartbeat_ticks': len(ticks),
            'child_peak_rss_mb': max(samples) if samples else None,
            'all_runs_preserved': True, 'fixed_errors_px': window.compare_panel.failure_label.height(),
            'algorithm_areas_px': [scroll.parentWidget().height() for scroll in window.experiment_panel.algorithm_scrolls]
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        window.close()
    print('Verified v2.4 fixed UI and 324-run complete export:', output)


if __name__ == '__main__':
    main()
