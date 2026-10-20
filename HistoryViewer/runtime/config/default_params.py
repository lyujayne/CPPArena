# -*- coding: utf-8 -*-
"""Paper-aligned defaults. Values absent from papers are identified below.
See PAPER_ALIGNMENT.md for differences between Wu's text and public MATLAB code.
"""
import os
import sys

APP_NAME = "CPP Arena"
APP_VERSION = "2.4"

# 项目根目录（cpp_arena/）
# 打包为 exe（PyInstaller 冻结）后：只读资源在 sys._MEIPASS（临时解压目录），
# 实验记录、工程等用户可写数据放在 exe 所在目录，避免关闭程序后随临时目录丢失。
def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


BASE_DIR = _base_dir()
RESOURCE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)


def resolve_versioned_path(path):
    """Rebase existing local assets/projects after the source folder is renamed."""
    if not path or os.path.exists(path):
        return path
    import re
    from pathlib import Path
    base = Path(BASE_DIR).resolve()
    source = Path(path)
    for parent in source.parents:
        if (re.fullmatch(r'CPP _Arena_v\d+(?:\.\d+)*', parent.name)
                and parent.parent.resolve() == base.parent):
            candidate = (base / source.relative_to(parent)).resolve()
            if base in candidate.parents and candidate.exists():
                return str(candidate)
    return path


EXPERIMENT_DIR = os.path.join(BASE_DIR, "experiments")
PLUGIN_DIR = os.path.join(BASE_DIR, "algorithms", "plugins")
PROJECT_DIR = os.path.join(BASE_DIR, "projects")
PICTURE_DIR = os.path.join(BASE_DIR, 'pictures')
DATASET_LIBRARY_DIR = os.path.join(BASE_DIR, 'dataset_library')
COMPONENT_DIR = os.path.join(BASE_DIR, 'components')


def _history_viewer_dir():
    if os.path.isfile(os.path.join(BASE_DIR, 'viewer.py')):
        # A repository copy shares the user's existing sibling deployment.
        if os.path.isfile(os.path.join(os.path.dirname(BASE_DIR), 'main.py')):
            sibling = os.path.join(os.path.dirname(os.path.dirname(BASE_DIR)), 'HistoryViewer')
            if os.path.isfile(os.path.join(sibling, 'viewer.py')):
                return sibling
        return BASE_DIR  # A copied standalone viewer keeps its own library.
    sibling = os.path.join(os.path.dirname(BASE_DIR), 'HistoryViewer')
    return sibling if os.path.isfile(os.path.join(sibling, 'viewer.py')) else os.path.join(BASE_DIR, 'HistoryViewer')


HISTORY_VIEWER_DIR = _history_viewer_dir()
HISTORY_EXPERIMENT_DIR = os.path.join(HISTORY_VIEWER_DIR, 'experiments')

for _d in (EXPERIMENT_DIR, PROJECT_DIR, PICTURE_DIR):
    os.makedirs(_d, exist_ok=True)


# ---------------------------------------------------------------- 相机/飞行参数
CAMERA_DEFAULTS = {
    "scan_boundary_mode": "inside",
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

    if not 0 <= ov_s < 1 or not 0 <= ov_h < 1:
        raise ValueError("旁向和航向重叠率必须在 [0,100%)")

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
    "ACO-GTSP": {"alpha": .5, "beta": 20., "rho": .7, "Q": 1.,
        "max_iterations": 500, "exploration_prob": .1, "tau0": 1., "seed": 42},
    "贪心最近邻": {"seed": 42}, "导入顺序": {"seed": 42},
    "水平扫描 (插件示例)": {"seed": 42},
}
# Kato 未明确 random factor / tau0 的数值；.1 与 1 是实现取值。
ALGORITHM_DEFAULTS["Enhanced-ECD-ACO"] = dict(ALGORITHM_DEFAULTS["ACO-GTSP"])
ALGORITHM_DEFAULTS["PSO-FA3ACO"] = {
    "pso_swarm_size": 40, "pso_iterations": 120,  # 分割阶段预算未公开
    "pso_w_max": .9, "pso_w_min": .2, "pso_c1": 2., "pso_c2": 2.,
    "pso_vmax_ratio": .15, "pso_warm_start": 0, "pso_merge_slivers": 0,
    "pso_sliver_diag_ratio": .001,
    "ants_count": 80, "max_iterations": 500,  # 论文第14页；20是独立运行次数
    "alpha": 1., "beta": 5.,  # 作者 main.m；论文未列本算法此参数
    "Q": 1., "mu": .5, "memory_strength": .1,  # 作者积分阶数与强度
    "fractional_order": 1,
    "fractional_mode": 1,  # 1作者历史信息素积分；0论文有符号Eq.16核验
    "adaptive_rho": 1, "rho_min": .05, "rho_max": .9,
    "rho_decay_k": .006,  # 每迭代实际k，原文未给值，不能与旧k=3混用
    "rho_fixed": .5, "use_three_opt": 1, "tau0": 1., "seed": 42,
}
ALGORITHM_DEFAULTS["Enhanced-ECD-DP"] = {
    "dp_max_groups": 16, "li_start_group": 0, "li_end_group": 0, "seed": 42,
    "li_adjacency_mode": 0,
}

ALGORITHM_META = {
    "ACO-GTSP": {
        "author": "Kato et al. (2025)",
        "citation": "Computers and Electronics in Agriculture 231:109983",
        "scope": "Bayazit凸分解、四方案牛耕扫描、随机起点ACO求解闭环E-GTSP。",
        "params_note": "α=.5 β=20 ρ=.7 Q=1；全候选随机探索、常数Q沉积。探索概率及tau0原文未给具体值。",
    },
    "PSO-FA3ACO": {
        "author": "Wu et al. (2025)",
        "citation": "Scientific Reports 15:37227, DOI 10.1038/s41598-025-20978-8",
        "scope": "PSO最小宽度和分割、牛耕扫描、历史信息素积分、自适应挥发及完整闭环3-opt。",
        "params_note": "论文框架与作者公开记忆核结合，不能严格逐式复现。论文Eq.16与作者代码不同；模式0核验原式，负概率报错。论文种群80，20为独立运行次数。分割预算为实现取值。",
    },
    "Enhanced-ECD-ACO": {
        "author": "Li et al. (2011) 分割 + Kato ACO",
        "citation": "Mechatronics 21:876–885; 10.1016/j.mechatronics.2010.10.009",
        "scope": "增强精确单元分解与ACO的组合实验，不是Li原文完整算法。",
        "params_note": "分割按Fig.8及§4.5，区域连接使用Kato ACO。",
    },
    "Enhanced-ECD-DP": {
        "author": "Li et al. (2011)",
        "citation": "Mechatronics 21:876–885; 10.1016/j.mechatronics.2010.10.009",
        "scope": "增强分割与开放DP。默认允许不相邻子区转场（工程扩展）；转场约束1为Li论文的严格邻接图。",
        "params_note": "li_adjacency_mode=0通用转场，1严格邻接；两种模式均用精确DP。起终编号0表示自动选择。起降附加航段不参与连接目标。严格模式无解时明确说明，不自动放宽；超过子区/内存上限时报错。",
    },
}
