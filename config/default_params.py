# -*- coding: utf-8 -*-
"""全局默认参数。

ACO 核心四参数对齐基准论文：
《A method for planning multirotor UAV flight paths to cover areas using
 the Ant Colony Optimization metaheuristic》
（α=0.5, β=20, ρ=0.7, Q=1, 最大迭代 500, 蚂蚁数=节点总数）。
此外按论文 §3.4 提到的“随机因子（random factor）”与 Algorithm 2 的
ANT-cycle 流程，补齐了前期探索→后期利用相关参数：exploration_prob
（初始探索率，随迭代余弦衰减到 0）、rcl_ratio（GRASP 受限候选池占比）、
elite_weight / elite_delay（全局最优精英沉积强度与启用时机）、tau0
（<=0 时自动取 Q/L_nn）。这些参数用于消除 β=20 下第 0 代即早熟锁死、
收敛曲线呈水平线的问题。
"""

import os

APP_NAME = "CPP Arena"
APP_VERSION = "1.4.0"

# 项目根目录（cpp_arena/）
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
        "alpha": 0.5,            # 信息素权重 α（论文）
        "beta": 20.0,            # 距离权重 β（论文）
        "rho": 0.7,              # 信息素挥发率 ρ（论文）
        "Q": 1.0,                # 信息素沉积量 Q（论文）
        "max_iterations": 500,   # 最大迭代次数（论文）
        # 以下为论文“随机因子”+ ANT-cycle 探索-利用机制的实现参数
        "exploration_prob": 0.5, # 初始随机探索率（随迭代余弦衰减到 0；0=关闭，会早熟锁死）
        "rcl_ratio": 0.2,        # GRASP 受限候选池占比（探索时只在最近的该比例候选中随机）
        "elite_weight": 25.0,    # 全局最优路径的精英信息素沉积权重（0=不强化最优）
        "elite_delay": 0.2,      # 精英沉积在该迭代占比之后才线性启用（先探索后强化）
        "tau0": 0.0,             # 信息素初值（<=0 自动取 Q/最近邻路径长度，量纲自适应）
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

# PSO-FA3ACO（Wu et al. 2025 文献完整算法）：
# PSO-DCAS 分割参数（Algorithm 2 / Table 1）+ FA3ACO 求解器参数（Algorithm 3-4）
ALGORITHM_DEFAULTS["PSO-FA3ACO"] = {
    # ---- PSO 动态凹区域分割（论文 Algorithm 2 / Table 1）----
    "pso_swarm_size": 40,    # 粒子种群规模 M（论文未明确分割阶段取值，平台默认 40）
    "pso_iterations": 120,   # PSO 最大迭代次数 MaxFEs（平台默认 120，可调大）
    "pso_w_max": 0.9,        # 惯性权重上限（论文 Table 1）
    "pso_w_min": 0.2,        # 惯性权重下限（论文 Table 1）
    "pso_c1": 2.0,           # 个体学习因子（论文 Table 1）
    "pso_c2": 2.0,           # 群体学习因子（论文 Table 1）
    # ---- FA3ACO 区域访问顺序求解（论文 §4 / Algorithm 3-4）----
    "ants_count": 20,        # 蚂蚁数 m（论文 §5.1 统一为 20）
    "max_iterations": 500,   # 最大迭代（论文 §5.1 统一为 500）
    "alpha": 1.0,            # 信息素权重 α（论文 Eq.15 未给值，取经典 1）
    "beta": 1.0,             # 距离权重 β（论文未给值；CPP 距离比大，取 1 保探索）
    "Q": 1.0,                # 信息素沉积量
    # 改进 1：分数阶状态转移（Eq.16）
    "fractional_order": 1,   # 1=开启分数阶历史记忆；0=退化为标准一阶转移
    "mu": 0.5,               # 分数阶阶数 μ∈(0,1)（论文仅限定区间，默认 0.5）
    # 改进 2：自适应信息素蒸发率（Eq.18）
    "adaptive_rho": 1,       # 1=ρ(t) 指数衰减；0=使用固定 rho_fixed
    "rho_max": 0.9,          # 初期蒸发率（强探索，抵消贪心边雪崩沉积）
    "rho_min": 0.05,         # 后期蒸发率（强利用）
    "rho_decay_k": 3.0,      # ρ(t)=ρ_min+(ρ_max-ρ_min)e^{-k·t/T} 的 k
    "rho_fixed": 0.1,        # 关闭自适应时的固定蒸发率
    # 改进 3：3-opt 局部搜索（Algorithm 3）
    "use_three_opt": 1,      # 1=每只蚂蚁构建后做 3-opt 至局部最优
    "tau0": 0.0,             # 信息素初值（<=0 自动取 Q/最近邻路径长度）
    "seed": 42,
}

# 各算法作者/文献引用/适用范围元信息（用于论文素材生成）
ALGORITHM_META = {
    "ACO-GTSP": {
        "author": "论文基准算法",
        "citation": "（请填入基准论文引用）",
        "scope": "元启发式；适用于平坦无障碍农田区域的多边形覆盖路径规划。"
                 "三步法：凸分解 → 牛耕式内部路径 → ACO 求解 E-GTSP 访问顺序。",
        "params_note": ("α=0.5, β=20, ρ=0.7, Q=1 为论文穷举最优组合；另按论文随机因子与 "
                        "ANT-cycle 流程默认开启前期探索(exploration_prob=0.5，余弦衰减)、"
                        "RCL 受限候选(rcl_ratio=0.2)与全局最优精英沉积(elite_weight=25)，"
                        "避免 β=20 下第 0 代早熟、收敛曲线水平。"),
    },
    "PSO-FA3ACO": {
        "author": "Wu W., Wang Z., Lin L., Chang X., Tian L.（青海师范大学 / 华北科技学院）",
        "citation": ("Wu W., Wang Z., Lin L., Chang X., Tian L. An efficient coverage "
                     "path planning method for UAV in complex concave regions. Scientific "
                     "Reports, 2025, 15:37227. DOI: 10.1038/s41598-025-20978-8"),
        "scope": ("论文完整两阶段 PSO-FA3ACO：① 粒子群动态凹区域分割（PSO-DCAS）——"
                  "叉积法识别凹点（Eq.1-2），每个凹点一个切割方向角，以各凸子区旋转"
                  "卡壳最小宽度之和 min Σw(R_i)（Eq.3/8）为适应度，PSO（Eq.13/14）"
                  "全局优化切割方向；② 凸子区牛耕式往复扫描（4 种进出点方案）；"
                  "③ FA3ACO 求解区域访问顺序——分数阶状态转移（Eq.16，"
                  "Grünwald–Letnikov 历史记忆）、自适应信息素蒸发率（Eq.18）、"
                  "3-opt 局部搜索（Algorithm 3 的 8 种断边重连）。三个改进均有开关，"
                  "可复现论文 Table 2 的 ACO/3opt-ACO/fractional-ACO/Hybrid-ACO/"
                  "FA3ACO 消融对比，以及 Table 3/4 的分割方法对比。"),
        "params_note": ("PSO：c1=c2=2、惯性权重 w 由 0.9 线性衰减到 0.2（论文 Table 1），"
                        "种群 40、迭代 120 为平台默认（论文未明确分割阶段 M/MaxFEs）。"
                        "FA3ACO：蚂蚁 20、迭代 500（论文 §5.1）；α=1、β=1（论文未给 "
                        "FA3ACO 自身 α/β；CPP 子区进出点距离比大，β 过高会首代即贪心"
                        "锁死，β=1 配合 3-opt 保证全局采样与局部求精）；μ=0.5、"
                        "ρ_max=0.9→ρ_min=0.05、"
                        "k=3 为分数阶/蒸发率常用取值（论文仅限定 μ∈(0,1)、给出 Eq.18 "
                        "形式而未列参数值），均可在面板调整。"),
    },
    "贪心最近邻": {
        "author": "CPP Arena 内置基线",
        "citation": "本平台实现",
        "scope": "确定性对照算法：每次选择距离当前位置最近的未访问区域。",
        "params_note": "无算法参数，使用全局相机参数。",
    },
    "导入顺序": {
        "author": "CPP Arena 内置基线",
        "citation": "本平台实现；等价 Mission Planner 按导入顺序访问",
        "scope": "确定性对照算法：按用户导入区域顺序依次访问，作为论文对照基线。",
        "params_note": "无算法参数，使用全局相机参数。",
    },
    "水平扫描 (插件示例)": {
        "author": "CPP Arena 插件示例",
        "citation": "本平台示例插件",
        "scope": "演示插件机制的扩展算法：固定水平方向做牛耕扫描（不按最优方向）。",
        "params_note": "无算法参数，使用全局相机参数。",
    },
}
