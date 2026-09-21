# -*- coding: utf-8 -*-
"""航点导出（.kml / .csv / .txt）。"""
import csv
import os
from typing import List, Tuple

from data.kml_handler import write_waypoints_kml

LonLatAlt = Tuple[float, float, float]


def export_waypoints(waypoints_lonlat_alt: List[LonLatAlt],
                     path: str, mission_name: str = "Mission") -> str:
    """按扩展名自动选择格式导出航点。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".kml":
        write_waypoints_kml(waypoints_lonlat_alt, path, name=mission_name)
    elif ext == ".csv":
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["序号", "经度", "纬度", "高度"])
            for i, (lon, lat, alt) in enumerate(waypoints_lonlat_alt):
                w.writerow([i, f"{lon:.9f}", f"{lat:.9f}", f"{alt:.1f}"])
    elif ext == ".txt":
        with open(path, "w", encoding="utf-8") as f:
            f.write("序号 经度 纬度 高度\n")
            for i, (lon, lat, alt) in enumerate(waypoints_lonlat_alt):
                f.write(f"{i} {lon:.9f} {lat:.9f} {alt:.1f}\n")
    else:
        raise ValueError("不支持的导出格式，请使用 .kml / .csv / .txt")
    return path
