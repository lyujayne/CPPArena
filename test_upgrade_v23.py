"""v2.3 geometry invariants, real search operators and full component integration."""
import itertools
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
from shapely import affinity
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
from algorithms.decomposition_methods import (TDDecomposition, HMDecomposition,
    IEEDecomposition, GreeneDecomposition, RGSDecomposition, TDDPDecomposition,
    _iee_cells, _merge_candidates, _td, _td_dp)
from algorithms.swarm_planners import (DBOPlanner, SSAPlanner, GSIPSOPlanner,
    IDGWOVNSPlanner, OrderEvaluator, _perturb, _cross, _swaps_towards, _apply_velocity)
from algorithms.aco.aco_gtsp import tour_distance, validate_visit
from core.base_algorithm import CPPInput, Region, CameraParams
from core.combinations import (Combination, ComposedAlgorithm, DECOMPOSITIONS,
    PLANNERS, component_defaults, component_spec, build_combination_jobs)
from core.execution_control import execution_context, ExperimentCancelled
from core.experiment_runner import ExperimentRunner
from test_paper_alignment import make_nodes
from test_upgrade_v21 import metric_dataset, external_history_module

METHODS = [TDDecomposition, HMDecomposition, IEEDecomposition,
           GreeneDecomposition, RGSDecomposition, TDDPDecomposition]
NEW_PLANNERS = [DBOPlanner, SSAPlanner, GSIPSOPlanner, IDGWOVNSPlanner]
L = [(0, 0), (300, 0), (300, 120), (180, 120), (180, 300), (0, 300)]
U = [(0, 0), (300, 0), (300, 300), (220, 300), (220, 90), (80, 90), (80, 300), (0, 300)]
STAR = [(0, 0), (90, 10), (200, 0), (150, 70), (210, 140), (110, 120), (20, 160), (45, 80)]


@pytest.mark.parametrize('method', METHODS, ids=lambda cls: cls.__name__)
@pytest.mark.parametrize('shape', [L, U, STAR, [(0, 0), (500, 0), (500, .02), (0, .02)]])
@pytest.mark.parametrize('angle', [0, 17, 90])
def test_partitions_convex_complete_disjoint_utm_safe(method, shape, angle):
    target = affinity.translate(affinity.rotate(Polygon(shape), angle, origin=(0, 0)), 685000, 8805000)
    ring = list(target.exterior.coords[:-1])
    if angle == 17:
        ring.reverse()
        ring.append(ring[0])
    parts, info = method().decompose_region(ring, {})
    polygons = [Polygon(p) for p in parts]
    joined = unary_union(polygons)
    tolerance = max(1e-6, target.area*1e-9)
    assert joined.symmetric_difference(target).area <= tolerance
    assert sum(p.area for p in polygons)-joined.area <= tolerance
    assert all(p.is_valid and p.area > 0 and p.convex_hull.area-p.area <= tolerance for p in polygons)
    assert info['implementation_scope'] and info['n_cells'] == len(parts)


def test_td_dp_really_merges_convex_contiguous_cells():
    poly = Polygon([(0, 0), (2, 0), (3, 1), (2, 3), (1, 4), (0, 2)])
    cells = _td(poly, 0)
    assert len(cells) > 1 and len(_td_dp(cells)) == 1
    td, _ = TDDecomposition().decompose_region(list(poly.exterior.coords), {'td_angle_deg': 23.})
    dp, _ = TDDPDecomposition().decompose_region(list(poly.exterior.coords), {'td_angle_deg': 23.})
    assert len(dp) <= len(td)


def _disjoint_cover(masks, full):
    combined = 0
    for mask in masks:
        if combined & mask:
            return False
        combined |= mask
    return combined == full


def test_iee_integer_set_partitioning_against_brute_force():
    poly = Polygon([(x/300, y/300) for x, y in U])
    cells = _iee_cells(poly)
    candidates, _ = _merge_candidates(cells, 8, 5000)
    masks, full = list(candidates), (1 << len(cells))-1
    optimum = next(size for size in range(1, len(cells)+1) if any(
        _disjoint_cover(choice, full) for choice in itertools.combinations(masks, size)))
    parts, info = IEEDecomposition().decompose_region(U, {})
    assert info['optimal_within_candidates'] and len(parts) == optimum == 3


def test_greene_known_minimum_and_budget_scope():
    parts, info = GreeneDecomposition().decompose_region(L, {})
    assert len(parts) == 2 and info['minimum_count_proven']
    parts, info = GreeneDecomposition().decompose_region(U, {'greene_state_budget': 1})
    assert parts and info['state_budget_hit'] and not info['minimum_count_proven']


@pytest.mark.parametrize('method', METHODS)
def test_invalid_geometry_reported(method):
    with pytest.raises(ValueError, match='简单多边形'):
        method().decompose_region([(0, 0), (4, 4), (0, 4), (4, 0)], {})


@pytest.fixture
def nodes():
    return make_nodes([[(0, 0), (120, 0), (120, 50), (0, 50)],
        [(250, 60), (350, 60), (350, 120), (250, 120)],
        [(80, 230), (180, 230), (180, 300), (80, 300)]], spacing=20)


def test_order_decoder_matches_exhaustive_variants(nodes):
    evaluator = OrderEvaluator(nodes)
    for order in itertools.permutations(range(3)):
        distance, visit = evaluator.evaluate(order)
        brute = min(tour_distance(nodes, evaluator.cost, selection) for selection in
                    itertools.product(*(evaluator.members[g] for g in order)))
        assert distance == pytest.approx(brute)
        validate_visit(nodes, visit)


@pytest.mark.parametrize('planner', NEW_PLANNERS, ids=lambda cls: cls.name)
def test_planners_reproducible_complete_objective_convergence(planner, nodes):
    instance = planner()
    params = dict(population_size=12, max_iterations=8)
    a = instance.solve_region_order(nodes, params, 42)
    b = instance.solve_region_order(nodes, params, 42)
    assert a == b
    visit, history, stats = a
    validate_visit(nodes, visit)
    assert len(history) == 8 and all(x >= y-1e-9 for x, y in zip(history, history[1:]))
    assert history[-1] == pytest.approx(stats['objective_value'])
    assert stats['objective_value'] == pytest.approx(tour_distance(nodes, OrderEvaluator(nodes).cost, visit))
    assert stats['solver'] == planner.name and stats['implementation_assumptions']
    assert sum(stats['operator_counts'].values()) > 0 and stats['fitness_evaluations'] > 1
    if planner is DBOPlanner:
        assert all(stats['operator_counts'][k] > 0 for k in ('rolling', 'breeding', 'foraging', 'stealing'))
    if planner is SSAPlanner:
        assert all(stats['operator_counts'][k] > 0 for k in ('producer', 'follower', 'scout'))
    if planner is IDGWOVNSPlanner:
        assert all(stats['operator_counts'][k] > 0 for k in ('leader_cross', 'elimination', 'swap', 'insert', 'reverse', 'disorder'))


def test_permutation_operators_and_velocity():
    rng = np.random.default_rng(53)
    source, target = list(range(12)), list(reversed(range(12)))
    assert _apply_velocity(source, _swaps_towards(source, target)) == target
    for _ in range(20):
        assert sorted(_cross(source, target, rng)) == source
        for kind in ('swap', 'insert', 'reverse', 'disorder'):
            assert sorted(_perturb(source, kind, rng)) == source


@pytest.mark.parametrize('planner', NEW_PLANNERS)
def test_planners_cancel_and_validate_budget(planner, nodes):
    with pytest.raises(ValueError):
        planner().solve_region_order(nodes, {'max_iterations': 0}, 42)
    with pytest.raises(ExperimentCancelled):
        with execution_context(lambda: True):
            planner().solve_region_order(nodes, {'max_iterations': 100}, 42)


@pytest.mark.parametrize('decomposition', list(DECOMPOSITIONS))
@pytest.mark.parametrize('planning', list(PLANNERS))
def test_all_63_pairs_execute_with_metric_identity(decomposition, planning):
    combo = Combination(decomposition, planning)
    if decomposition == 'PSO-DCAS':
        combo.decomposition_params.update(pso_iterations=2, pso_swarm_size=10)
    if planning != 'Li-DP':
        combo.planning_params['max_iterations'] = 2
    if planning == 'FA3ACO':
        combo.planning_params['ants_count'] = 4
    if planning in {p.name for p in NEW_PLANNERS}:
        combo.planning_params['population_size'] = 8
    result = ComposedAlgorithm(combo).solve(CPPInput([Region(1, 'L', L),
        Region(2, 'rect', [(450, 100), (550, 100), (550, 200), (450, 200)])],
        (-30, -30), CameraParams()))
    assert result.waypoints[0] == result.waypoints[-1] == (-30, -30)
    assert result.total_distance == pytest.approx(LineString(result.waypoints).length)
    assert len(result.subregion_sequence) == result.metadata['n_subregions_total']
    assert result.metadata['combination'] == combo.to_dict()
    assert 0 <= result.metadata['coverage']['covered_ratio'] <= 1
    assert 'planning' in result.metadata['component_implementation_scope']
    if planning != 'Li-DP':
        assert result.convergence[-1] == pytest.approx(result.total_distance)


def test_component_params_independent_and_not_filtered_as_pso():
    assert len(DECOMPOSITIONS) == 9 and len(PLANNERS) == 7
    for kind, catalog in (('decomposition', DECOMPOSITIONS), ('planning', PLANNERS)):
        for key, (_, cls) in catalog.items():
            if getattr(cls, 'independent_component_params', False):
                defaults = component_defaults(kind, key)
                assert defaults == cls.default_params
                assert {s[0] for s in component_spec(kind, key)} == set(defaults)
    a, b = Combination('TD', 'DBO'), Combination('TD', 'DBO')
    a.planning_params['population_size'] = 12
    assert b.effective_params()['planning']['population_size'] == 80


def test_spawned_workers_and_portable_history(tmp_path):
    from core.experiment_bundle import make_record, export_experiment_directory, load_experiment_directory
    from PySide6.QtWidgets import QApplication
    from gui.experiment_panel import ExperimentPanel
    app = QApplication.instance() or QApplication([])
    panel = ExperimentPanel()
    assert set(panel.decomp_checks) == set(DECOMPOSITIONS)
    assert set(panel.planner_checks) == set(PLANNERS)
    assert '单机' in panel.planner_checks['IDGWO-VNS'].toolTip()
    dataset = metric_dataset()
    combos = [Combination(d, p, planning_params={'population_size': 8, 'max_iterations': 2})
              for d, p in zip(('IEE-MILP', 'Greene', 'RGS', 'TD-DP'), ('DBO', 'SSA', 'GS-IPSO', 'IDGWO-VNS'))]
    camera = CameraParams().as_dict()
    runs = ExperimentRunner().run_jobs_isolated(build_combination_jobs(combos, [dataset], [7], camera))
    for combo in combos:
        run = runs[dataset.name][combo.label][0]
        assert not run.get('error'), run.get('traceback')
        assert run['metadata']['execution']['backend'] == 'spawn-process'
        assert run['metadata']['gtsp']['solver'] == combo.planning
    record = make_record('v2.3 integration', [dataset], camera, combos, runs, 'new planner integration')
    folder = export_experiment_directory(tmp_path/'library', record, 'new algorithms')
    restored = load_experiment_directory(folder)
    assert restored['combinations'] == [c.to_dict() for c in combos]
    module = external_history_module()
    viewer = module.HistoryWindow(library_dir=tmp_path/'replay')
    viewer.open_path(str(folder))
    assert viewer.library.count() == 1
    viewer.close()
    panel.close()


def test_history_library_reports_unreadable_record_and_keeps_other_experiments(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    denied, readable = tmp_path/'denied', tmp_path/'readable'
    denied.mkdir()
    readable.mkdir()
    (readable/'experiment.json').write_text(json.dumps({'schema': 'cpp-arena-experiment'}), encoding='utf-8')
    original = Path.is_file
    def is_file(path, *args, **kwargs):
        if path.parent == denied:
            raise PermissionError('test inaccessible experiment')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'is_file', is_file)
    viewer = external_history_module().HistoryWindow(library_dir=tmp_path)
    assert viewer.library.count() == 1
    assert len(viewer.library_scan_errors) == 1
    assert 'denied' in viewer.statusBar().currentMessage()
    viewer.close()
