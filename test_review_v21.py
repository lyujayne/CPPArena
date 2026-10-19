"""Independent hand-calculated metric, rendering and UI workflow regressions."""
import os
from copy import deepcopy
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication, QAbstractItemView
from data.dataset import Dataset
from compare.metrics import count_turns, path_length
from compare.route_metrics import compute_route_metrics, attach_route_metrics

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

def example():
    ds = Dataset('hand calculated')
    ds.add_region('a', [(0, 0), (4, 0), (4, 2), (0, 2)])
    ds.add_region('b', [(6, 0), (10, 0), (10, 2), (6, 2)])
    ds.launch_point = (-2, 1)
    paths = [[(0, 1), (4, 1)], [(6, 1), (10, 1)]]
    points = [ds.launch_point] + paths[0] + paths[1] + [ds.launch_point]
    run = dict(algorithm='Bayazit × ACO', total_distance=24., total_turns=1, seed=42, runtime=.1,
        waypoints=points, internal_paths=paths, convergence=[24.],
        subregion_sequence=[dict(order=i+1, entry=p[0], exit=p[-1], polygon=r.vertices, scan_segments=[p])
                            for i, (r, p) in enumerate(zip(ds.regions, paths))],
        metadata={'turn_metrics': {'sweep_reversals': 0}},
        combination={'decomposition': 'Bayazit', 'planning': 'ACO'})
    return ds, run

def test_route_metrics_are_exact_for_repeated_and_outside_legs():
    ds, run = example()
    values = compute_route_metrics(run, ds)
    assert values['executed_distance_m'] == 24
    assert values['subregion_transfer_m'] == 2  # Excludes both launch legs.
    assert values['outside_distance_m'] == 8  # Repeated portions count on each flight.
    assert values['redundancy_pct'] == 50
    assert values['scan_distance_m'] == 8
    assert values['non_scan_distance_m'] == 16
    assert values['sweep_reversals'] == 0
    assert values['scan_distance_m'] + values['non_scan_distance_m'] == values['executed_distance_m']
    assert values['subregion_transfer_m'] <= values['non_scan_distance_m']

@pytest.mark.parametrize('points,ratio', [
    ([(0, 0), (4, 0), (1, 0)], 300/7),
    ([(0, 0), (2, 2), (0, 2), (2, 0)], 0),
    ([(0, 0), (0, 0)], 0),
])
def test_redundancy_counts_retracing_but_not_crossings(points, ratio):
    assert compute_route_metrics({'waypoints': points})['redundancy_pct'] == pytest.approx(ratio)

def test_duplicate_waypoint_does_not_hide_a_real_turn():
    assert count_turns([(0, 0), (1, 0), (1, 0), (1, 1)]) == 1

def test_missing_old_geometry_is_unknown_instead_of_zero_redundancy():
    values = compute_route_metrics({'total_distance': 100, 'metadata': None})
    assert 'redundancy_pct' not in values and 'outside_distance_m' not in values
    run = {'waypoints': [(0, 0), (1, 0)], 'metadata': None}
    assert attach_route_metrics(run)['executed_distance_m'] == 1

def test_coverage_uses_target_union_and_actual_chosen_scan_footprints():
    from compare.coverage_metrics import evaluate_coverage
    ds = Dataset()
    ds.add_region('a', [(0, 0), (4, 0), (4, 2), (0, 2)])
    ds.add_region('b', [(0, 2), (4, 2), (4, 4), (0, 4)])
    result = evaluate_coverage(ds.regions, [[(0, 2), (4, 2)]], 4, 1)
    assert result['covered_ratio'] == 1 and result['uncovered_area_m2'] == 0
    ds.add_region('overlapping input', [(0, 0), (4, 0), (4, 2), (0, 2)])
    assert evaluate_coverage(ds.regions, [[(0, 2), (4, 2)]], 4, 1)['covered_ratio'] == 1

def test_decomposition_metrics_handle_split_edges_and_reject_overlaps():
    from gui.decomp_compare import _cut_info, compute_metrics, METRIC_DEFS
    original = [(0, 0), (4, 0), (4, 4), (0, 4)]
    pieces = [[(0, 0), (2, 0), (2, 4), (0, 4)],
              [(2, 0), (4, 0), (4, 2), (2, 2)], [(2, 2), (4, 2), (4, 4), (2, 4)]]
    assert _cut_info(original, pieces)[0] == 6
    values = compute_metrics([dict(verts=original, pieces=pieces, runtime=.3)])
    assert values['valid'] and values['n_cells'] == 3 and values['coverage'] == 100
    assert values['width_sum'] == 6 and values['n_steiner'] == 4
    assert values['area_cv'] == pytest.approx(35.3553390593)
    assert values['runtime'] == .3
    assert not compute_metrics([dict(verts=original, pieces=[original, original])])['valid']
    assert all(direction is None for key, _, _, direction, _ in METRIC_DEFS
               if key in ('area_cv', 'regularity', 'cut_length', 'n_steiner'))

def test_live_progress_does_not_flood_log_and_errors_are_red(app):
    from gui.experiment_panel import ExperimentPanel
    panel = ExperimentPanel()
    panel.set_progress(0, 1, '启动计算进程：FA3ACO')
    for i in range(500):
        panel.set_progress(0, 1, f'FA3ACO 第{i+1}/500代：构建/3-opt蚂蚁 77/80')
    assert panel.log.document().blockCount() == 1
    assert '500/500' in panel.status_label.text()
    panel.set_progress(1, 1, '组合：失败 ValueError: bad input')
    assert panel.log.document().blockCount() == 2
    fragment = panel.log.document().lastBlock().begin().fragment()
    assert fragment.charFormat().foreground().color().name() == '#b91c1c'
    panel.append_log('下一组合启动')
    fragment = panel.log.document().lastBlock().begin().fragment()
    assert fragment.charFormat().foreground().color().name() == '#22354b'
    panel.random_seed_count.setValue(20)
    panel.randomize_seeds()
    assert len(set(panel.seeds())) == 20
    assert all(0 <= seed < 2**32 for seed in panel.seeds())
    panel.close()

def test_baseline_changes_table_and_scrollbar_moves_by_pixels(app, monkeypatch):
    from gui.compare_panel import ComparePanel
    ds, run = example()
    second = deepcopy(run)
    second['total_distance'] = 12.
    panel = ComparePanel()
    values = {ds.name: {f'combo{i}': [deepcopy(run)] for i in range(9)}}
    values[ds.name]['short'] = [second]
    panel.set_data(values, [ds], {}, None)
    panel.resize(900, 800)
    panel.show()
    app.processEvents()
    assert panel.table.horizontalScrollMode() == QAbstractItemView.ScrollPerPixel
    scrollbar = panel.table.horizontalScrollBar()
    assert scrollbar.maximum() > 200
    scrollbar.setValue(43)
    assert scrollbar.value() == 43
    redraws = []
    monkeypatch.setattr(panel, '_rebuild_convergence', lambda: redraws.append(1))
    monkeypatch.setattr(panel, '_rebuild_stats', lambda: redraws.append(2))
    panel.baseline_combo.setCurrentIndex(panel.baseline_combo.findData('combo0'))
    row = next(i for i in range(panel.table.rowCount()) if panel.table.verticalHeaderItem(i).text() == '相对基线距离改善率 (%)')
    assert panel.table.item(row, 9).text() == '50'
    assert not redraws
    assert any(panel.table.verticalHeaderItem(i).text() == '非扫描航程均值 (m)' for i in range(panel.table.rowCount()))
    panel.close()

def test_canvas_dataset_switch_preserves_results_and_syncs_both_selectors(app, tmp_path):
    from gui.main_window import MainWindow
    ds, run = example()
    other = Dataset.from_dict(ds.to_dict())
    other.id, other.name = 'second-id', 'second dataset'
    window = MainWindow(dataset_library_dir=tmp_path / 'library')
    window.project.datasets = [ds, other]
    window.results = {ds.name: {'one': [run]}, other.name: {'two': [run]}}
    window._set_active_dataset(ds)
    window.canvas_dataset_combo.setCurrentIndex(1)
    assert window.active_dataset is other
    assert window.dataset_combo.currentIndex() == 1
    assert set(window.canvas._results) == {'two'}
    assert window.run_combo.count() == 2
    window.dataset_combo.setCurrentIndex(0)
    assert window.canvas_dataset_combo.currentIndex() == 0 and window.active_dataset is ds
    window.close()

def test_decomposition_paging_reuses_calculation_and_has_metric_tab(app, monkeypatch):
    import gui.decomp_compare as module
    ds, _ = example()
    for i in range(2):
        ds.add_region(f'extra{i}', [(20+i*5, 0), (24+i*5, 0), (24+i*5, 4), (20+i*5, 4)])
    original = module.decompose_region_with
    calls = []
    def compute(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(module, 'decompose_region_with', compute)
    dialog = module.DecompCompareDialog(ds, ['Bayazit', 'Enhanced-ECD'])
    assert len(calls) == 8 and len(dialog.figure.axes) == 6
    dialog.page_spin.setValue(2)
    assert len(dialog.figure.axes) == 2 and len(calls) == 8
    dialog.region_filter.setCurrentIndex(1)
    assert not dialog.page_spin.isEnabled() and len(dialog.figure.axes) == 2
    dialog._show_metrics()
    assert dialog.tabs.currentIndex() == 1
    assert dialog.metric_table.item(0, 1).text() == '4'
    dialog.close()

def test_separate_overlay_and_toolbar_exports_are_real_high_resolution_jpeg(app, tmp_path):
    from PIL import Image
    from gui.route_export_dialog import export_route_images, RouteExportDialog
    from core.image_export import save_jpeg
    from matplotlib.figure import Figure
    ds, run = example()
    second = deepcopy(run)
    second['combination']['planning'] = 'Li-DP'
    runs = {'first': run, 'second': second}
    separate = export_route_images(tmp_path, ds, runs)
    assert [p.name for p in separate] == ['Bayazit + ACO.jpg', 'Bayazit + Li-DP.jpg']
    overlay = export_route_images(tmp_path, ds, runs, overlay=True)[0]
    assert overlay.name == '1Bayazit + ACO｜2Bayazit + Li-DP.jpg'
    assert export_route_images(tmp_path, ds, {'first': run})[0].name == 'Bayazit + ACO (2).jpg'
    for path in separate + [overlay]:
        with Image.open(path) as image:
            assert image.format == 'JPEG' and image.width > 3500
    target = save_jpeg(Figure(figsize=(2, 2)), tmp_path / 'requested.png')
    assert Path(target).suffix == '.jpg' and not (tmp_path / 'requested.png').exists()
    chooser = RouteExportDialog(list(runs), selected='first')
    assert chooser.selected_labels() == ['first']
    chooser.mode.setCurrentIndex(2)
    assert chooser.selected_labels() == ['first', 'second']
    chooser.close()
