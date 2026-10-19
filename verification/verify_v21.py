"""Generate inspectable acceptance artifacts with real, reduced-budget runs."""
import os
import sys
import json
import multiprocessing
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))


def main():
    from core.base_algorithm import CameraParams
    from core.combinations import DECOMPOSITIONS, PLANNERS, enumerate_combinations, build_combination_jobs
    from core.experiment_runner import ExperimentRunner
    from core.experiment_bundle import export_bundle, load_bundle, dump_json
    from data.dataset import Dataset
    from PySide6.QtWidgets import QApplication
    from gui.theme import apply_theme
    import gui.main_window as main_module
    import importlib.util
    from verification.history_location import history_viewer_directory
    spec = importlib.util.spec_from_file_location('_independent_history_verification',
        history_viewer_directory() / 'runtime/gui/history_window.py')
    history_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(history_module)
    output = root / 'verification' / 'v2.1'
    output.mkdir(parents=True, exist_ok=True)
    ds = Dataset('验收示例（合成 L 形地块）')
    ds.add_region('L形地块', [(500000, 4400000), (500300, 4400000),
        (500300, 4400100), (500100, 4400100), (500100, 4400300), (500000, 4400300)])
    ds.launch_point = (499970, 4399970)
    camera = CameraParams().as_dict()
    combos = enumerate_combinations(DECOMPOSITIONS, PLANNERS)
    for combo in combos:
        if combo.decomposition == 'PSO-DCAS':
            combo.decomposition_params.update(pso_swarm_size=10, pso_iterations=4)
        if combo.planning != 'Li-DP':
            combo.planning_params['max_iterations'] = 3
        if combo.planning == 'FA3ACO':
            combo.planning_params['ants_count'] = 4
    runner = ExperimentRunner()
    runner.registry.load_builtins()
    messages = []
    results = runner.run_jobs_isolated(build_combination_jobs(combos, [ds], [42], camera),
        lambda done, total, message: messages.append((done, total, message)))
    assert len(results[ds.name]) == 9
    assert all(not run.get('error') for values in results.values() for runs in values.values() for run in runs)
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    main_module.EXPERIMENT_DIR = str(output)
    window = main_module.MainWindow(dataset_library_dir=output / 'test_library')
    window.project.name = 'v2.1 验收 · 缩短迭代预算'
    window.project.datasets = [ds]
    window._set_active_dataset(ds)
    window._run_datasets, window._run_combinations = [ds], combos
    window._pending = ('combinations', [42], camera)
    window.experiment_panel.combinations = combos
    window.experiment_panel.refresh_table()
    for done, total, message in messages:
        window.experiment_panel.set_progress(done, total, message)
    window._on_experiment_done(results)
    window.run_combo.setCurrentIndex(1)
    window.decomp_check.setChecked(True)
    window.right_tabs.setCurrentWidget(window.result_panel)
    window.canvas.fit_view()
    window.show()
    app.processEvents()
    window.grab().save(str(output / 'main_window.png'))
    record = window._record
    record['view'] = window._view_state()
    bundle = output / 'acceptance_9_combinations.cppx'
    export_bundle(bundle, record)
    assets = output / 'replay_assets'
    assets.mkdir(exist_ok=True)
    restored = load_bundle(bundle, assets)
    history_module.EXPERIMENT_DIR = str(output)
    history = history_module.HistoryWindow()
    history.library.setCurrentItem(history._add_path(bundle))
    history.open_path(bundle)
    history.show()
    app.processEvents()
    history.grab().save(str(output / 'history_window.png'))
    summary = {'version': '2.1', 'pairs_executed': 9, 'successful': 9,
        'budget': {'aco_iterations': 3, 'fa3aco_ants': 4, 'pso_iterations': 4, 'pso_swarm': 10},
        'complete_archive': bundle.name, 'main_screenshot': 'main_window.png',
        'history_screenshot': 'history_window.png',
        'note': 'Synthetic metric L-shaped geometry; validation budgets do not change production defaults.'}
    dump_json(output / 'acceptance_summary.json', summary)
    print(json.dumps(summary, ensure_ascii=True))
    history.close()
    window.close()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
