"""Regression cases for boundary scans, DP transfers and independent replay."""
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon
from core.base_algorithm import CameraParams, CPPInput, Region
from algorithms.aco import ACOGTSPAlgorithm
from algorithms.aco.boustrophedon import plan_region_variants
from algorithms.aco.aco_gtsp import GTSPNode, build_cost_matrix
from algorithms.aco.li_dp_connection import solve_li_dp_connection


def nodes_for(pieces):
    nodes = [GTSPNode(0, -1, 0, (-10, -10), (-10, -10), 0, [])]
    for group, poly in enumerate(pieces, 1):
        for variant in plan_region_variants(poly, 3, boundary_joints=True, boundary_mode='inside'):
            nodes.append(GTSPNode(len(nodes), group, group, variant.entry, variant.exit,
                variant.internal_distance, variant.path, polygon=poly, variant_id=variant.variant_id))
    return nodes


@pytest.mark.parametrize('angle', [0, .37, 1.6])
def test_clipped_scans_and_turns_stay_in_the_cell(angle):
    points = np.array([(0, 0), (500, 0), (400, 60), (30, 170)])
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    points = points @ rotation.T + np.array([500000, 4400000])
    poly = Polygon(points)
    for boundary_joints in (False, True):
        plans = plan_region_variants(points.tolist(), 20, boundary_joints=boundary_joints, boundary_mode='inside')
        for plan in plans:
            assert poly.buffer(1e-7).covers(LineString(plan.path))
            assert all(poly.buffer(1e-7).covers(LineString(segment)) for segment in plan.scan_segments)
            for point in (plan.entry, plan.exit):
                assert poly.boundary.distance(Point(point)) < 1e-7
            assert any(np.allclose(plan.path, list(reversed(other.path))) for other in plans)


def test_actual_coverage_is_reported_when_boundary_clipping_misses_sharp_tip():
    tri = [(0, 0), (1000, 0), (0, 90)]
    region = Region(1, 'acute', tri)
    algo = ACOGTSPAlgorithm()
    inside = algo.solve(CPPInput([region], (-10, -10), CameraParams(side_overlap_pct=0)), max_iterations=2)
    envelope = algo.solve(CPPInput([region], (-10, -10), CameraParams(side_overlap_pct=0, scan_boundary_mode='envelope')), max_iterations=2)
    coverage = inside.metadata['coverage']
    assert 0 < coverage['covered_ratio'] < 1
    assert coverage['uncovered_area_m2'] > 0 and coverage['warning']
    assert envelope.metadata['coverage']['covered_ratio'] == pytest.approx(1)
    assert Polygon(tri).buffer(1e-7).covers(LineString(inside.internal_paths[0]))
    assert not Polygon(tri).buffer(1e-7).covers(LineString(envelope.internal_paths[0]))
    for index, item in enumerate(inside.subregion_sequence):
        assert item['entry'] == list(inside.internal_paths[index][0])
        assert item['exit'] == list(inside.internal_paths[index][-1])


@pytest.mark.parametrize('pieces', [
    [[(0, 0), (10, 0), (10, 10), (0, 10)], [(30, 0), (40, 0), (40, 10), (30, 10)]],
    [[(0, 0), (10, 0), (10, 10), (0, 10)], [(-10, 2), (0, 2), (0, 4), (-10, 4)],
     [(2, 10), (4, 10), (4, 20), (2, 20)], [(10, 6), (20, 6), (20, 8), (10, 8)]]])
def test_free_transfer_dp_solves_disconnected_and_branched_graphs_exactly(pieces):
    nodes = nodes_for(pieces)
    with pytest.raises(ValueError, match='不存在'):
        solve_li_dp_connection(nodes, {'li_adjacency_mode': 1})
    seq, curve, stats = solve_li_dp_connection(nodes, {'li_adjacency_mode': 0})
    cost = build_cost_matrix(nodes)
    groups = {}
    for node in nodes[1:]:
        groups.setdefault(node.subregion_id, []).append(node.index)
    best = math.inf
    for order in itertools.permutations(groups):
        for chosen in itertools.product(*(groups[g] for g in order)):
            best = min(best, sum(cost[a, b] for a, b in zip(chosen, chosen[1:])))
    assert curve[0] == pytest.approx(best)
    assert sorted(nodes[index].subregion_id for index in seq) == sorted(groups)
    assert stats['connection_mode'] == 'free_transfers'
    assert stats['nonadjacent_transfers'] > 0 and stats['paper_extension']
    fixed, _, _ = solve_li_dp_connection(nodes, {'li_adjacency_mode': 0, 'li_start_group': 1, 'li_end_group': len(groups)})
    assert nodes[fixed[0]].subregion_id == 1 and nodes[fixed[-1]].subregion_id == len(groups)


def test_old_record_entry_exit_fallback_and_annotation_toggle():
    from PySide6.QtWidgets import QApplication
    from core.path_annotations import subregion_endpoints
    from gui.path_canvas import PathCanvas
    from data.dataset import Dataset
    app = QApplication.instance() or QApplication([])
    ds = Dataset('legacy')
    ds.add_region('r', [(0, 0), (100, 0), (100, 100), (0, 100)])
    run = {'waypoints': [(0, 0), (10, 10), (90, 90), (0, 0)],
           'internal_paths': [[(10, 10), (90, 90)]],
           'subregion_sequence': [{'order': 1, 'polygon': ds.regions[0].vertices}], 'total_distance': 200}
    endpoints = list(subregion_endpoints(run))
    assert endpoints[0]['entry'] == (10, 10) and endpoints[0]['exit'] == (90, 90)
    canvas = PathCanvas()
    canvas.set_dataset(ds)
    canvas.set_results({'route': run})
    assert any(text.get_gid() == 'entry-label-1' for text in canvas.ax.texts)
    assert any(line.get_linestyle() == '--' for line in canvas.ax.lines)
    canvas.set_layer('endpoints', False)
    assert not any(text.get_gid() == 'entry-label-1' for text in canvas.ax.texts)
    canvas.close()


def test_copied_history_platform_runs_without_main_or_algorithm_sources(tmp_path):
    from core.combinations import Combination
    from core.experiment_runner import ExperimentRunner, ExperimentJob
    from core.experiment_bundle import make_record, export_bundle
    from data.dataset import Dataset
    ds = Dataset('independent')
    ds.add_region('r', [(0, 0), (100, 0), (100, 100), (0, 100)])
    ds.launch_point = (-10, -10)
    combination = Combination('Bayazit', 'ACO', planning_params={'max_iterations': 2})
    camera = CameraParams().as_dict()
    run = ExperimentRunner()._run_single(ExperimentJob(combination.label, ds, 42, camera=camera, combination=combination.to_dict()))
    archive = tmp_path / 'experiment.cppx'
    export_bundle(archive, make_record('standalone', [ds], camera, [combination], {ds.name: {combination.label: [run]}}))
    from verification.history_location import history_viewer_directory
    platform = history_viewer_directory()
    destination = tmp_path / 'CopiedViewer'
    shutil.copytree(platform, destination, ignore=shutil.ignore_patterns('__pycache__', 'experiments', 'projects'))
    output = tmp_path / 'check.json'
    environment = dict(os.environ, PYTHONPATH='', QT_QPA_PLATFORM='offscreen')
    result = subprocess.run([sys.executable, str(destination / 'viewer.py'), str(archive), '--check', str(output)],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    checked = json.loads(output.read_text(encoding='utf-8'))
    assert checked['standalone'] and not checked['algorithm_modules_loaded']
    assert checked['experiment_loaded'] and checked['runs_in_selector'] == 2
