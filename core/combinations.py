"""Independent decomposition/planning components and serializable experiment tasks."""
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from itertools import product
from uuid import uuid4

from algorithms.aco import ACOGTSPAlgorithm
from algorithms.aco.pso_fa3aco import PSOFA3ACOAlgorithm
from algorithms.aco.enhanced_aco import EnhancedECDACOAlgorithm
from algorithms.aco.enhanced_ecd_dp import EnhancedECDDPAlgorithm

DECOMPOSITIONS = {
    "Bayazit": ("Bayazit 凸分解", ACOGTSPAlgorithm),
    "PSO-DCAS": ("PSO-DCAS 粒子群分割", PSOFA3ACOAlgorithm),
    "Enhanced-ECD": ("增强精确单元分解", EnhancedECDACOAlgorithm),
}
PLANNERS = {
    "ACO": ("ACO 闭环规划", ACOGTSPAlgorithm),
    "FA3ACO": ("FA3ACO 闭环规划", PSOFA3ACOAlgorithm),
    "Li-DP": ("DP 开放规划（可选严格邻接）", EnhancedECDDPAlgorithm),
}


def component_defaults(kind, key):
    catalog = DECOMPOSITIONS if kind == "decomposition" else PLANNERS
    defaults = catalog[key][1].default_params
    if getattr(catalog[key][1], 'component_plugin', False):
        return {k: deepcopy(v) for k, v in defaults.items() if k != 'seed'}
    return {k: deepcopy(v) for k, v in defaults.items() if k != "seed"
            and (k.startswith("pso_") == (kind == "decomposition"))}


def component_spec(kind, key):
    catalog = DECOMPOSITIONS if kind == "decomposition" else PLANNERS
    defaults = component_defaults(kind, key)
    specs = {s[0]: s for s in catalog[key][1]().get_param_spec()}
    return [specs.get(k, (k, k, "int" if isinstance(v, int) else "float", v))
            for k, v in defaults.items()]


@dataclass
class Combination:
    decomposition: str
    planning: str
    decomposition_params: dict = field(default_factory=dict)
    planning_params: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex[:8])
    dataset_ids: list = None  # None inherits experiment scope; explicit IDs bind this row.

    def __post_init__(self):
        if self.decomposition not in DECOMPOSITIONS or self.planning not in PLANNERS:
            raise ValueError("未知分割或规划模块")
        self.decomposition_params = deepcopy(self.decomposition_params)
        self.planning_params = deepcopy(self.planning_params)
        self.dataset_ids = list(dict.fromkeys(self.dataset_ids)) if self.dataset_ids is not None else None
        for kind, key, params in (("decomposition", self.decomposition, self.decomposition_params),
                                  ("planning", self.planning, self.planning_params)):
            if set(params) - set(component_defaults(kind, key)):
                raise ValueError("参数不属于所选模块")

    @property
    def label(self):
        return f"{self.decomposition} × {self.planning} [{self.id}]"

    def to_dict(self):
        return asdict(self)

    def effective_params(self):
        return {
            "decomposition": dict(component_defaults("decomposition", self.decomposition),
                                  **self.decomposition_params),
            "planning": dict(component_defaults("planning", self.planning), **self.planning_params),
        }


def enumerate_combinations(decompositions, planners):
    return [Combination(d, p) for d, p in product(dict.fromkeys(decompositions), dict.fromkeys(planners))]


class ComposedAlgorithm(ACOGTSPAlgorithm):
    """Reuse geometry/coverage validation and assembly with independent hooks."""
    default_params = {}

    def __init__(self, combination):
        self.combination = Combination(**combination) if isinstance(combination, dict) else combination
        self.name = self.combination.label
        self._effective = self.combination.effective_params()
        self._decomp = DECOMPOSITIONS[self.combination.decomposition][1]()
        self._planner = PLANNERS[self.combination.planning][1]()

    def decompose_region(self, vertices, params):
        return self._decomp.decompose_region(vertices, dict(self._effective["decomposition"],
                                                           seed=params.get("seed", 42)))

    def solve_region_order(self, nodes, params, seed):
        return self._planner.solve_region_order(nodes, dict(self._effective["planning"], seed=seed), seed)

    def plan_subregion(self, vertices, line_spacing):
        self._planner._scan_boundary_mode = self._scan_boundary_mode
        return self._planner.plan_subregion(vertices, line_spacing)

    def solve(self, cpp_input, **params):
        result = super().solve(cpp_input, **params)
        result.metadata["combination"] = self.combination.to_dict()
        result.metadata["effective_component_params"] = self._effective
        result.metadata['component_sources'] = {
            kind: {'path': getattr(component, 'source_path', ''), 'sha256': getattr(component, 'source_hash', '')}
            for kind, component in (('decomposition', self._decomp), ('planning', self._planner))}
        return result


def build_combination_jobs(combinations, datasets, seeds, camera, default_dataset_ids=None):
    from core.experiment_runner import ExperimentJob
    if len({ds.name for ds in datasets}) != len(datasets):
        raise ValueError('数据集名称重复，请重命名后再运行，避免结果混合。')
    if len({c.id for c in combinations}) != len(combinations):
        raise ValueError('组合编号重复，请重新添加重复编号的组合。')
    jobs = []
    available = {ds.id for ds in datasets}
    assignments = {}
    for combination in combinations:
        selected = combination.dataset_ids if combination.dataset_ids is not None else default_dataset_ids
        if selected is None:
            selected = list(available)
        if not selected:
            raise ValueError(f'{combination.label} 没有选择数据集')
        missing = set(selected) - available
        if missing:
            raise ValueError(f'{combination.label} 绑定的数据集已不存在，请重新选择数据集')
        assignments[combination.id] = set(selected)
    for ds in datasets:
        for combination in combinations:
            if ds.id not in assignments[combination.id]:
                continue
            for seed in seeds:
                jobs.append(ExperimentJob(combination.label, ds, seed, camera=deepcopy(camera),
                                          combination=combination.to_dict()))
    return jobs


# Spawn workers import this module as well, so installed components are available
# without trying to pickle dynamically loaded Python classes.
from core.component_plugins import load_component_plugins
COMPONENT_LOAD_ERRORS = load_component_plugins()
