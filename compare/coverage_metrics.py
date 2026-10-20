"""Camera footprint evaluation from chosen scan segments, independent of solvers."""
import math


def scan_footprints(segments, width, height):
    from shapely.geometry import Polygon
    footprints = []
    for a, b in segments:
        length = math.dist(a, b)
        if length < 1e-10:
            continue
        dx, dy = ((b[0]-a[0])/length, (b[1]-a[1])/length)
        ux, uy = -dy*width/2, dx*width/2
        start = (a[0]-dx*height/2, a[1]-dy*height/2)
        end = (b[0]+dx*height/2, b[1]+dy*height/2)
        footprints.append(Polygon([(start[0]+ux, start[1]+uy), (end[0]+ux, end[1]+uy),
                                   (end[0]-ux, end[1]-uy), (start[0]-ux, start[1]-uy)]))
    return footprints


def evaluate_coverage(regions, segments, width, height):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    target = unary_union([Polygon(r.vertices) for r in regions])
    covered = unary_union(scan_footprints(segments, width, height))
    scanned = target.intersection(covered).area
    missed = target.difference(covered).area
    if target.area <= 0:
        raise ValueError('总任务区域面积必须大于0')
    return {'covered_ratio': max(0., min(1., scanned/target.area)),
            'covered_area_m2': scanned, 'target_area_m2': target.area,
            'uncovered_area_m2': missed,
            'definition': 'covered target area / total target area; both evaluated as unions',
            'evaluation': 'union of chosen scan footprints intersected with union of original target regions'}


def coverage_details(run, dataset=None, camera=None):
    """Evaluate saved scans, or retain legacy values without inventing geometry."""
    saved = dict((run.get('metadata') or {}).get('coverage') or {})
    sequence = run.get('subregion_sequence') or []
    complete = all(saved.get(key) is not None for key in ('covered_area_m2', 'target_area_m2', 'uncovered_area_m2'))
    if not complete and dataset is not None and dataset.regions and camera and sequence and all('scan_segments' in s for s in sequence):
        from config.default_params import compute_camera
        info = compute_camera(camera)
        saved.update(evaluate_coverage(dataset.regions, [p for s in sequence for p in s['scan_segments']],
                                      info['coverage_w'], info['coverage_h']))
        saved['display_source'] = 'saved scan geometry and camera snapshot'
    return saved


def format_area(value):
    if value is None:
        return '--'
    return f'{value:.4e}' if 0 < abs(value) < .0001 else f'{value:.8g}'


def format_coverage(coverage):
    ratio = coverage.get('covered_ratio')
    if ratio is None:
        return '--'
    value = f'{ratio*100:.6g}'
    if value == '100' and coverage.get('uncovered_area_m2', 0) > 0:
        return '≈100%（仍有微小未覆盖）'
    return value + '%'


def coverage_tooltip(coverage):
    lines = ['覆盖率 = 已扫描到的目标区域面积 / 总任务区域面积；重叠只计一次，区外不计。']
    for key, label in (('covered_area_m2', '已扫描目标面积'), ('target_area_m2', '总任务面积'),
                       ('uncovered_area_m2', '未覆盖面积')):
        if coverage.get(key) is not None:
            lines.append(f'{label}：{coverage[key]:.12g} m²')
    lines.append('未覆盖为0只表示当前相机/连续扫描模型下无漏扫，不代表路线最短。')
    return '\n'.join(lines)
