# -*- coding: utf-8 -*-
"""统一算法抽象接口与统一结果结构（平台核心设计）。

所有 CPP 算法实现 BaseCPPAlgorithm 抽象接口，保证可插拔与公平比较：
相同的区域数据、相机参数、指标口径。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

XY = Tuple[float, float]


@dataclass
class Region:
    """一个待覆盖地块（UTM 平面米制坐标）。"""
    id: int
    name: str
    vertices: List[XY] = field(default_factory=list)  # 闭合环（首尾可重复）

    def ring(self) -> List[XY]:
        """返回闭合环（首尾相同），供 shapely 使用。"""
        pts = [(float(x), float(y)) for x, y in self.vertices]
        if len(pts) >= 3 and (pts[0] != pts[-1]):
            pts = pts + [pts[0]]
        return pts

    def to_dict(self):
        return {"id": self.id, "name": self.name, "vertices": self.vertices}

    @classmethod
    def from_dict(cls, d):
        return cls(id=d["id"], name=d.get("name", f"区域{d['id']}"),
                   vertices=[(float(x), float(y)) for x, y in d["vertices"]])


@dataclass
class CameraParams:
    """全局共享相机/飞行参数（公平比较口径）。"""
    focal_length_mm: float = 5.2
    sensor_width_mm: float = 7.6
    sensor_height_mm: float = 5.7
    image_width_px: int = 5472
    image_height_px: int = 3648
    flight_height_m: float = 100.0
    side_overlap_pct: float = 80.0
    heading_overlap_pct: float = 80.0

    def as_dict(self) -> dict:
        return {
            "focal_length_mm": self.focal_length_mm,
            "sensor_width_mm": self.sensor_width_mm,
            "sensor_height_mm": self.sensor_height_mm,
            "image_width_px": self.image_width_px,
            "image_height_px": self.image_height_px,
            "flight_height_m": self.flight_height_m,
            "side_overlap_pct": self.side_overlap_pct,
            "heading_overlap_pct": self.heading_overlap_pct,
        }

    @classmethod
    def from_dict(cls, d) -> "CameraParams":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})

    @property
    def line_spacing(self) -> float:
        from config.default_params import compute_camera
        return compute_camera(self.as_dict())["line_spacing"]


@dataclass
class CPPInput:
    """算法求解输入：区域列表、起飞点、相机参数。"""
    regions: List[Region]
    launch_point: XY
    camera: CameraParams


@dataclass
class CPPResult:
    """统一结果结构，所有算法必须返回。"""
    waypoints: List[XY]                     # 全局航点序列（含起飞/返航）
    total_distance: float                   # 总飞行距离 (m)
    total_turns: int                        # 总转弯次数
    region_order: List[int]                 # 区域访问顺序（区域 id 序列）
    internal_paths: List[List[XY]]          # 各区域内部路径
    convergence: List[float] = field(default_factory=list)   # 迭代轮次→最优值
    runtime: float = 0.0                    # 运行耗时 (s)
    seed: int = 0                           # 随机种子
    algorithm_name: str = ""                # 算法显示名
    metadata: Dict = field(default_factory=dict)  # 算法自定义信息

    def to_dict(self) -> dict:
        return {
            "waypoints": self.waypoints,
            "total_distance": round(self.total_distance, 3),
            "total_turns": self.total_turns,
            "region_order": self.region_order,
            "internal_paths": self.internal_paths,
            "convergence": [round(c, 3) for c in self.convergence],
            "runtime": round(self.runtime, 4),
            "seed": self.seed,
            "algorithm_name": self.algorithm_name,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d) -> "CPPResult":
        r = cls(
            waypoints=[(float(x), float(y)) for x, y in d["waypoints"]],
            total_distance=float(d["total_distance"]),
            total_turns=int(d["total_turns"]),
            region_order=[int(i) for i in d["region_order"]],
            internal_paths=[[(float(x), float(y)) for x, y in p]
                            for p in d.get("internal_paths", [])],
            convergence=[float(c) for c in d.get("convergence", [])],
            runtime=float(d.get("runtime", 0.0)),
            seed=int(d.get("seed", 0)),
            algorithm_name=d.get("algorithm_name", ""),
            metadata=d.get("metadata", {}),
        )
        return r


class BaseCPPAlgorithm(ABC):
    """统一算法接口。子类必须实现 solve()，并通过 registry 注册。"""

    # ---- 元数据（论文素材自动生成用）----
    name: str = "Base"                    # 算法唯一标识
    display_name: str = "Base"            # 界面显示名
    description: str = ""                 # 算法描述
    author: str = ""
    citation: str = ""
    scope: str = ""
    params_note: str = ""
    default_params: dict = {}             # 默认参数
    deterministic: bool = False           # 是否为确定性算法

    @abstractmethod
    def solve(self, cpp_input: CPPInput, **params) -> CPPResult:
        """输入：区域列表、起飞点、相机参数 → 输出：统一结果结构。"""
        raise NotImplementedError

    def get_param_spec(self) -> List[Tuple[str, str, str, float]]:
        """参数表单规格：[(key, 标签, 类型('int'|'float'), 默认值), ...]。
        默认从 default_params 自动推断；可重写以自定义顺序/标签。"""
        spec = []
        for k, v in self.default_params.items():
            if k == "seed":
                continue
            typ = "int" if isinstance(v, bool) is False and isinstance(v, int) else "float"
            spec.append((k, k, typ, float(v)))
        return spec
