"""Independent geometry, graph, objective and stochastic regression checks."""
import itertools
import math

import numpy as np
import pytest
from shapely import affinity
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from algorithms.aco import ACOGTSPAlgorithm
from algorithms.aco.aco_gtsp import GTSPNode, build_cost_matrix, solve_aco_gtsp, tour_distance
from algorithms.aco.boustrophedon import (choose_sweep_direction, coverage_geometry,
                                         plan_region_variants)
from algorithms.aco.enhanced_decomp import enhanced_convex_decompose
from algorithms.aco.enhanced_ecd_dp import EnhancedECDDPAlgorithm
from algorithms.aco.fa3aco_gtsp import (build_reverse_node_map, evaporation_rate,
    fractional_pheromone_integral, gruenwald_letnikov_coeffs, solve_fa3aco_gtsp,
    three_opt_tour)
from algorithms.aco.li_dp_connection import li_adjacency_cost, solve_li_dp_connection
from algorithms.aco.polygon_decomp import convex_decompose
from algorithms.aco.pso_decomp import pso_convex_decompose, rotating_calipers_width
from config.default_params import ALGORITHM_DEFAULTS, compute_camera
from core.base_algorithm import CPPInput, CameraParams, Region

L = [(0, 0), (300, 0), (300, 120), (180, 120), (180, 300), (0, 300)]
U = [(0, 0), (300, 0), (300, 300), (220, 300), (220, 90),
     (80, 90), (80, 300), (0, 300)]


def make_nodes(pieces, spacing=20, launch=(-60, -60)):
    nodes = [GTSPNode(0, -1, 0, launch, launch, 0)]
    for group, poly in enumerate(pieces, 1):
        for v in plan_region_variants(poly, spacing):
            nodes.append(GTSPNode(len(nodes), 1, group, v.entry, v.exit,
                v.internal_distance, v.path, poly, v.variant_id))
    return nodes


@pytest.mark.parametrize('angle', [0, 13, 90, 179])
@pytest.mark.parametrize('shape', [
    [(0, 0), (100, 0), (100, 24), (0, 24)],
    [(0, 0), (1000, 0), (0, 90)],
    [(0, 0), (200, 0), (180, 30), (40, 55), (0, 25)],
])
def test_scan_coverage_reversal_and_parity(shape, angle):
    poly = affinity.translate(affinity.rotate(Polygon(shape), angle, origin=(0, 0)),
                              520000, 3800000)
    ring = list(poly.exterior.coords[:-1])
    direction = choose_sweep_direction(ring)
    for ring2 in (ring, list(reversed(ring)), ring[1:]+ring[:1]):
        variants = plan_region_variants(ring2, 10, sweep_dir=direction)
        assert len(variants) == 4
        for v in variants:
            signs = [np.sign(np.dot(np.subtract(b, a), direction))
                     for a, b in zip(v.path[::2], v.path[1::2])]
            assert all(a*b < 0 for a, b in zip(signs, signs[1:]))
            # Width=spacing is harder than the default camera's 80% overlap.
            covered = coverage_geometry(v, direction, 10, 7.5)
            assert poly.difference(covered).area < 1e-5
            assert v.internal_distance == pytest.approx(LineString(v.path).length)
        nodes = make_nodes([ring2], spacing=10)
        reverse = build_reverse_node_map(nodes)
        for a, b in reverse.items():
            assert nodes[a].path == list(reversed(nodes[b].path))


def test_scan_no_degenerate_last_line():
    poly = [(0, 0), (200, 0), (180, 30), (40, 55), (0, 25)]
    plans = plan_region_variants(poly, 10, np.array([1., 0.]))
    assert len(plans[0].scan_segments) == 6
    assert all(np.linalg.norm(np.subtract(a, b)) > 0 for a, b in plans[0].scan_segments)


def test_scan_rectangle_short_connections():
    v = plan_region_variants([(0, 0), (100, 0), (100, 24), (0, 24)], 10)[0]
    assert v.internal_distance == pytest.approx(320)
    for a, b in zip(v.path[1::2], v.path[2::2]):
        assert a[0] == b[0]


def test_width_against_independent_projection_reference():
    rng = np.random.RandomState(147)
    for _ in range(80):
        poly = Polygon(rng.uniform(-100, 100, (30, 2))).convex_hull
        pts = np.array(poly.exterior.coords[:-1])
        widths = []
        for a, b in zip(pts, np.roll(pts, -1, axis=0)):
            e = b-a
            n = np.array([-e[1], e[0]])/np.linalg.norm(e)
            projection = pts@n
            widths.append(np.ptp(projection))
        assert rotating_calipers_width(list(map(tuple, pts))) == pytest.approx(min(widths))


@pytest.mark.parametrize('kind', ['bayazit', 'li', 'pso'])
def test_decomposition_partition_constraints(kind):
    rng = np.random.RandomState(20261018)
    for _ in range(12):
        radii = rng.uniform(40, 140, 9)
        angles = np.linspace(0, 2*math.pi, 9, endpoint=False)
        pts = [(r*math.cos(a), r*math.sin(a)) for r, a in zip(radii, angles)]
        if kind == 'bayazit':
            parts = convex_decompose(pts, seed=42)
        elif kind == 'li':
            parts, _ = enhanced_convex_decompose(pts)
        else:
            parts, info = pso_convex_decompose(pts,
                {'pso_swarm_size': 20, 'pso_iterations': 16}, seed=42)
            assert info['n_extra_cuts'] == 0
        polygons = [Polygon(p) for p in parts]
        union = unary_union(polygons)
        assert union.symmetric_difference(Polygon(pts)).area < 1e-6
        assert sum(p.area for p in polygons)-union.area < 1e-6
        assert all(p.is_valid and p.convex_hull.area-p.area < 1e-6 for p in polygons)


def test_li_dp_matches_open_adjacency_bruteforce():
    pieces, _ = enhanced_convex_decompose(U)
    nodes = make_nodes(pieces)
    costs, groups, adjacent = li_adjacency_cost(nodes)
    start, end = min(groups), max(groups)
    visit, curve, stats = solve_li_dp_connection(nodes, {'li_start_group': start, 'li_end_group': end})
    middle = [g for g in groups if g not in (start, end)]
    optimum = math.inf
    for order in itertools.permutations(middle):
        for seq in itertools.product(*(groups[g] for g in [start]+list(order)+[end])):
            optimum = min(optimum, sum(costs[a, b] for a, b in zip(seq, seq[1:])))
    assert curve[-1] == pytest.approx(optimum)
    assert sum(costs[a, b] for a, b in zip(visit, visit[1:])) == pytest.approx(optimum)
    assert nodes[visit[0]].subregion_id == start
    assert nodes[visit[-1]].subregion_id == end
    assert all(adjacent[nodes[a].subregion_id, nodes[b].subregion_id]
               for a, b in zip(visit, visit[1:]))
    assert stats['launch_return_in_objective'] is False


def test_li_limit_does_not_return_incomplete_coverage():
    pieces, _ = enhanced_convex_decompose(U)
    with pytest.raises(ValueError, match='超过上限'):
        solve_li_dp_connection(make_nodes(pieces), {'dp_max_groups': 1})


def test_li_disconnected_graph_fails_explicitly():
    pieces = [[(0, 0), (10, 0), (10, 10), (0, 10)],
              [(30, 0), (40, 0), (40, 10), (30, 10)]]
    with pytest.raises(ValueError, match='不存在'):
        solve_li_dp_connection(make_nodes(pieces), {})


def test_li_auto_endpoints_match_all_orders_bruteforce():
    pieces, _ = enhanced_convex_decompose(U)
    nodes = make_nodes(pieces)
    costs, groups, _ = li_adjacency_cost(nodes)
    seq, curve, stats = solve_li_dp_connection(nodes, {})
    best = math.inf
    for permutation in itertools.permutations(groups):
        for chosen in itertools.product(*(groups[g] for g in permutation)):
            best = min(best, sum(costs[a, b] for a, b in zip(chosen, chosen[1:])))
    assert curve[-1] == pytest.approx(best)
    assert stats['endpoint_selection'] == 'DP selects unspecified endpoint(s)'
    assert len(seq) == len(groups)


def test_li_branched_graph_has_no_once_only_traversal():
    pieces = [[(0, 0), (10, 0), (10, 10), (0, 10)],
              [(-10, 2), (0, 2), (0, 4), (-10, 4)],
              [(2, 10), (4, 10), (4, 20), (2, 20)],
              [(10, 6), (20, 6), (20, 8), (10, 8)]]
    with pytest.raises(ValueError, match='不存在'):
        solve_li_dp_connection(make_nodes(pieces), {})


def test_fractional_literal_coefficients_and_author_integral():
    assert np.allclose(gruenwald_letnikov_coeffs(.5, 5),
                       [-.5, -.125, -.0625, -.0390625, -.02734375])
    assert np.allclose(fractional_pheromone_integral([np.array([2., 3.])], .5),
                       np.array([2., 3.])/math.sqrt(math.pi))
    history = [np.array([2.]), np.array([5.]), np.array([7.])]
    expected = (2/math.sqrt(3)+5/math.sqrt(2)+7)/math.sqrt(math.pi)
    assert fractional_pheromone_integral(history, .5)[0] == pytest.approx(expected)
    assert evaporation_rate(1, .05, .9, 3) == pytest.approx(.05+.85*math.exp(-3))


def test_fractional_eq16_invalid_probability_is_not_clipped():
    nodes = [GTSPNode(i, i, i, (float(x), 0.), (float(x), 0.), 0.)
             for i, x in enumerate([0, 1, 10, 100])]
    with pytest.raises(ValueError, match='负转移概率'):
        solve_fa3aco_gtsp(nodes, {'fractional_mode': 0, 'max_iterations': 1,
                                 'ants_count': 4, 'use_three_opt': 0}, seed=42)


def test_li_boundary_joints_on_width_supports_and_reverse_pairs():
    from shapely.geometry import Point
    poly = [(0, 0), (1000, 0), (0, 90)]
    direction = choose_sweep_direction(poly)
    normal = np.array([-direction[1], direction[0]])
    bounds = np.array(poly)@normal
    plans = plan_region_variants(poly, 20, boundary_joints=True)
    for plan in plans:
        for point in (plan.entry, plan.exit):
            assert Polygon(poly).boundary.distance(Point(point)) < 1e-7
            h = np.dot(point, normal)
            assert min(abs(h-bounds.min()), abs(h-bounds.max())) < 1e-7
    for plan in plans:
        assert any(plan.path == list(reversed(other.path)) for other in plans)


def test_three_opt_previous_first_node_counterexample():
    pts = np.random.RandomState(42).uniform(0, 100, (6, 2))
    costs = np.linalg.norm(pts[:, None]-pts[None, :], axis=2)
    def length(seq):
        t = [0]+list(seq)+[0]
        return sum(costs[a, b] for a, b in zip(t, t[1:]))
    seq, gain, _, _ = three_opt_tour([1, 2, 3, 4, 5], costs,
                                    {i: i for i in range(6)}, lambda i: 0, {})
    assert length(seq) <= 241.06807549059883+1e-8
    assert gain == pytest.approx(length([1, 2, 3, 4, 5])-length(seq))
    # Validate every 2-opt neighbor independently, including changing first node.
    for i in range(len(seq)):
        for j in range(i+1, len(seq)):
            neighbor = seq[:i]+list(reversed(seq[i:j+1]))+seq[j+1:]
            assert length(neighbor) >= length(seq)-1e-8


def test_three_opt_directed_variant_gain_and_full_neighbor_exhaustion():
    pieces = [[(x, y), (x+12, y), (x+12, y+8), (x, y+8)]
              for x, y in [(0, 0), (60, 90), (-40, 30), (80, -40)]]
    nodes = make_nodes(pieces, spacing=5)
    cost = build_cost_matrix(nodes)
    rev = build_reverse_node_map(nodes)
    original = [1, 5, 9, 13]
    seq, gain, _, _ = three_opt_tour(original, cost, rev,
                                    lambda j: nodes[j].internal_distance, {})
    assert gain == pytest.approx(tour_distance(nodes, cost, original)-tour_distance(nodes, cost, seq))
    route = [0]+seq
    value = tour_distance(nodes, cost, seq)
    for i, j, k in itertools.combinations(range(len(route)), 3):
        A, B = route[i+1:j+1], route[j+1:k+1]
        C = route[k+1:]+route[:i+1]
        for ra, rb in itertools.product([0, 1], repeat=2):
            a = [rev[x] for x in reversed(A)] if ra else A
            b = [rev[x] for x in reversed(B)] if rb else B
            for t in (C+a+b, C+b+a):
                z = t.index(0)
                s = (t[z:]+t[:z])[1:]
                assert tour_distance(nodes, cost, s) >= value-1e-8


@pytest.mark.parametrize('solver', [solve_aco_gtsp, solve_fa3aco_gtsp])
def test_stochastic_solvers_visit_all_groups_and_reproduce(solver):
    pieces, _ = enhanced_convex_decompose(U)
    nodes = make_nodes(pieces)
    params = {'max_iterations': 4, 'ants_count': 5}
    a, history, stats = solver(nodes, params, seed=12)
    b, history2, _ = solver(nodes, params, seed=12)
    assert a == b and history == history2
    assert sorted(nodes[j].subregion_id for j in a) == list(range(1, len(pieces)+1))
    assert history[-1] == pytest.approx(tour_distance(nodes, build_cost_matrix(nodes), a))
    assert all(b <= a for a, b in zip(history, history[1:]))
    if solver == solve_aco_gtsp:
        assert stats['n_ants'] == len(nodes)
        assert 'constant-Q' in stats['paper_alignment']


@pytest.mark.parametrize('algorithm', [ACOGTSPAlgorithm, EnhancedECDDPAlgorithm])
def test_end_to_end_triangle_coverage_and_objective(algorithm):
    # The legacy envelope mode intentionally allows endpoints outside the cell.
    cam = CameraParams(scan_boundary_mode='envelope')
    tri = [(0, 0), (1000, 0), (0, 90)]
    inp = CPPInput([Region(1, 'triangle', tri)], (-10, -10), cam)
    r = algorithm().solve(inp, max_iterations=3)
    assert r.metadata['coverage']['covered_ratio'] == pytest.approx(1)
    assert r.total_distance == pytest.approx(LineString(r.waypoints).length)
    assert r.waypoints[0] == r.waypoints[-1] == inp.launch_point
    if algorithm == EnhancedECDDPAlgorithm:
        assert r.convergence == [0.]  # One subregion: no inter-region edge.
    else:
        assert r.convergence[-1] == pytest.approx(r.total_distance)


def test_invalid_inputs_not_silently_repaired():
    with pytest.raises(ValueError, match='重叠率'):
        compute_camera(CameraParams(side_overlap_pct=100).as_dict())
    with pytest.raises(ValueError, match='凸多边形'):
        plan_region_variants(L, 10)
    with pytest.raises(RuntimeError, match='上限'):
        enhanced_convex_decompose(U, max_pieces=1)


def test_paper_population_defaults():
    assert ALGORITHM_DEFAULTS['PSO-FA3ACO']['ants_count'] == 80
    assert ALGORITHM_DEFAULTS['ACO-GTSP']['tau0'] > 0
