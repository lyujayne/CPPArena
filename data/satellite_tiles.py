# -*- coding: utf-8 -*-
"""卫星瓦片底图：根据 UTM 范围自动从 Esri World Imagery 下载瓦片拼接。

使用免费的 ArcGIS World Imagery 服务，无需 API key。
瓦片坐标系为 Web Mercator (EPSG:3857)，下载后按 UTM 范围对齐显示。
"""
import io
import math
import os
import tempfile
from typing import Optional, Tuple

import requests
from PIL import Image

TILE_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}")
TILE_SIZE = 256
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Referer": "https://livingatlas.arcgis.com/",
}


def _lonlat_to_tile(lon: float, lat: float, z: int) -> Tuple[int, int]:
    x = int((lon + 180.0) / 360.0 * (1 << z))
    lat_r = math.radians(max(-85.05, min(85.05, lat)))
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * (1 << z))
    return x, y


def _tile_to_lonlat(x: int, y: int, z: int) -> Tuple[float, float]:
    lon = x / (1 << z) * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * y / (1 << z)
    lat = math.degrees(math.atan(math.sinh(n)))
    return lon, lat


def _choose_zoom(span_m: float) -> int:
    """根据经度方向跨度（米）选 zoom：目标约 5 个瓦片覆盖跨度。"""
    # z 级时一行有 2^z 块瓦片，赤道上每块瓦片宽 = 40075016.7 / 2^z 米。
    WORLD_M = 40075016.7
    target_tile_m = span_m / 5.0  # 希望约 5 个瓦片覆盖地块宽度
    z = int(round(math.log2(WORLD_M / max(target_tile_m, 1.0))))
    return max(1, min(z, 19))


def fetch_satellite_basemap(
    lon_min: float, lat_min: float,
    lon_max: float, lat_max: float,
    out_path: Optional[str] = None,
    progress_cb=None,
) -> Tuple[str, Tuple[float, float, float, float]]:
    """下载并拼接卫星瓦片。

    返回 (图片路径, (lon0, lat0, lon1, lat1))——图片四角实际覆盖的经纬度范围。
    """
    if lon_max < lon_min:
        lon_min, lon_max = lon_max, lon_min
    if lat_max < lat_min:
        lat_min, lat_max = lat_max, lat_min

    # 用中点纬度估算跨度，选 zoom
    mid_lat = (lat_min + lat_max) / 2.0
    span_lon_m = (lon_max - lon_min) * 111320.0 * math.cos(math.radians(mid_lat))
    z = _choose_zoom(max(abs(span_lon_m), 1.0))

    x0, y0 = _lonlat_to_tile(lon_min, lat_max, z)  # 左上
    x1, y1 = _lonlat_to_tile(lon_max, lat_min, z)  # 右下
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)

    n_x = x1 - x0 + 1
    n_y = y1 - y0 + 1
    if n_x > 32 or n_y > 32:
        raise RuntimeError(f"瓦片范围过大（{n_x}×{n_y}），请降低飞行高度或缩小地块范围")

    total = n_x * n_y
    canvas = Image.new("RGB", (n_x * TILE_SIZE, n_y * TILE_SIZE))
    sess = requests.Session()
    sess.headers.update(HEADERS)

    for i, tx in enumerate(range(x0, x1 + 1)):
        for j, ty in enumerate(range(y0, y1 + 1)):
            url = TILE_URL.format(z=z, y=ty, x=tx)
            r = None
            for attempt in range(3):
                try:
                    r = sess.get(url, headers=HEADERS, timeout=20)
                    if r.status_code == 200:
                        break
                except requests.RequestException:
                    pass
            if r is None or r.status_code != 200:
                raise RuntimeError(
                    f"瓦片下载失败 HTTP {r.status_code if r else 'N/A'}: {url}")
            tile = Image.open(io.BytesIO(r.content)).convert("RGB")
            canvas.paste(tile, (i * TILE_SIZE, j * TILE_SIZE))
            if progress_cb:
                progress_cb((i * n_y + j + 1), total)

    # 实际覆盖的经纬度范围（瓦片边缘）
    img_lon_min, img_lat_max = _tile_to_lonlat(x0, y0, z)
    img_lon_max, img_lat_min = _tile_to_lonlat(x1 + 1, y1 + 1, z)

    if out_path is None:
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"cppa_sat_{os.getpid()}_{int(mid_lat*1e6)}_{z}.png")
    canvas.save(out_path, "PNG")
    return out_path, (img_lon_min, img_lat_min, img_lon_max, img_lat_max)
