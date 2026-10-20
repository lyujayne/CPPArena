"""DBO, SSA, GS-IPSO and IDGWO-VNS adapted to the platform's closed E-GTSP.

DBO/SSA retain continuous behavioral updates and use random-key permutations.
GS-IPSO and IDGWO-VNS operate on permutations directly. For every proposed
order, layered DP chooses exactly one entry/exit variant per subregion, including
launch and return distances. This shared decoder is an explicit adaptation,
not a claim to reproduce the papers' TSP/3D/multi-UAV experimental settings.
"""
import math
import numpy as np

from algorithms.aco import ACOGTSPAlgorithm
from algorithms.aco.aco_gtsp import build_cost_matrix, tour_distance, validate_visit
from core.execution_control import checkpoint


class OrderEvaluator:
    def __init__(self, nodes):
        self.nodes = nodes
        self.cost = build_cost_matrix(nodes)
        self.groups = sorted({node.subregion_id for node in nodes if node.subregion_id != 0})
        if not self.groups or nodes[0].subregion_id != 0:
            raise ValueError('群智能规划需要起降点和至少一个子区域')
        self.members = [np.array([i for i, node in enumerate(nodes) if node.subregion_id == group])
                        for group in self.groups]
        self.cache = {}
        self.evaluations = 0

    def evaluate(self, order):
        checkpoint()
        key = tuple(int(i) for i in order)
        if len(key) != len(self.groups) or set(key) != set(range(len(self.groups))):
            raise ValueError('访问顺序须为所有子区域的完整排列')
        if key in self.cache:
            return self.cache[key]
        previous = np.array([0])
        values = np.array([0.])
        parents = []
        for group in key:
            current = self.members[group]
            candidates = values[:, None] + self.cost[np.ix_(previous, current)]
            best_parent = np.argmin(candidates, axis=0)
            values = candidates[best_parent, np.arange(len(current))] + np.array(
                [self.nodes[i].internal_distance for i in current])
            parents.append(best_parent)
            previous = current
        end_values = values + self.cost[previous, 0]
        end = int(np.argmin(end_values))
        distance = float(end_values[end])
        visit = []
        for k in range(len(key)-1, -1, -1):
            visit.append(int(self.members[key[k]][end]))
            end = int(parents[k][end])
        visit.reverse()
        self.evaluations += 1
        # Cache only a bounded number of permutations in long experiments.
        if len(self.cache) >= 20000:
            self.cache.clear()
        self.cache[key] = distance, visit
        return distance, visit

    def greedy(self, first):
        remaining = set(range(len(self.groups)))
        order, previous = [], 0
        while remaining:
            checkpoint()
            group = first if not order else min(remaining, key=lambda g: min(
                self.cost[previous, i]+self.nodes[i].internal_distance for i in self.members[g]))
            node = min(self.members[group], key=lambda i: self.cost[previous, i]+self.nodes[i].internal_distance)
            order.append(group)
            remaining.remove(group)
            previous = int(node)
        return order


def _budget(params, minimum):
    population, iterations = int(params['population_size']), int(params['max_iterations'])
    if population < minimum or iterations < 1:
        raise ValueError(f'种群数量至少为{minimum}，迭代次数须为正')
    return population, iterations


def _result(evaluator, best, convergence, solver, params, assumptions, counts):
    distance, visit = evaluator.evaluate(best)
    validate_visit(evaluator.nodes, visit)
    direct = tour_distance(evaluator.nodes, evaluator.cost, visit)
    if not math.isclose(distance, direct, rel_tol=1e-10, abs_tol=1e-7):
        raise RuntimeError('搜索目标与最终航程不一致')
    internal = sum(evaluator.nodes[i].internal_distance for i in visit)
    return visit, convergence, {'solver': solver, 'objective': 'mission_total_distance',
        'objective_value': distance, 'best_transition_distance': distance-internal,
        'internal_distance_total': internal, 'n_groups': len(evaluator.groups)+1,
        'fitness_evaluations': evaluator.evaluations, 'planner_params': dict(params),
        'operator_counts': counts, 'paper_alignment': 'adapted_search_mechanisms',
        'implementation_assumptions': assumptions + [
            'Closed single-UAV planar E-GTSP; optimize total flight distance including launch and return.',
            'For each order, layered DP exactly selects among the platform scan entry/exit variants.',
            'No added 3-opt or fallback ACO solver.']}


def _dbo_step(x, previous, personal, global_best, worst, progress, rng, p, counts):
    n, dim = x.shape
    roll, breed, forage = max(1, round(.2*n)), max(2, round(.4*n)), max(3, round(23/30*n))
    local_best = personal.copy()
    shrink = 1-progress
    lower_local, upper_local = np.clip(local_best*(1-shrink), 0, 1), np.clip(local_best*(1+shrink), 0, 1)
    lower_global, upper_global = np.clip(global_best*(1-shrink), 0, 1), np.clip(global_best*(1+shrink), 0, 1)
    proposal = x.copy()
    for i in range(n):
        checkpoint('DBO 行为更新', i+1, n)
        if i < roll:
            if rng.random() < .9:
                sign = 1 if rng.random() > .1 else -1
                proposal[i] = x[i]+sign*p['dbo_k']*previous[i]+p['dbo_b']*abs(x[i]-worst)
                counts['rolling'] += 1
            else:
                angle = int(rng.integers(0, 180))
                if angle not in (0, 90):
                    proposal[i] = x[i]+math.tan(math.radians(angle))*abs(x[i]-previous[i])
                counts['dancing'] += 1
        elif i < breed:
            proposal[i] = local_best+rng.random(dim)*(x[i]-lower_local)+rng.random(dim)*(x[i]-upper_local)
            proposal[i] = np.clip(proposal[i], lower_local, upper_local)
            counts['breeding'] += 1
        elif i < forage:
            proposal[i] = personal+rng.normal()*(x[i]-lower_global)+rng.random(dim)*(x[i]-upper_global)
            counts['foraging'] += 1
        else:
            proposal[i] = global_best+p['dbo_s']*rng.normal(size=dim)*(abs(x[i]-local_best)+abs(x[i]-global_best))
            counts['stealing'] += 1
    return np.clip(proposal, 0, 1)


def solve_dbo(nodes, params, seed):
    n, iterations = _budget(params, 8)
    if not 0 < params['dbo_k'] <= .2 or not 0 < params['dbo_b'] < 1 or params['dbo_s'] <= 0:
        raise ValueError('DBO 要求0<k≤0.2、0<b<1、偷窃系数S>0')
    rng, evaluator = np.random.default_rng(seed), OrderEvaluator(nodes)
    x = rng.random((n, len(evaluator.groups)))
    previous, pbest = x.copy(), x.copy()
    fitness = np.array([evaluator.evaluate(np.argsort(v, kind='stable'))[0] for v in x])
    pfitness = fitness.copy()
    best_index = int(np.argmin(fitness))
    global_best, best_value = x[best_index].copy(), float(fitness[best_index])
    convergence, counts = [], dict.fromkeys(('rolling', 'dancing', 'breeding', 'foraging', 'stealing'), 0)
    for t in range(iterations):
        checkpoint('DBO 迭代', t+1, iterations)
        local_best = x[int(np.argmin(fitness))].copy()
        proposal = _dbo_step(x, previous, local_best, global_best, x[int(np.argmax(fitness))],
                             (t+1)/iterations, rng, params, counts)
        previous, x = x.copy(), proposal
        fitness = np.array([evaluator.evaluate(np.argsort(v, kind='stable'))[0] for v in x])
        improve = fitness < pfitness
        pbest[improve], pfitness[improve] = x[improve], fitness[improve]
        k = int(np.argmin(pfitness))
        if pfitness[k] < best_value:
            global_best, best_value = pbest[k].copy(), float(pfitness[k])
        convergence.append(best_value)
    return _result(evaluator, np.argsort(global_best, kind='stable'), convergence, 'DBO', params, [
        'Xue & Shen DBO (2023), DOI 10.1007/s11227-022-04959-6; comparison in Wu2025 Table1.',
        'Random-key order encoding is this platform adaptation; Wu2025 does not specify its DBO TSP encoding.',
        'k=.1,b=.3 from Wu2025; role fractions 6:6:7:11 and S=.5 follow original DBO convention.',
        'Population80 and iterations500 follow Wu2025 common budget on page14 (Table1 GA lists100).'], counts)


def _ssa_step(x, fitness, best, iterations, rng, p, counts, evaluator):
    n, dim = x.shape
    ranking = np.argsort(fitness, kind='stable')
    x, fitness = x[ranking].copy(), fitness[ranking].copy()
    producer_count = max(1, round(p['ssa_producer_ratio']*n))
    worst, worst_f = x[-1].copy(), float(fitness[-1])
    best_f = float(fitness[0])
    proposal = x.copy()
    alarm = rng.random()
    for i in range(producer_count):
        checkpoint('SSA 发现者更新', i+1, producer_count)
        if alarm < p['ssa_safety_threshold']:
            proposal[i] = x[i]*math.exp(-(i+1)/(max(rng.random(), 1e-12)*iterations))
        else:
            proposal[i] = x[i]+rng.normal()
        counts['producer'] += 1
    proposal[:producer_count] = np.clip(proposal[:producer_count], 0, 1)
    producer_values = [evaluator.evaluate(np.argsort(v, kind='stable'))[0]
                       for v in proposal[:producer_count]]
    producer_best = proposal[int(np.argmin(producer_values))].copy()
    for i in range(producer_count, n):
        if i >= n/2:
            proposal[i] = rng.normal()*np.exp(np.clip((worst-x[i])/(i+1)**2, -50, 50))
        else:
            signs = rng.choice([-1., 1.], size=dim)
            proposal[i] = producer_best+(abs(x[i]-producer_best) @ signs)/dim
        counts['follower'] += 1
    for i in rng.choice(n, max(1, round(p['ssa_scout_ratio']*n)), replace=False):
        if fitness[i] > best_f:
            proposal[i] = best+rng.normal()*abs(x[i]-best)
        else:
            proposal[i] = x[i]+rng.uniform(-1, 1)*abs(x[i]-worst)/(fitness[i]-worst_f+1e-12)
        counts['scout'] += 1
    return np.clip(proposal, 0, 1)


def solve_ssa(nodes, params, seed):
    n, iterations = _budget(params, 4)
    if not 0 < params['ssa_producer_ratio'] < 1 or not 0 < params['ssa_scout_ratio'] <= 1 or not 0 < params['ssa_safety_threshold'] < 1:
        raise ValueError('SSA 发现者/警戒者比例和安全阈值无效')
    rng, evaluator = np.random.default_rng(seed), OrderEvaluator(nodes)
    x = rng.random((n, len(evaluator.groups)))
    fitness = np.array([evaluator.evaluate(np.argsort(v, kind='stable'))[0] for v in x])
    index = int(np.argmin(fitness))
    best, best_value = x[index].copy(), float(fitness[index])
    convergence, counts = [], dict.fromkeys(('producer', 'follower', 'scout'), 0)
    for t in range(iterations):
        checkpoint('SSA 迭代', t+1, iterations)
        x = _ssa_step(x, fitness, best, iterations, rng, params, counts, evaluator)
        fitness = np.array([evaluator.evaluate(np.argsort(v, kind='stable'))[0] for v in x])
        index = int(np.argmin(fitness))
        if fitness[index] < best_value:
            best, best_value = x[index].copy(), float(fitness[index])
        convergence.append(best_value)
    return _result(evaluator, np.argsort(best, kind='stable'), convergence, 'SSA', params, [
        'Xue & Shen SSA (2020), DOI 10.1080/21642583.2019.1708830; comparison in Wu2025 Table1.',
        'Random-key order encoding is a platform adaptation; Wu2025 does not specify its SSA TSP encoding.',
        'Producer fraction .2 and safe update probability .5 from Wu2025; scout fraction .1 is an implementation choice.',
        'Population80 and iterations500 follow the common experimental budget on Wu2025 page14.'], counts)


def _cross(a, b, rng):
    """Order crossover: keep a segment from a, fill remaining genes from b."""
    if len(a) < 2:
        return list(a)
    left, right = sorted(rng.choice(len(a), 2, replace=False))
    child = [None]*len(a)
    child[left:right+1] = a[left:right+1]
    existing = set(a[left:right+1])
    remaining = iter(g for g in b if g not in existing)
    return [next(remaining) if g is None else g for g in child]


def _perturb(order, kind, rng):
    out = list(order)
    if len(out) < 2:
        return out
    a, b = sorted(rng.choice(len(out), 2, replace=False))
    if kind == 'swap':
        out[a], out[b] = out[b], out[a]
    elif kind == 'insert':
        out.insert(b, out.pop(a))
    elif kind == 'reverse':
        out[a:b+1] = reversed(out[a:b+1])
    elif kind == 'disorder':
        out[a:b+1] = rng.permutation(out[a:b+1]).tolist()
    else:
        raise ValueError('未知排列扰动算子')
    return out


def _swaps_towards(source, target):
    work, swaps = list(source), []
    for i, gene in enumerate(target):
        if work[i] != gene:
            j = work.index(gene)
            swaps.append((i, j))
            work[i], work[j] = work[j], work[i]
    return swaps


def _apply_velocity(order, swaps):
    out = list(order)
    for i, j in swaps:
        out[i], out[j] = out[j], out[i]
    return out


def _initial_orders(evaluator, n, rng):
    # Random starting group, then deterministic nearest feasible next group.
    # Additional particles also receive one random perturbation for diversity.
    starts = rng.permutation(len(evaluator.groups)).tolist()
    orders = []
    for i in range(n):
        order = evaluator.greedy(starts[i % len(starts)])
        if i >= len(starts):
            order = _perturb(order, 'reverse', rng)
        orders.append(order)
    return orders


def solve_gs_ipso(nodes, params, seed):
    n, iterations = _budget(params, 4)
    for k in ('gs_inertia', 'gs_mutation_prob', 'gs_replacement_ratio', 'gs_elite_ratio', 'gs_early_fraction'):
        if not 0 <= params[k] <= 1:
            raise ValueError('GS-IPSO 的概率、比例和交换惯性须在0～1之间')
    if not 0 < params['gs_elite_ratio'] < 1 or not 0 < params['gs_early_fraction'] < 1 or params['gs_temperature_ratio'] <= 0:
        raise ValueError('GS-IPSO 精英比例/阶段阈值须在(0,1)，温度系数须为正')
    rng, evaluator = np.random.default_rng(seed), OrderEvaluator(nodes)
    population = _initial_orders(evaluator, n, rng)
    fitness = np.array([evaluator.evaluate(o)[0] for o in population])
    pbest, pfitness = [o[:] for o in population], fitness.copy()
    velocities = [[] for _ in population]
    index = int(np.argmin(fitness))
    best, best_value = population[index][:], float(fitness[index])
    temperature = max(best_value*params['gs_temperature_ratio'], 1e-9)
    convergence, counts = [], dict.fromkeys(('velocity', 'personal_cross', 'peer_cross', 'global_cross',
        'metropolis_worse_accepted', 'mutation', 'elite_replacement'), 0)
    for t in range(iterations):
        checkpoint('GS-IPSO 迭代', t+1, iterations)
        fraction = t/iterations
        early = params['gs_early_fraction']
        # Eq17 specifies separate stages. Inactive factor is explicitly zero.
        peer_factor = 1-fraction/early if fraction <= early else 0.
        global_factor = 0. if fraction <= early else 1-(fraction-early)/(1-early)
        old_population = [o[:] for o in population]
        for i, order in enumerate(old_population):
            checkpoint('GS-IPSO 离散交换与Metropolis', i+1, n)
            velocity = [s for s in velocities[i] if rng.random() < params['gs_inertia']]
            for target, factor, counter in ((pbest[i], rng.random(), 'personal_cross'),
                    (old_population[int(rng.integers(n))], rng.random()*peer_factor, 'peer_cross'),
                    (best, rng.random()*global_factor, 'global_cross')):
                swaps = [s for s in _swaps_towards(order, target) if rng.random() < factor]
                velocity.extend(swaps)
                counts[counter] += len(swaps)
            # Two passes suffice to express a full permutation change; bounding
            # velocity prevents unbounded growth of old swap histories.
            velocity = velocity[-2*len(order):]
            candidate = _apply_velocity(order, velocity)
            counts['velocity'] += 1
            if rng.random() < params['gs_mutation_prob']:
                mutation = _perturb(candidate, 'reverse', rng)
                if evaluator.evaluate(mutation)[0] < evaluator.evaluate(candidate)[0]:
                    candidate = mutation
                counts['mutation'] += 1
            value = evaluator.evaluate(candidate)[0]
            delta = value-fitness[i]
            if delta <= 0 or rng.random() < math.exp(-delta/temperature):
                population[i], fitness[i], velocities[i] = candidate, value, velocity
                if delta > 0:
                    counts['metropolis_worse_accepted'] += 1
            if fitness[i] < pfitness[i]:
                pbest[i], pfitness[i] = population[i][:], fitness[i]
        ranking = np.argsort(fitness)
        elite_count = max(2, round(n*params['gs_elite_ratio']))
        elites = ranking[:elite_count]
        weights = 1/np.maximum(fitness[elites], 1e-12)
        weights /= weights.sum()
        replace_count = round(n*params['gs_replacement_ratio'])
        for _ in range(replace_count):
            ia, ib = rng.choice(elites, 2, replace=False, p=weights)
            child = _cross(population[int(ia)], population[int(ib)], rng)
            mutation = _perturb(child, 'reverse', rng)
            if evaluator.evaluate(mutation)[0] < evaluator.evaluate(child)[0]:
                child = mutation
            value = evaluator.evaluate(child)[0]
            # Eq19 selects high-cost particles for replacement, not as parents.
            victim = int(rng.choice(n, p=fitness/fitness.sum())) if fitness.sum() > 0 else int(rng.integers(n))
            if value < fitness[victim]:
                population[victim], fitness[victim], velocities[victim] = child, value, []
                if value < pfitness[victim]:
                    pbest[victim], pfitness[victim] = child[:], value
            counts['elite_replacement'] += 1
        index = int(np.argmin(pfitness))
        if pfitness[index] < best_value:
            best, best_value = pbest[index][:], float(pfitness[index])
        convergence.append(best_value)
    return _result(evaluator, best, convergence, 'GS-IPSO', params, [
        'Li et al.2025, DOI 10.1016/j.engappai.2025.111253, Sections3.1-3.3.',
        'Retains greedy initialization, discrete swap velocity, adaptive peer/global stages, Metropolis, elite crossover and reverse mutation.',
        'Eq16 operators are instantiated as swap sequences and order crossover; this operator detail is an adaptation.',
        'Distance-only 2D objective; no bridge mesh, CGN, climb penalties, or 3D collision constraints.',
        'Paper budget is 800 particles/300 iterations; interactive defaults80/300 are explicitly reduced.',
        'Temperature is initial best distance times exposed coefficient; no unspecified annealing schedule is invented.'], counts)


def solve_idgwo_vns(nodes, params, seed):
    n, iterations = _budget(params, 4)
    if not 0 < params['gwo_elimination_ratio'] < 1 or not 0 < params['gwo_control_u'] <= 1 or int(params['vns_iterations']) < 1:
        raise ValueError('IDGWO-VNS 要求淘汰比例在(0,1)、u在(0,1]、VNS次数为正')
    rng, evaluator = np.random.default_rng(seed), OrderEvaluator(nodes)
    population = _initial_orders(evaluator, n, rng)
    fitness = np.array([evaluator.evaluate(o)[0] for o in population])
    index = int(np.argmin(fitness))
    best, best_value = population[index][:], float(fitness[index])
    convergence, counts = [], dict.fromkeys(('leader_cross', 'elimination', 'swap', 'insert', 'reverse', 'disorder'), 0)
    for t in range(iterations):
        checkpoint('IDGWO-VNS 迭代', t+1, iterations)
        ranking = np.argsort(fitness)
        leaders = [population[int(k)][:] for k in ranking[:3]]
        proposed = [_cross(o, leaders[int(rng.integers(3))], rng) for o in population]
        counts['leader_cross'] += n
        proposed_values = np.array([evaluator.evaluate(o)[0] for o in proposed])
        for i in range(n):
            if proposed_values[i] < fitness[i]:
                population[i], fitness[i] = proposed[i], proposed_values[i]
        # Replace the poorest fraction with new feasible heuristic individuals.
        # The retained best archive also survives when all current values tie.
        poor_count = max(1, round(n*params['gwo_elimination_ratio']))
        poor = np.argsort(fitness)[-poor_count:]
        for i in poor:
            population[int(i)] = _perturb(leaders[int(rng.integers(3))], 'disorder', rng)
            fitness[int(i)] = evaluator.evaluate(population[int(i)])[0]
            counts['elimination'] += 1
        s = 1-math.sin(math.pi*(t+1)/(2*iterations))**params['gwo_control_u']
        candidate = best[:]
        for k in range(int(params['vns_iterations'])):
            checkpoint('IDGWO-VNS 变邻域搜索', k+1, int(params['vns_iterations']))
            modes = ('disorder',) if rng.random() <= s else ('swap', 'insert', 'reverse')
            for mode in modes:
                neighbor = _perturb(candidate, mode, rng)
                counts[mode] += 1
                if evaluator.evaluate(neighbor)[0] < evaluator.evaluate(candidate)[0]:
                    candidate = neighbor
        population.append(candidate)
        fitness = np.append(fitness, evaluator.evaluate(candidate)[0])
        ranking = np.argsort(fitness)[:n]
        population, fitness = [population[int(i)] for i in ranking], fitness[ranking]
        if fitness[0] < best_value:
            best, best_value = population[0][:], float(fitness[0])
        convergence.append(best_value)
    return _result(evaluator, best, convergence, 'IDGWO-VNS', params, [
        'Li et al.2024, DOI 10.3390/drones8120764, Section3.2.',
        'Retains heuristic initialization, equal-choice alpha/beta/delta crossover, poor-individual replacement, VNS swap/insert/reverse/disorder.',
        'Eq18 s=1-sin(pi*t/(2*T))**u with u=.4; follows r2<=s disorder rule. The following prose reverses early/late trends.',
        'Single UAV adaptation; no fleet allocation chromosome, minimax balancing, endurance model, Voronoi obstacle avoidance or original coverage DP.',
        'Order crossover and replaced-individual construction are explicit engineering choices.'], counts)


class SwarmPlanner(ACOGTSPAlgorithm):
    independent_component_params = True
    parameter_labels = {'population_size': '种群数量', 'max_iterations': '最大迭代次数'}

    def solve_region_order(self, nodes, params, seed):
        return self.solver(nodes, dict(self.default_params, **params), seed)

    def get_param_spec(self):
        return [(k, self.parameter_labels[k], 'int' if isinstance(v, int) else 'float', v)
                for k, v in self.default_params.items()]


class DBOPlanner(SwarmPlanner):
    name = 'DBO'
    label = 'DBO 蜣螂优化（适配）'
    description = '滚动/跳舞/繁殖/觅食/偷窃五种行为，随机键搜索访问顺序；适配单机二维闭环E-GTSP，非Wu论文未公开离散实现的逐式复现。'
    solver = staticmethod(solve_dbo)
    default_params = {'population_size': 80, 'max_iterations': 500, 'dbo_b': .3, 'dbo_k': .1, 'dbo_s': .5}
    parameter_labels = dict(SwarmPlanner.parameter_labels, dbo_b='滚动系数 b', dbo_k='偏转系数 k', dbo_s='偷窃系数 S')


class SSAPlanner(SwarmPlanner):
    name = 'SSA'
    label = 'SSA 麻雀搜索（适配）'
    description = '发现者/加入者/警戒者更新，随机键搜索访问顺序；发现者20%、安全更新概率0.5按Wu对比参数，警戒者比例为实现设置。'
    solver = staticmethod(solve_ssa)
    default_params = {'population_size': 80, 'max_iterations': 500, 'ssa_producer_ratio': .2,
                      'ssa_safety_threshold': .5, 'ssa_scout_ratio': .1}
    parameter_labels = dict(SwarmPlanner.parameter_labels, ssa_producer_ratio='发现者比例',
        ssa_safety_threshold='安全阈值/安全更新概率', ssa_scout_ratio='警戒者比例（实现取值）')


class GSIPSOPlanner(SwarmPlanner):
    name = 'GS-IPSO'
    label = 'GS-IPSO 贪心改进粒子群（二维适配）'
    description = 'Li等2025：贪心初始化、离散交换、阶段自适应、Metropolis、精英交叉和逆序变异。仅优化二维任务总距离，无三维桥梁网格/爬升惩罚；默认种群80（原文800）。'
    solver = staticmethod(solve_gs_ipso)
    default_params = {'population_size': 80, 'max_iterations': 300, 'gs_inertia': 1.,
        'gs_mutation_prob': .05, 'gs_replacement_ratio': .03, 'gs_elite_ratio': .2,
        'gs_early_fraction': .6, 'gs_temperature_ratio': 1.}
    parameter_labels = dict(SwarmPlanner.parameter_labels, gs_inertia='交换惯性 w', gs_mutation_prob='粒子变异概率',
        gs_replacement_ratio='每代精英替换比例（适配）', gs_elite_ratio='精英比例 GP/N',
        gs_early_fraction='早期阶段比例', gs_temperature_ratio='温度/初始最优航程系数')


class IDGWOVNSPlanner(SwarmPlanner):
    name = 'IDGWO-VNS'
    label = 'IDGWO-VNS 离散灰狼+变邻域（单机适配）'
    description = 'Li等2024：启发式初始化、三头狼交叉、淘汰替换及四种变邻域算子，s按式18。适配单机访问顺序，不包含多机分配、续航与Voronoi避障。'
    solver = staticmethod(solve_idgwo_vns)
    default_params = {'population_size': 100, 'max_iterations': 200, 'gwo_elimination_ratio': .4,
                      'gwo_control_u': .4, 'vns_iterations': 30}
    parameter_labels = dict(SwarmPlanner.parameter_labels, gwo_elimination_ratio='种群淘汰比例 κ',
        gwo_control_u='式18控制因子 u', vns_iterations='每代变邻域搜索次数')
