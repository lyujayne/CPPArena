# -*- coding: utf-8 -*-
"""区域数据集管理：KML / 图片导入统一入口，工程保存/加载。"""
import json
import os
import shutil
from typing import List, Optional, Tuple

from core.base_algorithm import Region, CameraParams
from data.coord_transform import CoordTransform
from data.kml_handler import parse_kml

XY = Tuple[float, float]


class Dataset:
    """一个实验数据集：多个区域 + 起飞点 + 坐标系信息。"""

    def __init__(self, name: str = "数据集"):
        self.name = name
        self.regions: List[Region] = []
        self.launch_point: Optional[XY] = None
        self.epsg: int = 32650
        self._next_region_id = 0
        # 图片底图模式
        self.bg_image_path: Optional[str] = None
        self.bg_corners_lonlat: Optional[List[Tuple[float, float]]] = None  # 四角经纬度
        self.bg_bounds_utm: Optional[Tuple[float, float, float, float]] = None  # (minx,miny,maxx,maxy)

    # ---------------- 区域操作 ----------------
    def add_region(self, name: str, vertices: List[XY]) -> Region:
        if len(vertices) < 3:
            raise ValueError("多边形顶点数必须 ≥ 3")
        region = Region(id=self._next_region_id, name=name, vertices=list(vertices))
        self._next_region_id += 1
        self.regions.append(region)
        return region

    def remove_region(self, region_id: int):
        self.regions = [r for r in self.regions if r.id != region_id]

    def rename_region(self, region_id: int, new_name: str):
        for r in self.regions:
            if r.id == region_id:
                r.name = new_name
                return

    def region_by_id(self, region_id: int) -> Optional[Region]:
        for r in self.regions:
            if r.id == region_id:
                return r
        return None

    def bounds(self):
        xs, ys = [], []
        for r in self.regions:
            xs += [p[0] for p in r.vertices]
            ys += [p[1] for p in r.vertices]
        if self.launch_point:
            xs.append(self.launch_point[0])
            ys.append(self.launch_point[1])
        if not xs:
            return None
        return (min(xs), min(ys), max(xs), max(ys))

    # ---------------- KML 导入 ----------------
    def load_kml(self, kml_path: str):
        """导入 KML：仅把多边形当作地块/地图导入，WGS84 → UTM。

        KML 中的 Point 地标不再被识别为起飞点；起飞点由用户在画布上
        手动标记（"▲ 标记起飞点"）。UTM 带按多边形自身位置选择，
        避免 Point 与 Polygon 跨地区时投影带选错。
        """
        regions_ll = parse_kml(kml_path)
        if not regions_ll:
            raise ValueError("KML 中未找到多边形地标")
        lon0, lat0 = regions_ll[0][1][0]
        tf = CoordTransform(lon=lon0, lat=lat0)
        self.epsg = tf.epsg
        self.regions.clear()
        self._next_region_id = 0
        for name, pts_ll in regions_ll:
            self.add_region(name, tf.points_lonlat_to_utm(pts_ll))
        return tf

    def launch_lonlat(self, tf: CoordTransform) -> Optional[Tuple[float, float]]:
        if self.launch_point is None:
            return None
        return tf.utm_to_lonlat(*self.launch_point)

    # ---------------- 序列化 ----------------
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "epsg": self.epsg,
            "regions": [r.to_dict() for r in self.regions],
            "launch_point": self.launch_point,
            "bg_image_path": self.bg_image_path,
            "bg_corners_lonlat": self.bg_corners_lonlat,
            "bg_bounds_utm": self.bg_bounds_utm,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Dataset":
        ds = cls(name=d.get("name", "数据集"))
        ds.epsg = int(d.get("epsg", 32650))
        ds.launch_point = tuple(d["launch_point"]) if d.get("launch_point") else None
        for rd in d.get("regions", []):
            r = Region.from_dict(rd)
            ds.regions.append(r)
            ds._next_region_id = max(ds._next_region_id, r.id + 1)
        ds.bg_image_path = d.get("bg_image_path")
        ds.bg_corners_lonlat = d.get("bg_corners_lonlat")
        ds.bg_bounds_utm = tuple(d["bg_bounds_utm"]) if d.get("bg_bounds_utm") else None
        return ds


class Project:
    """工程文件：数据集 × 相机参数 × 算法选择 × 实验设置。"""

    def __init__(self):
        self.datasets: List[Dataset] = []
        self.camera: CameraParams = CameraParams()
        self.selected_algorithms: List[str] = []
        self.baseline_algorithm: Optional[str] = None
        self.seeds: List[int] = [42]
        self.experiment_mode: str = "single"
        self.name: str = "未命名工程"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": 1,
            "camera": self.camera.as_dict(),
            "datasets": [ds.to_dict() for ds in self.datasets],
            "selected_algorithms": self.selected_algorithms,
            "baseline_algorithm": self.baseline_algorithm,
            "seeds": self.seeds,
            "experiment_mode": self.experiment_mode,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        p = cls()
        p.name = d.get("name", "未命名工程")
        p.camera = CameraParams.from_dict(d.get("camera", {}))
        p.datasets = [Dataset.from_dict(x) for x in d.get("datasets", [])]
        p.selected_algorithms = d.get("selected_algorithms", [])
        p.baseline_algorithm = d.get("baseline_algorithm")
        p.seeds = [int(s) for s in d.get("seeds", [42])]
        p.experiment_mode = d.get("experiment_mode", "single")
        return p

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
