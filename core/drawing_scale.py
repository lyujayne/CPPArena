"""Metric drawing validation and explicit width calibration."""
import math
from shapely.geometry import Polygon


def validate_regions(dataset, camera):
    issues = []
    spacing = camera.line_spacing
    for region in dataset.regions:
        if any(not math.isfinite(float(v)) for p in region.vertices for v in p):
            issues.append(f'{region.name}：坐标包含非有限值，请重新勾绘。')
            continue
        polygon = Polygon(region.vertices)
        if not polygon.is_valid or polygon.area <= 1e-8:
            issues.append(f'{region.name}：多边形自交或面积为零，请重新勾绘。')
            continue
        x0, y0, x1, y1 = polygon.bounds
        width, height = x1-x0, y1-y0
        if min(width, height) < max(.1, spacing*.05):
            issues.append(f'{region.name}：尺寸仅 {width:.3f} × {height:.3f} m，'
                          f'当前航线间距 {spacing:.2f} m；请使用“尺寸校准”或调整相机参数。')
        if max(width, height) > 100000 or max(abs(v) for p in region.vertices for v in p) > 1e8:
            issues.append(f'{region.name}：范围或坐标量级异常，请重新设定尺寸/导入坐标。')
    return issues


def calibrate_dataset(dataset, target_width):
    bounds = dataset.bounds()
    if not bounds or target_width <= 0 or not math.isfinite(target_width):
        raise ValueError('请输入正数宽度（米）。')
    # Only region vertices define the calibration width; launch follows the transform.
    xs = [p[0] for r in dataset.regions for p in r.vertices]
    ys = [p[1] for r in dataset.regions for p in r.vertices]
    width = max(xs)-min(xs)
    if width <= 1e-9:
        raise ValueError('当前图形没有有效宽度。')
    factor = target_width / width
    origin = ((min(xs)+max(xs))/2, (min(ys)+max(ys))/2)
    scale = lambda p: (origin[0]+(p[0]-origin[0])*factor, origin[1]+(p[1]-origin[1])*factor)
    for r in dataset.regions:
        r.vertices = [scale(p) for p in r.vertices]
    if dataset.launch_point:
        dataset.launch_point = scale(dataset.launch_point)
    # Scaling changes geometry relative to georeferenced images.
    dataset.bg_image_path = None
    dataset.bg_bounds_utm = None
    return factor
