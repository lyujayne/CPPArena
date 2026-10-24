"""Route metrics derived from executed geometry, never optimizer objectives."""
from compare.metrics import path_length


METRIC_HELP = {
    '运行状态': '成功优于部分失败或运行失败；只有有效运行参与数值统计。',
    '失败运行次数': '运行报错或缺少有效总距离的次数。越小越好，理想值为0。',
    '总距离均值 (m)': '多次有效运行的完整执行航程平均值。覆盖率满足要求时越小越好。',
    '总距离标准差': '多次有效运行总航程的总体标准差（m），反映随机运行的波动。越小越稳定；需结合平均航程评价，稳定不等于航程短。',
    '总距离最优': '多次有效运行中最短的完整航程（m）。覆盖率满足要求时越小越好。',
    '总距离最差': '多次有效运行中最长的完整航程（m）。覆盖率满足要求时越小越好。',
    '航向拐点均值': '完整航迹中航向变化超过5°的拐点次数平均值。覆盖率满足要求时通常越小越好；不是能耗的直接测量。',
    '航向拐点最少': '有效运行中最少的>5°航向拐点次数。覆盖率满足要求时通常越小越好。',
    '耗时均值 (s)': '有效运行算法耗时的平均值。相同硬件、输入与参数预算下越小越好。',
    '有效运行次数': '成功且具有有效总距离的运行次数。同等计划运行次数下越大越好；不同试验规模间不直接排名。',
    '相对基线距离改善率 (%)': '（所选基线航程均值−当前航程均值）/基线均值×100%。越大越好；正数为缩短，负数为变长。先在“距离基线”中选择基线。',
    '覆盖率均值 (%)': '覆盖率=扫描到的目标区域面积/总任务区域面积×100%；两者按并集计算，重复覆盖只计一次，区外扫描不计。此处为有效运行的平均值。',
    '覆盖率最低 (%)': '有效运行中最低的覆盖率。不是优化器的目标函数，也不表示总航程是否最优。',
    '未覆盖面积均值 (m²)': '总任务区域中未被扫描覆盖到的面积。0表示当前相机/连续扫描模型下无漏扫；非零小数保留，不四舍五入为0。',
    '子区域转运距离均值 (m)': '访问顺序中，相邻子区出口到下一子区入口的直线距离之和；不含起飞与返航。',
    '区域外航程均值 (m)': '完整执行轨迹落在所有原始目标地块并集之外的长度，包含区外的起飞、返航、转场或扫描；逐航段累加，重复飞行重复计数。',
    '冗余率均值 (%)': '重复飞行长度/总航程×100%。例如A到B为100m，再原路飞回100m，总航程200m中100m为重走，冗余率50%。按线段并集去重；只有交叉点不算重走，不是照片重叠率。',
    '扫描换行次数均值': '各子区相邻扫描条带之间的换行次数之和；区别于>5°几何拐点数，不含子区之间转运。',
    '非扫描航程均值 (m)': '完整航程−实际扫描航段总长度，包含起飞/返航、子区转运、区内换行及边界连接段；不等同于区域外航程。',
}

for _metric in ('覆盖率均值 (%)', '覆盖率最低 (%)'):
    METRIC_HELP[_metric] += ' 越大越好，最大100%。'
for _metric in ('未覆盖面积均值 (m²)', '子区域转运距离均值 (m)', '区域外航程均值 (m)',
                '冗余率均值 (%)', '扫描换行次数均值', '非扫描航程均值 (m)'):
    METRIC_HELP[_metric] += ' 覆盖率满足要求、相同任务条件下越小越好；起降和转场可能使其无法为0。'


def compute_route_metrics(run, dataset=None):
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union
    points = run.get('waypoints') or []
    paths = run.get('internal_paths') or []
    total = path_length(points)
    result = {'executed_distance_m': total} if points else {}
    if paths:
        endpoints = [(p[0], p[-1]) for p in paths if p]
        result['subregion_transfer_m'] = sum(path_length([a[1], b[0]]) for a, b in zip(endpoints, endpoints[1:]))
        result['internal_distance_m'] = sum(path_length(p) for p in paths)
    elif run.get('subregion_sequence'):
        seq = run['subregion_sequence']
        if all(item.get('entry') is not None and item.get('exit') is not None for item in seq):
            result['subregion_transfer_m'] = sum(path_length([a['exit'], b['entry']]) for a, b in zip(seq, seq[1:]))
    segments = [LineString([a, b]) for a, b in zip(points, points[1:]) if a != b and tuple(a) != tuple(b)]
    if points and dataset is not None and dataset.regions:
        target = unary_union([Polygon(r.vertices) for r in dataset.regions])
        result['outside_distance_m'] = sum(segment.difference(target).length for segment in segments)
    # The union removes duplicate linework but not mere point crossings.
    if points:
        result['unique_route_length_m'] = unary_union(segments).length if segments else 0.
        result['redundancy_pct'] = max(0., min(100., (total-result['unique_route_length_m'])/total*100)) if total else 0.
    seq = run.get('subregion_sequence') or []
    if points and seq and all('scan_segments' in item for item in seq):
        scan_length = sum(path_length(segment) for item in seq for segment in item['scan_segments'])
        result['scan_distance_m'] = scan_length
        result['non_scan_distance_m'] = max(0., total-scan_length)
    turns = (run.get('metadata') or {}).get('turn_metrics', {}).get('sweep_reversals')
    if turns is not None:
        result['sweep_reversals'] = turns
    return result


def attach_route_metrics(run, dataset=None):
    values = compute_route_metrics(run, dataset)
    if not isinstance(run.get('metadata'), dict):
        run['metadata'] = {}
    if not isinstance(run['metadata'].get('route_metrics'), dict):
        run['metadata']['route_metrics'] = {}
    run['metadata']['route_metrics'].update(values)
    return values
