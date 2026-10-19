# -*- coding: utf-8 -*-
"""WGS84 经纬度 ↔ UTM 平面米制坐标转换（pyproj）。"""
from typing import List, Tuple

import pyproj

LonLat = Tuple[float, float]
XY = Tuple[float, float]


def utm_epsg_for(lon: float, lat: float) -> int:
    """由经纬度确定 UTM 投影 EPSG 代码（北/南半球自动选择）。"""
    zone = int((lon + 180.0) // 6) + 1
    zone = max(1, min(60, zone))
    if lat >= 0:
        return 32600 + zone
    return 32700 + zone


class CoordTransform:
    """WGS84 ↔ UTM 转换器（携带固定 EPSG，保证同一数据集内坐标系一致）。"""

    def __init__(self, epsg: int = None, lon: float = 0.0, lat: float = 0.0):
        if epsg is None:
            epsg = utm_epsg_for(lon, lat)
        self.epsg = int(epsg)
        self._to_utm = pyproj.Transformer.from_crs(
            "EPSG:4326", f"EPSG:{self.epsg}", always_xy=True)
        self._to_lonlat = pyproj.Transformer.from_crs(
            f"EPSG:{self.epsg}", "EPSG:4326", always_xy=True)

    def lonlat_to_utm(self, lon: float, lat: float) -> XY:
        x, y = self._to_utm.transform(lon, lat)
        return (float(x), float(y))

    def utm_to_lonlat(self, x: float, y: float) -> LonLat:
        lon, lat = self._to_lonlat.transform(x, y)
        return (float(lon), float(lat))

    def points_lonlat_to_utm(self, pts: List[LonLat]) -> List[XY]:
        return [self.lonlat_to_utm(*p) for p in pts]

    def points_utm_to_lonlat(self, pts: List[XY]) -> List[LonLat]:
        return [self.utm_to_lonlat(*p) for p in pts]
