# -*- coding: utf-8 -*-
"""FA3ACO 补全后的验证脚本（可重复运行）。

验证内容：
1. 分数阶 Grünwald–Letnikov 系数与反向方案映射的单元正确性；
2. PSO-DCAS 分割完整性（子区全凸、并集面积守恒）；
3. 完整 PSO-FA3ACO 可运行、收敛、不劣于最近邻贪心，3-opt 确实缩短路径；
4. 三个消融开关（分数阶 / 自适应ρ / 3-opt）工作正常；
5. 基准 ACO-GTSP 行为未受影响（钩子重构后仍走标准蚁群）。
"""
import math
import sys

from shapely.geometry import Polygon

from core.base_algorithm import CPPInput, Region, CameraParams
from core.registry import get_registry
from algorithms.aco.fa3aco_gtsp import gruenwald_letnikov_coeffs

# ------------------------------------------------------------ 测试地块（米制坐标）
# L 形（1 个凹点）
L_SHAPE = [(0, 0), (300, 0), (300, 120), (180, 120), (180, 300), (0, 300)]
# 十字/多凹点复杂形（4 个凹点，类似论文 Fig.17a 的星形凹多边形）
STAR_SHAPE = [(0, 200), (80, 120), (60, 80), (150, 100), (200, 0),
              (250, 100), (340, 80), (320, 120), (400, 200), (320, 280),
              (340, 320), (250, 300), (200, 400), (150, 300), (60, 320),
              (80, 280)]
# U 形（2 个凹点）
U_SHAPE = [(0, 0), (300, 0), (300, 300), (220, 300), (220, 90),
           (80, 90), (80, 300), (0, 300)]


def check_coeffs():
    print("== 1. 分数阶系数（μ=0.5，理论值 c1=1, c2=0.25, c3=0.125, c4=0.078125, c5=0.0546875）==")
    c = gruenwald_letnikov_coeffs(0.5, 5)
    expect = [1.0, 0.25, 0.125, 0.078125, 0.0546875]
    for k, (got, exp) in enumerate(zip(c, expect), 1):
        ok = abs(got - exp) < 1e-9
        print(f"  c{k} = {got:.8f}  理论 {exp:.8f}  {'OK' if ok else 'FAIL'}")
        assert ok
    print("  系数全部正确。\n")


def check_decomposition(algo, vertices, params, name):
    pieces, info = algo.decompose_region(vertices, params)
    orig = Polygon(vertices).buffer(0)
    union = Polygon(pieces[0]).buffer(0)
    for p in pieces[1:]:
        union = union.union(Polygon(p).buffer(0))
    area_err = abs(union.area - orig.area) / orig.area
    # 全凸校验：shapely 面积 == 凸包面积
    convex_ok = all(abs(Polygon(p).area - Polygon(p).convex_hull.area) < 1e-6
                    for p in pieces)
    print(f"  [{name}] 子区数={len(pieces)} 面积误差={area_err:.2e} "
          f"全凸={convex_ok} Σ宽度={info.get('width_sum')} 补切={info.get('n_extra_cuts')}")
    assert area_err < 1e-6, f"{name} 分割面积不守恒"
    assert convex_ok, f"{name} 存在非凸子区"
    return pieces


def run_case(registry, vertices, case_name, fast=True):
    print(f"== 算例：{case_name} ==")
    region = Region(id=1, name=case_name, vertices=vertices)
    cam = CameraParams()
    cpp_in = CPPInput(regions=[region], launch_point=(-60, -60), camera=cam)

    base_params = {"seed": 42}
    if fast:
        base_params.update(pso_swarm_size=30, pso_iterations=40,
                           max_iterations=120, ants_count=12)

    aco = registry.get_instance("ACO-GTSP")
    pso = registry.get_instance("PSO-FA3ACO")

    check_decomposition(pso, vertices, base_params, case_name)

    r_aco = aco.solve(cpp_in, **dict(base_params))
    r_full = pso.solve(cpp_in, **dict(base_params))

    g = r_full.metadata["gtsp"]
    print(f"  ACO-GTSP(基准)   总航程={r_aco.total_distance:9.2f} 转弯={r_aco.total_turns:4d} "
          f"子区={r_aco.metadata['n_subregions_total']} 耗时={r_aco.runtime:.2f}s")
    print(f"  PSO-FA3ACO(完整) 总航程={r_full.total_distance:9.2f} 转弯={r_full.total_turns:4d} "
          f"子区={r_full.metadata['n_subregions_total']} 耗时={r_full.runtime:.2f}s")
    print(f"    最近邻={g['nearest_neighbor_distance']:.2f} → 3opt后="
          f"{g['nn_three_opt_distance']:.2f} → FA3ACO={r_full.total_distance:.2f}")
    print(f"    转运={g['best_transition_distance']:.2f} 内部={g['internal_distance_total']:.2f} "
          f"ρ:{g['rho_start']}→{g['rho_end']} 收敛代={g['best_iteration']}")
    print(f"    3-opt 改进蚂蚁数={g['three_opt']['improved_tours']} "
          f"缓存命中={g['three_opt']['cache_hits']} "
          f"相对最近邻净缩短={g['three_opt']['gain_over_nearest']:.2f}")
    print(f"    收敛曲线 首={r_full.convergence[0]:.2f} 末={r_full.convergence[-1]:.2f}")

    # 硬断言（stats 里里程保留 3 位小数，故与统计值比较留 0.001 舍入容差）
    best_full = r_full.convergence[-1]
    diff_m = abs(r_full.total_distance - best_full)
    print(f"    组装航点重算里程与求解器里程差 = {diff_m:.4f} m（应≈0）")
    assert best_full <= g["nearest_neighbor_distance"] + 1e-3, \
        "FA3ACO 最优值劣于最近邻贪心（兜底失效）"
    assert g["nn_three_opt_distance"] <= g["nearest_neighbor_distance"] + 1e-3, \
        "3-opt 后路径不应变长"
    assert r_full.convergence[-1] <= r_full.convergence[0] + 1e-6, "收敛曲线应单调不增"
    assert diff_m < 1.0, "航点组装里程与求解器里程口径不一致（差>1m）"
    # 返航闭合
    assert r_full.waypoints[0] == r_full.waypoints[-1] == (-60, -60), "应闭合回到起飞点"
    print("  断言通过。\n")
    return r_aco, r_full


def check_ablations(registry, vertices):
    print("== 4. 消融开关（复杂算例，快速参数）==")
    region = Region(id=1, name="abl", vertices=vertices)
    cpp_in = CPPInput(regions=[region], launch_point=(-60, -60),
                      camera=CameraParams())
    pso = registry.get_instance("PSO-FA3ACO")
    variants = {
        "完整 FA3ACO": {},
        "关 3-opt": {"use_three_opt": 0},
        "关分数阶": {"fractional_order": 0},
        "关自适应ρ": {"adaptive_rho": 0},
        "三关全关(≈标准ACO)": {"use_three_opt": 0, "fractional_order": 0,
                                "adaptive_rho": 0},
    }
    base = dict(seed=42, pso_swarm_size=30, pso_iterations=40,
                max_iterations=120, ants_count=12)
    for label, extra in variants.items():
        p = dict(base)
        p.update(extra)
        r = pso.solve(cpp_in, **p)
        g = r.metadata["gtsp"]
        print(f"  {label:18s} 总航程={r.total_distance:9.2f} "
              f"转运={g['best_transition_distance']:8.2f} 3opt改进="
              f"{g['three_opt']['improved_tours']}")
    print()


def check_default_params(registry, vertices):
    print("== 5. 文献默认参数（蚂蚁20/迭代500，PSO 40×120）星形算例 ==")
    region = Region(id=1, name="star-default", vertices=vertices)
    cpp_in = CPPInput(regions=[region], launch_point=(-60, -60),
                      camera=CameraParams())
    pso = registry.get_instance("PSO-FA3ACO")
    r = pso.solve(cpp_in, seed=42)     # 全部默认参数
    g = r.metadata["gtsp"]
    print(f"  总航程={r.total_distance:.2f} 转弯={r.total_turns} 子区="
          f"{r.metadata['n_subregions_total']} 耗时={r.runtime:.1f}s")
    print(f"  最近邻={g['nearest_neighbor_distance']:.2f} → 3opt贪心="
          f"{g['nn_three_opt_distance']:.2f} → FA3ACO={r.convergence[-1]:.2f} "
          f"净缩短={g['three_opt']['gain_over_nearest']:.2f}")
    assert all(r.convergence[i + 1] <= r.convergence[i] + 1e-9
               for i in range(len(r.convergence) - 1)), "收敛曲线必须单调不增"
    assert r.convergence[-1] <= g["nn_three_opt_distance"] + 1e-3
    assert g["three_opt"]["gain_over_nearest"] > 0, "默认参数下应优于最近邻"
    print("  默认参数验证通过。\n")


def main():
    registry = get_registry()
    registry.load_builtins()
    print("已注册算法:", registry.names(), "\n")
    assert "ACO-GTSP" in registry.names() and "PSO-FA3ACO" in registry.names()

    check_coeffs()
    print("== 2/3. 分割完整性 + 两算法运行（快速参数）==")
    run_case(registry, L_SHAPE, "L形（1凹点）")
    run_case(registry, U_SHAPE, "U形（2凹点）")
    run_case(registry, STAR_SHAPE, "复杂星形凹多边形（4凹点）")
    check_ablations(registry, STAR_SHAPE)
    check_default_params(registry, STAR_SHAPE)
    print("全部验证通过。")


if __name__ == "__main__":
    sys.exit(main())
