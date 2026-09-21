# -*- coding: utf-8 -*-
"""全局默认参数。

ACO 参数严格对齐基准论文：
《A method for planning multirotor UAV flight paths to cover areas using
 the Ant Colony Optimization metaheuristic》
（α=0.5, β=20, ρ=0.7, Q=1, 最大迭代 500, 蚂蚁数=节点总数）
"""

import os

APP_NAME = "CPPBench"
APP_VERSION = "2.0.0"

# 项目根目录（cppbench/）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPERIMENT_DIR = os.path.join(BASE_DIR, "experiments")
PLUGIN_DIR = os.path.join(BASE_DIR, "algorithms", "plugins")
PROJECT_DIR = os.path.join(BASE_DIR, "projects")

for _d in (EXPERIMENT_DIR, PROJECT_DIR):
    os.makedirs(_d, exist_ok=True)


# ---------------------------------------------------------------- 相机/飞行参数
CAMERA_DEFAULTS = {
    "focal_length_mm": 5.2,     # 相机焦距 (mm)
    "sensor_width_mm": 7.6,     # 传感器宽度 (mm)
    "sensor_height_mm": 5.7,    # 传感器高度 (mm)
    "image_width_px": 5472,     # 影像像素宽 (px)，用于计算 GSD
    "image_height_px": 3648,    # 影像像素高 (px)
    "flight_height_m": 100.0,   # 飞行高度 (m)
    "side_overlap_pct": 80.0,   # 旁向重叠率 (%)
    "heading_overlap_pct": 80.0,# 航向重叠率 (%)
}

# 相机参数界面展示顺序
CAMERA_PARAM_ORDER = [
    ("focal_length_mm", "相机焦距 (mm)"),
    ("sensor_width_mm", "传感器宽度 (mm)"),
    ("sensor_height_mm", "传感器高度 (mm)"),
    ("image_width_px", "影像宽 (px)"),
    ("image_height_px", "影像高 (px)"),
    ("flight_height_m", "飞行高度 (m)"),
    ("side_overlap_pct", "旁向重叠率 (%)"),
    ("heading_overlap_pct", "航向重叠率 (%)"),
]


def compute_camera(cam):
    """由相机参数计算 GSD、单幅覆盖宽/高、航线间距（旁向）、航向间距。"""
    f = float(cam["focal_length_mm"])
    sw = float(cam["sensor_width_mm"])
    sh = float(cam["sensor_height_mm"])
    iw = float(cam["image_width_px"])
    ih = float(cam["image_height_px"])
    h = float(cam["flight_height_m"])
    ov_s = float(cam["side_overlap_pct"]) / 100.0
    ov_h = float(cam["heading_overlap_pct"]) / 100.0

    if f <= 0 or sw <= 0 or sh <= 0 or iw <= 0 or ih <= 0 or h <= 0:
        raise ValueError("相机参数必须为正数")

    coverage_w = sw * h / f          # 单幅影像地面覆盖宽 (m)
    coverage_h = sh * h / f          # 单幅影像地面覆盖高 (m)
    gsd = coverage_w / iw            # 地面采样距离 (m/px)，横向口径
    line_spacing = coverage_w * (1.0 - ov_s)   # 旁向航线间距 (m)
    along_spacing = coverage_h * (1.0 - ov_h)  # 航向拍照间距 (m)
    return {
        "coverage_w": coverage_w,
        "coverage_h": coverage_h,
        "gsd": gsd,
        "line_spacing": line_spacing,
        "along_spacing": along_spacing,
    }


# ---------------------------------------------------------------- 算法默认参数
ALGORITHM_DEFAULTS = {
    "ACO-GTSP": {
        "alpha": 0.5,            # 信息素权重 α
        "beta": 20.0,            # 距离权重 β
        "rho": 0.7,              # 信息素挥发率 ρ
        "Q": 1.0,                # 信息素沉积量 Q
        "max_iterations": 500,   # 最大迭代次数
        "exploration_prob": 0.0, # 随机探索概率（论文最优为 0）
        "tau0": 1.0,             # 信息素初值
        "seed": 42,
    },
    "贪心最近邻": {
        "seed": 42,
    },
    "导入顺序": {
        "seed": 42,
    },
    "水平扫描 (插件示例)": {
        "seed": 42,
    },
}

# 各算法作者/文献引用/适用范围元信息（用于论文素材生成）
ALGORITHM_META = {
    "ACO-GTSP": {
        "author": "论文基准算法",
        "citation": "（请填入基准论文引用）",
        "scope": "元启发式；适用于平坦无障碍农田区域的多边形覆盖路径规划。"
                 "三步法：凸分解 → 牛耕式内部路径 → ACO 求解 E-GTSP 访问顺序。",
        "params_note": "α=0.5, β=20, ρ=0.7, Q=1 为论文穷举最优组合。",
    },
    "贪心最近邻": {
        "author": "CPPBench 内置基线",
        "citation": "本平台实现",
        "scope": "确定性对照算法：每次选择距离当前位置最近的未访问区域。",
        "params_note": "无算法参数，使用全局相机参数。",
    },
    "导入顺序": {
        "author": "CPPBench 内置基线",
        "citation": "本平台实现；等价 Mission Planner 按导入顺序访问",
        "scope": "确定性对照算法：按用户导入区域顺序依次访问，作为论文对照基线。",
        "params_note": "无算法参数，使用全局相机参数。",
    },
    "水平扫描 (插件示例)": {
        "author": "CPPBench 插件示例",
        "citation": "本平台示例插件",
        "scope": "演示插件机制的扩展算法：固定水平方向做牛耕扫描（不按最优方向）。",
        "params_note": "无算法参数，使用全局相机参数。",
    },
}
