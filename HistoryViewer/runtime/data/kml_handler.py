# -*- coding: utf-8 -*-
"""KML 导入/导出（基于 lxml，兼容 Google Earth Pro 导出文件与 Mission Planner）。"""
import os
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

KML_NS = "http://www.opengis.net/kml/2.2"
NS = {"kml": KML_NS}
KML_NSMAP = {None: KML_NS}

LonLat = Tuple[float, float]


def _parse_coords(text: str) -> List[Tuple[float, float, float]]:
    """解析 "lon,lat,alt lon,lat,alt ..." → [(lon,lat,alt), ...]。"""
    out = []
    for token in text.replace("\t", " ").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
            alt = float(parts[2]) if len(parts) > 2 else 0.0
        except ValueError:
            continue
        out.append((lon, lat, alt))
    return out


def parse_kml(path: str):
    """解析 KML 文件，仅提取多边形地块（作为地图导入）。

    KML 中的 Point 地标不再被识别为起飞点；起飞点由用户在画布上
    手动标记。这样可避免 Point 与 Polygon 跨地区时把 UTM 带选错。

    :return: regions: [(name, [(lon,lat), ...])]  多边形地标
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"文件不存在: {path}")
    tree = ET.parse(path)
    root = tree.getroot()

    regions = []

    for pm in root.findall(".//kml:Placemark", NS):
        name_el = pm.find("kml:name", NS)
        name = (name_el.text or "").strip() if name_el is not None else ""

        poly = pm.find(".//kml:Polygon", NS)
        if poly is not None:
            ring = poly.find(
                ".//kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", NS)
            if ring is not None and ring.text:
                coords = _parse_coords(ring.text)
                if len(coords) >= 3:
                    regions.append((name or f"区域{len(regions) + 1}",
                                    [(c[0], c[1]) for c in coords]))

    if not regions:
        raise ValueError("KML 中未找到多边形地标（Polygon Placemark）")
    return regions


def write_waypoints_kml(waypoints_lonlat_alt: List[Tuple[float, float, float]],
                        path: str, name: str = "Mission"):
    """导出航点为 KML（Mission Planner 可识别的 WP Placemark 格式）。"""
    doc = ET.Element("kml", KML_NSMAP)
    document = ET.SubElement(doc, "Document")
    ET.SubElement(document, "name").text = name
    folder = ET.SubElement(document, "Folder")
    ET.SubElement(folder, "name").text = "Mission"

    for i, (lon, lat, alt) in enumerate(waypoints_lonlat_alt):
        pm = ET.SubElement(folder, "Placemark")
        ET.SubElement(pm, "name").text = f"WP {i}"
        p = ET.SubElement(pm, "Point")
        ET.SubElement(p, "coordinates").text = f"{lon:.9f},{lat:.9f},{alt:.1f}"

    tree = ET.ElementTree(doc)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path
