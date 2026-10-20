"""Portable, offline experiment archives. No algorithm is run during loading."""
import csv
import json
import math
import re
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4
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


def dump_json(path, value, *, already_safe=False):
    # Stream chunks to disk instead of allocating a second full JSON string.
    with Path(path).open('w', encoding='utf-8') as stream:
        json.dump(value if already_safe else json_safe(value), stream,
                  ensure_ascii=False, indent=2, allow_nan=False)


def make_record(project_name, datasets, camera, combinations, results, logs='', view=None, status='completed', seeds=None):
    return json_safe({
        'schema': 'cpp-arena-experiment', 'schema_version': 1, 'app_version': APP_VERSION,
        'id': datetime.now().strftime('%Y%m%d_%H%M%S_%f'),
        'saved_at': datetime.now().astimezone().isoformat(), 'project': project_name,
        'status': status, 'camera': camera, 'datasets': [ds.to_dict() for ds in datasets],
        'seeds': seeds if seeds is not None else sorted({r['seed'] for ds in results.values()
                  for runs in ds.values() for r in runs if 'seed' in r}),
        'combinations': [c.to_dict() for c in combinations], 'results': results,
        'logs': logs, 'view': view or {},
    })


def _plot_run(path, ds, run, decomposition=False):
    return _plot_runs(path, ds, {run.get('algorithm', ''): run}, decomposition)


def _plot_runs(path, ds, runs, decomposition=False):
    import matplotlib
    matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    matplotlib.rcParams['axes.unicode_minus'] = False
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
    try:
        save_jpeg(figure, path)
    finally:
        # Agg buffers are tens of MB per 400-DPI image. Break figure/canvas
        # ownership and collect artists before rendering the next run.
        figure.clear()
        figure.set_canvas(None)
        del ax
        import gc
        gc.collect()


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


def _write_experiment_files(root, record, progress=None):
    """Write complete portable artifacts from a private record copy."""
    (root / 'assets').mkdir()
    metrics = []
    total = sum(len(runs) for values in record['results'].values() for runs in values.values())
    done = 0
    for ds_index, data in enumerate(record['datasets']):
        ds = Dataset.from_dict(data)
        if progress:
            progress(done, total, f'准备数据集：{ds.name}')
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
                if progress:
                    progress(done, total, f'{ds.name} · {label} · seed={run.get("seed")}：保存航点与结果')
                dump_json(directory / 'result.json', run, already_safe=True)
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
                            for key, point_label in (('entry', '入口'), ('exit', '出口')):
                                x, y = item[key]
                                writer.writerow([item['order'], item['subregion_id'], point_label, x, y, *tf.utm_to_lonlat(x, y)])
                    if progress:
                        progress(done, total, f'{label} · seed={run.get("seed")}：生成路线 JPEG')
                    _plot_run(directory / 'trajectory.jpg', ds, run)
                    _plot_run(directory / 'segmentation.jpg', ds, run, decomposition=True)
                run['artifacts'] = relative
                metrics.append({'dataset': ds.name, 'combination': label, 'seed': run.get('seed'),
                    'started_at': run.get('started_at'), 'finished_at': run.get('finished_at'),
                    'runtime_s': run.get('runtime'), 'elapsed_total_s': run.get('elapsed_total'),
                    'distance_m': run.get('total_distance'), 'turns': run.get('total_turns'),
                    'coverage_ratio': ((run.get('metadata') or {}).get('coverage') or {}).get('covered_ratio'),
                    **{key: ((run.get('metadata') or {}).get('coverage') or {}).get(key)
                       for key in ('covered_area_m2', 'target_area_m2', 'uncovered_area_m2')},
                    **{key: (run.get('metadata') or {}).get('route_metrics', {}).get(key)
                       for key in ('subregion_transfer_m', 'outside_distance_m', 'redundancy_pct',
                                   'sweep_reversals', 'non_scan_distance_m')},
                    'error': run.get('error', '')})
                done += 1
                if progress:
                    progress(done, total, f'已保存{done}/{total}次运行')
    if progress:
        progress(done, total, '写入完整实验索引')
    dump_json(root / 'experiment.json', record, already_safe=True)
    dump_json(root / 'metrics.json', metrics)
    if metrics:
        with (root / 'metrics.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(metrics[0]))
            writer.writeheader()
            writer.writerows(metrics)
    (root / 'experiment.log').write_text(record.get('logs', ''), encoding='utf-8')
    (root / 'README.txt').write_text(
        f'CPP Arena {APP_VERSION} 完整实验记录\n使用独立历史实验平台导入此文件夹或打开兼容ZIP。\n'
        'experiment.json 保存全部结果与视图；runs 下含 KML、分割几何、图片和运行数据。\n'
        '坐标与距离单位为米。失败任务保留错误与参数，不伪造路径。\n', encoding='utf-8')


def export_bundle(path, record):
    """Legacy ZIP export; use folder export for the current UI workflow."""
    path = Path(path)
    record = json_safe(record)
    with tempfile.TemporaryDirectory(prefix="cpp_export_") as staging:
        root = Path(staging)
        _write_experiment_files(root, record)
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


def _validate_record(record):
    if not isinstance(record, dict) or record.get('schema') != 'cpp-arena-experiment' or record.get('schema_version') != 1:
        raise ValueError('不是包含原始几何和相机快照的完整实验记录')
    if not isinstance(record.get('datasets'), list) or not isinstance(record.get('results'), dict):
        raise ValueError('实验缺少数据集或运行结果')
    if not isinstance(record.get('camera'), dict):
        raise ValueError('实验缺少相机参数快照')
    return record


def _experiment_stem(name, exported_at=None):
    name = str(name).strip()
    if not name:
        raise ValueError('请填写实验名称')
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')
    if not safe:
        raise ValueError('实验名称须包含有效字符')
    return (exported_at or datetime.now()).strftime('%Y%m%d_%H%M%S') + '_' + safe[:100]


def _publish_directory(staged, library, stem):
    """Publish a complete sibling directory without replacing an existing record."""
    library = Path(library).resolve()
    if staged.resolve().parent.parent != library:
        raise ValueError('临时实验目录不在目标实验库中')
    number = 1
    while True:
        destination = library / (stem if number == 1 else f'{stem} ({number})')
        if destination.parent.resolve() != library:
            raise ValueError('实验目录必须位于目标实验库内')
        if destination.exists():
            number += 1
            continue
        try:
            staged.rename(destination)
            return destination
        except FileExistsError:
            number += 1


@contextmanager
def _staging_directory(library, prefix='.cpp_export_'):
    """Disposable sibling with the library's inherited permissions.

    Python 3.13 Windows TemporaryDirectory creates a protected private ACL;
    moving its child into a shared library would retain that inaccessible ACL.
    Normal mkdir inherits the target library's existing reader permissions.
    """
    library = Path(library).resolve()
    root = library / (prefix + uuid4().hex)
    root.mkdir()
    try:
        yield root
    finally:
        if root.resolve().parent != library:
            raise ValueError('拒绝清理实验库以外的临时目录')
        if root.exists():
            shutil.rmtree(root)


def export_experiment_directory(library, record, experiment_name, exported_at=None):
    """Save an atomic timestamp+name folder directly into the history library."""
    exported_at = exported_at or datetime.now().astimezone()
    stem = _experiment_stem(experiment_name, exported_at)
    record = json_safe(_validate_record(record))
    record['experiment_name'] = str(experiment_name).strip()
    record['exported_at'] = exported_at.isoformat()
    library = Path(library).resolve()
    library.mkdir(parents=True, exist_ok=True)
    with _staging_directory(library) as temporary:
        staged = Path(temporary) / 'experiment'
        staged.mkdir()
        _write_experiment_files(staged, record)
        return _publish_directory(staged, library, stem)


def _resolve_backgrounds(record, directory):
    directory = Path(directory).resolve()
    for ds in record['datasets']:
        image = ds.get('bg_image_path')
        if not image:
            continue
        name = Path(image)
        if (not str(image).startswith('assets/') or '..' in name.parts or name.is_absolute()
                or name.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.bmp', '.tif')):
            raise ValueError('实验底图路径必须位于自身 assets 文件夹')
        target = (directory / name).resolve()
        if not target.is_relative_to(directory) or not target.is_file():
            raise ValueError('实验底图文件缺失或路径无效：' + str(image))
        ds['bg_image_path'] = str(target)
    return record


def load_experiment_directory(directory):
    directory = Path(directory).resolve()
    record = _validate_record(json.loads((directory / 'experiment.json').read_text(encoding='utf-8')))
    return _resolve_backgrounds(record, directory)


def _extract_portable_archive(path, directory):
    directory = Path(directory).resolve()
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            member = Path(item.filename)
            target = (directory / member).resolve()
            if (member.is_absolute() or '..' in member.parts or not target.is_relative_to(directory)
                    or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('实验包包含无效文件路径')
        archive.extractall(directory)


def import_experiment(source, library):
    """Copy an external folder/archive/legacy snapshot into permanent storage."""
    source, library = Path(source).resolve(), Path(library).resolve()
    if source.is_dir():
        record = load_experiment_directory(source)
        if source.parent == library:
            return source
        if library.is_relative_to(source):
            raise ValueError('目标实验库不能位于待导入实验文件夹内部')
        if any(p.is_symlink() for p in source.rglob('*')):
            raise ValueError('实验文件夹含外部链接，请使用实际文件导入')
    elif source.suffix.lower() == '.json':
        record = _validate_record(json.loads(source.read_text(encoding='utf-8')))
        return export_experiment_directory(library, record, record.get('experiment_name') or record.get('project') or source.stem)
    elif source.suffix.lower() not in ('.zip', '.cppx'):
        raise ValueError('请选择完整实验文件夹或 .cppx/.zip/.json 实验记录')
    library.mkdir(parents=True, exist_ok=True)
    with _staging_directory(library, '.cpp_import_') as temporary:
        staged = Path(temporary) / 'experiment'
        if source.is_dir():
            shutil.copytree(source, staged)
        else:
            staged.mkdir()
            _extract_portable_archive(source, staged)
            record = load_experiment_directory(staged)
        name = record.get('experiment_name') or record.get('project') or source.stem
        stem = source.name if source.is_dir() and re.fullmatch(r'\d{8}_\d{6}_.+', source.name) else _experiment_stem(name)
        load_experiment_directory(staged)  # Validate copied assets before publishing.
        return _publish_directory(staged, library, stem)
