"""Portable, offline experiment archives. No algorithm is run during loading."""
import csv
import io
import json
import math
import shutil
import tempfile
import zipfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from config.default_params import APP_VERSION
from data.dataset import Dataset
from data.coord_transform import CoordTransform
from data.waypoint_export import export_waypoints


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, 'item'):
        return json_safe(value.item())
    return value


def dump_json(path, value):
    Path(path).write_text(json.dumps(json_safe(value), ensure_ascii=False, indent=2,
                                    allow_nan=False), encoding='utf-8')


def make_record(project_name, datasets, camera, combinations, results, logs='', view=None, status='completed', seeds=None):
    return json_safe({
        'schema': 'cpp-arena-experiment', 'schema_version': 1, 'app_version': APP_VERSION,
        'id': datetime.now().strftime('%Y%m%d_%H%M%S_%f'),
        'saved_at': datetime.now().astimezone().isoformat(), 'project': project_name,
        'status': status, 'camera': camera, 'datasets': [ds.to_dict() for ds in datasets],
        'seeds': seeds if seeds is not None else sorted({r['seed'] for ds in results.values()
                  for runs in ds.values() for r in runs if 'seed' in r}),
        'combinations': [c.to_dict() for c in combinations], 'results': deepcopy(results),
        'logs': logs, 'view': view or {},
    })


def _plot_run(path, ds, run, decomposition=False):
    return _plot_runs(path, ds, {run.get('algorithm', ''): run}, decomposition)


def _plot_runs(path, ds, runs, decomposition=False):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.patches import Polygon
    figure = Figure(figsize=(12, 9), dpi=120)
    FigureCanvasAgg(figure)
    ax = figure.add_subplot(111)
    if ds.bg_image_path and ds.bg_bounds_utm and Path(ds.bg_image_path).is_file():
        from matplotlib.image import imread
        x0, y0, x1, y1 = ds.bg_bounds_utm
        ax.imshow(imread(ds.bg_image_path), extent=(x0, x1, y0, y1), alpha=.7)
    colors = ['#ccece6', '#b3cde3', '#decbe4', '#fed9a6', '#ffffcc']
    for r in ds.regions:
        ax.add_patch(Polygon(r.vertices, fill=False, edgecolor='#254047', lw=1.8))
    palette = ['#dc4545', '#0072b2', '#009e73', '#cc79a7', '#e69f00', '#6f42c1', '#4d7c0f', '#a16207', '#0e7490']
    from core.path_annotations import draw_partitions, draw_entry_exit, draw_route
    for i, (label, run) in enumerate(runs.items()):
        draw_partitions(ax, [seq['polygon'] for seq in run.get('subregion_sequence', [])],
                        colors[i % len(colors)] if decomposition else None)
        if len(runs) == 1:
            for seq in run.get('subregion_sequence', []):
                pts = seq['polygon']
                ax.text(sum(p[0] for p in pts)/len(pts), sum(p[1] for p in pts)/len(pts), str(seq['order']),
                    ha='center', va='center', fontsize=10, color='#1f3b99', zorder=11,
                    bbox=dict(boxstyle='circle,pad=.2', facecolor='white', edgecolor='#1f3b99'))
        if not decomposition and run.get('waypoints'):
            draw_route(ax, run, palette[i % len(palette)], label=label)
            draw_entry_exit(ax, run)
    if not decomposition:
        ax.plot([], [], '--', color='#64748b', label='虚线：起降 / 子区转场；箭头：飞行方向')
        ax.legend(loc='upper right', fontsize=8)
    if ds.launch_point:
        ax.plot(*ds.launch_point, '^', color='#dc4545', markersize=9)
    ax.set_aspect('equal', adjustable='datalim')
    ax.autoscale_view()
    ax.margins(.06)
    ax.set(xlabel='东向 (m)', ylabel='北向 (m)',
           title=f"{ds.name}\n" + ('图形分割' if decomposition else '路径规划轨迹'))
    ax.grid(alpha=.22)
    from core.image_export import save_jpeg
    save_jpeg(figure, path)
    figure.clear()


def _split_kml(path, ds, run):
    ns = 'http://www.opengis.net/kml/2.2'
    ET.register_namespace('', ns)
    tag = lambda name: f'{{{ns}}}{name}'
    root = ET.Element(tag('kml'))
    document = ET.SubElement(root, tag('Document'))
    tf = CoordTransform(epsg=ds.epsg)
    for seq in run.get('subregion_sequence', []):
        mark = ET.SubElement(document, tag('Placemark'))
        ET.SubElement(mark, tag('name')).text = f"子区域 {seq['order']}"
        poly = ET.SubElement(mark, tag('Polygon'))
        ring = ET.SubElement(ET.SubElement(poly, tag('outerBoundaryIs')), tag('LinearRing'))
        pts = list(seq['polygon'])
        if pts and pts[-1] != pts[0]:
            pts.append(pts[0])
        ET.SubElement(ring, tag('coordinates')).text = ' '.join(
            f'{lon:.10f},{lat:.10f},0' for lon, lat in (tf.utm_to_lonlat(*p) for p in pts))
    from core.path_annotations import subregion_endpoints
    for item in subregion_endpoints(run):
        for key, label in (('entry', '入口'), ('exit', '出口')):
            mark = ET.SubElement(document, tag('Placemark'))
            ET.SubElement(mark, tag('name')).text = f"{label}{item['order']}"
            point = ET.SubElement(mark, tag('Point'))
            lon, lat = tf.utm_to_lonlat(*item[key])
            ET.SubElement(point, tag('coordinates')).text = f'{lon:.10f},{lat:.10f},0'
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def export_bundle(path, record):
    """Write atomically; an existing archive survives an export failure."""
    path = Path(path)
    record = deepcopy(record)
    with tempfile.TemporaryDirectory(prefix='cpp_export_') as staging:
        root = Path(staging)
        (root / 'assets').mkdir()
        metrics = []
        for ds_index, data in enumerate(record['datasets']):
            ds = Dataset.from_dict(data)
            if ds.bg_image_path and Path(ds.bg_image_path).is_file():
                target = f'assets/background_{ds_index}.jpg'
                from PIL import Image
                with Image.open(ds.bg_image_path) as source:
                    source.convert('RGB').save(root / target, quality=98, subsampling=0)
                data['bg_image_path'] = target
            else:
                data['bg_image_path'] = None
            for combo_index, (label, runs) in enumerate(record['results'].get(ds.name, {}).items()):
                for run_index, run in enumerate(runs):
                    relative = f'runs/d{ds_index}_c{combo_index}_r{run_index}'
                    directory = root / relative
                    directory.mkdir(parents=True)
                    dump_json(directory / 'result.json', run)
                    dump_json(directory / 'segmentation.json', {
                        'crs': f'EPSG:{ds.epsg}', 'units': 'metres',
                        'source_regions': [r.to_dict() for r in ds.regions],
                        'subregions': run.get('subregion_sequence', [])})
                    if not run.get('error'):
                        tf = CoordTransform(epsg=ds.epsg)
                        coordinates = [(*tf.utm_to_lonlat(*p), record['camera']['flight_height_m'])
                                       for p in run.get('waypoints', [])]
                        export_waypoints(coordinates, str(directory / 'waypoints.kml'), label)
                        export_waypoints(coordinates, str(directory / 'waypoints.csv'), label)
                        _split_kml(directory / 'segmentation.kml', ds, run)
                        from core.path_annotations import subregion_endpoints
                        with (directory / 'entry_exit.csv').open('w', newline='', encoding='utf-8-sig') as stream:
                            writer = csv.writer(stream)
                            writer.writerow(['访问序号', '子区编号', '点类型', '东向(m)', '北向(m)', '经度', '纬度'])
                            for item in subregion_endpoints(run):
                                for key, label in (('entry', '入口'), ('exit', '出口')):
                                    x, y = item[key]
                                    writer.writerow([item['order'], item['subregion_id'], label, x, y, *tf.utm_to_lonlat(x, y)])
                        _plot_run(directory / 'trajectory.jpg', ds, run)
                        _plot_run(directory / 'segmentation.jpg', ds, run, decomposition=True)
                    run['artifacts'] = relative
                    metrics.append({'dataset': ds.name, 'combination': label, 'seed': run.get('seed'),
                        'started_at': run.get('started_at'), 'finished_at': run.get('finished_at'),
                        'runtime_s': run.get('runtime'), 'elapsed_total_s': run.get('elapsed_total'),
                        'distance_m': run.get('total_distance'), 'turns': run.get('total_turns'),
                        'coverage_ratio': run.get('metadata', {}).get('coverage', {}).get('covered_ratio'),
                        **{key: (run.get('metadata') or {}).get('route_metrics', {}).get(key)
                           for key in ('subregion_transfer_m', 'outside_distance_m', 'redundancy_pct',
                                       'sweep_reversals', 'non_scan_distance_m')},
                        'error': run.get('error', '')})
        dump_json(root / 'experiment.json', record)
        dump_json(root / 'metrics.json', metrics)
        if metrics:
            with (root / 'metrics.csv').open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(metrics[0]))
                writer.writeheader()
                writer.writerows(metrics)
        (root / 'experiment.log').write_text(record.get('logs', ''), encoding='utf-8')
        (root / 'README.txt').write_text(
            'CPP Arena 2.1 完整实验包\n使用独立历史实验平台打开此 ZIP。\n'
            'experiment.json 保存全部结果与视图；runs 下含 KML、分割几何、图片和运行数据。\n'
            '坐标与距离单位为米。失败任务保留错误与参数，不伪造路径。\n', encoding='utf-8')
        # Use a unique sibling to avoid overwriting partially written exports.
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
        try:
            with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
                for item in root.rglob('*'):
                    if item.is_file():
                        archive.write(item, item.relative_to(root).as_posix())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return str(path)


def load_bundle(path, asset_directory):
    """Only materialize referenced images; never extract arbitrary archive paths."""
    with zipfile.ZipFile(path) as archive:
        record = json.loads(archive.read('experiment.json'))
        if record.get('schema') != 'cpp-arena-experiment' or record.get('schema_version') != 1:
            raise ValueError('不支持的实验包格式或版本')
        for index, ds in enumerate(record['datasets']):
            image = ds.get('bg_image_path')
            if image:
                name = Path(image)
                if not image.startswith('assets/') or '..' in name.parts or name.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.bmp', '.tif'):
                    raise ValueError('实验包中底图路径无效')
                target = Path(asset_directory) / f'{index}{name.suffix}'
                target.write_bytes(archive.read(image))
                ds['bg_image_path'] = str(target)
    return record
