"""The allocation problem, solved by simulated annealing and checked by an exact solver.

Each agent is a variable and its domain is the candidate segments, as in a constraint satisfaction
problem. The constraints in `Problem` are hard. The objective is the total of a value table.
"""
from dataclasses import dataclass
import math

import numpy as np
from scipy import optimize, sparse


@dataclass
class Problem:
    values: np.ndarray          # value of 0..max_area agents, one row per segment
    area: np.ndarray            # area index of each segment
    offplan: np.ndarray         # True for Off-Plan segments
    agents: int
    min_team: int
    max_area: int
    max_areas: int
    offplan_low: int
    offplan_high: int
    current: np.ndarray | None = None
    max_moves: int | None = None


def limits(agents, cfg):
    """Area size limit. A cap of min_team + 1 always leaves a way to split any team size."""
    if agents < cfg['min_team_per_area']:
        raise ValueError(f'{agents} agents cannot form a team of {cfg["min_team_per_area"]}')
    return max(math.ceil(cfg['max_area_share'] * agents), cfg['min_team_per_area'] + 1)


def make_problem(candidates, values, agents, cfg, current=None):
    area = candidates.area.astype('category').cat.codes.to_numpy(dtype=np.int64)
    offplan = candidates.registration_type.eq('Off-Plan').to_numpy()
    max_area = limits(agents, cfg)
    if values.shape[1] != max_area + 1:
        raise ValueError('Value table does not match the area limit')
    low, high = cfg['offplan_share']
    problem = Problem(values, area, offplan, agents, cfg['min_team_per_area'], max_area,
                      cfg['max_areas'], math.floor(low * agents), math.ceil(high * agents),
                      current, cfg['max_moves'] if current is not None else None)
    if min(problem.max_areas, area.max() + 1) * max_area < agents:
        raise ValueError('Constraints cannot hold this many agents; raise max_areas or max_area_share')
    return problem


def total_value(problem, x):
    return float(problem.values[np.arange(len(x)), x].sum())


def violations(p, x):
    """Number of constraint units broken; 0 means feasible."""
    x = np.asarray(x)
    teams = np.bincount(p.area, x, minlength=p.area.max() + 1)
    active = teams[teams > 0]
    count = abs(int(x.sum()) - p.agents)
    count += int(np.maximum(p.min_team - active, 0).sum() + np.maximum(active - p.max_area, 0).sum())
    count += max(0, len(active) - p.max_areas)
    offplan = int(x[p.offplan].sum())
    count += max(0, p.offplan_low - offplan) + max(0, offplan - p.offplan_high)
    if p.max_moves is not None:
        count += max(0, int(np.maximum(x - p.current, 0).sum()) - p.max_moves)
    return count


def greedy(p):
    """Add one agent at a time where it gains most, respecting the limits it can see."""
    x = np.zeros(len(p.area), dtype=int)
    for _ in range(p.agents):
        teams = np.bincount(p.area, x, minlength=p.area.max() + 1)
        gains = p.values[np.arange(len(x)), np.minimum(x + 1, p.max_area)] - p.values[np.arange(len(x)), x]
        allowed = teams[p.area] < p.max_area
        if np.count_nonzero(teams) >= p.max_areas:
            allowed &= teams[p.area] > 0
        if x[p.offplan].sum() >= p.offplan_high:
            allowed &= ~p.offplan
        x[int(np.argmax(np.where(allowed, gains, -np.inf)))] += 1
    return x


class State:
    """An allocation with its value and violations kept up to date as agents move."""

    def __init__(self, p, x, values):
        self.p, self.values = p, values
        self.area, self.offplan = p.area.tolist(), p.offplan.tolist()
        self.current = None if p.current is None else p.current.tolist()
        self.x = [int(v) for v in x]
        self.teams = np.bincount(p.area, x, minlength=p.area.max() + 1).tolist()
        self.value = sum(values[i][v] for i, v in enumerate(self.x))
        self.active = sum(t > 0 for t in self.teams)
        self.off = sum(v for v, flag in zip(self.x, self.offplan) if flag)
        self.moved = 0 if p.current is None else sum(max(0, v - c) for v, c in zip(self.x, self.current))
        self.team_broken = sum(self.team_penalty(t) for t in self.teams)

    def team_penalty(self, team):
        p = self.p
        return 0 if team == 0 else max(0, p.min_team - team) + max(0, team - p.max_area)

    def broken(self):
        p = self.p
        count = self.team_broken + max(0, self.active - p.max_areas)
        count += max(0, p.offplan_low - self.off) + max(0, self.off - p.offplan_high)
        return count + (0 if p.max_moves is None else max(0, self.moved - p.max_moves))

    def change_team(self, area, step):
        old = self.teams[area]
        self.team_broken += self.team_penalty(old + step) - self.team_penalty(old)
        self.active += (old + step > 0) - (old > 0)
        self.teams[area] = old + step

    def change(self, cell, step):
        old = self.x[cell]
        new = old + step
        row = self.values[cell]
        self.value += row[min(new, self.p.max_area)] - row[min(old, self.p.max_area)]
        self.x[cell] = new
        self.change_team(self.area[cell], step)
        if self.offplan[cell]:
            self.off += step
        if self.current is not None:
            self.moved += max(0, new - self.current[cell]) - max(0, old - self.current[cell])

    def shift(self, source, target):
        self.change(source, -1)
        self.change(target, 1)


def anneal(p, settings, rng, start=None, trace=None):
    """Simulated annealing over one-agent moves and whole-team moves. Returns the best feasible x.

    Pass a list as `trace` to collect the best value every 500 iterations (nan until feasible).
    """
    top = float(np.max(p.values[:, 1:] - p.values[:, :-1])) or 1.0
    table = (p.values / top).tolist()
    cells = len(p.area)
    start = greedy(p) if start is None else start
    best_x, best_value = None, -math.inf
    if violations(p, start) == 0:
        best_x, best_value = np.array(start), total_value(p, start) / top
    steps, penalty = settings['iterations'], settings['penalty']
    cooling = (settings['end_temperature'] / settings['start_temperature']) ** (1 / max(steps - 1, 1))
    members = [np.flatnonzero(p.area == a).tolist() for a in range(p.area.max() + 1)]
    for _ in range(settings['restarts']):   # each restart reheats from the best plan so far
        state = State(p, start if best_x is None else best_x, table)
        placed = [i for i, v in enumerate(state.x) for _ in range(v)]
        temperature = settings['start_temperature']
        draws, cells_drawn = rng.random(steps * 2).tolist(), rng.integers(cells, size=steps).tolist()
        picks = rng.integers(len(placed), size=steps).tolist()
        for step in range(steps):
            energy = state.value - penalty * state.broken()
            agent, target = picks[step], cells_drawn[step]
            source = placed[agent]
            if draws[2 * step] < 0.15:      # move every agent of this area to one other segment
                moves = [(i, a) for a, i in enumerate(placed) if state.area[i] == state.area[source]]
            else:
                if draws[2 * step] < 0.5:   # stay inside the areas already in use
                    target = placed[(agent + 1 + cells_drawn[step]) % len(placed)]
                    pool = members[state.area[target]]
                    target = pool[cells_drawn[step] % len(pool)]
                moves = [(source, agent)]
            for i, _a in moves:
                state.shift(i, target)
            gain = state.value - penalty * state.broken() - energy
            if gain >= 0 or draws[2 * step + 1] < math.exp(gain / temperature):
                for _i, a in moves:
                    placed[a] = target
                if state.value > best_value + 1e-9 and state.broken() == 0:
                    best_value, best_x = state.value, np.array(state.x)
            else:
                for i, _a in moves:
                    state.shift(target, i)
            temperature *= cooling
            if trace is not None and step % 500 == 0:
                trace.append(best_value * top if best_x is not None else math.nan)
    if best_x is None:
        raise ValueError('No feasible allocation found')
    return hill_climb(p, best_x) if settings.get('polish', True) else best_x


def rebuild(p, x, closing, opening):
    """Close one area and hand its agents out again, one at a time, to `opening` or areas in use."""
    y = x.copy()
    y[p.area == closing] = 0
    rows = np.arange(len(y))
    for _ in range(int(x[p.area == closing].sum())):
        gains = p.values[rows, np.minimum(y + 1, p.max_area)] - p.values[rows, y]
        teams = np.bincount(p.area, y, minlength=p.area.max() + 1)
        allowed = ((p.area == opening) | (teams[p.area] > 0)) & (teams[p.area] < p.max_area)
        if not allowed.any():
            return None
        y[int(np.argmax(np.where(allowed, gains, -np.inf)))] += 1
    return y


def hill_climb(p, x):
    """Take the best feasible single move or area swap until none improves the plan."""
    x, value = x.copy(), total_value(p, x)
    while True:
        best, best_value = None, value + 1e-9
        for source in np.flatnonzero(x):
            for target in np.flatnonzero(x < p.max_area):
                y = x.copy()
                y[source] -= 1
                y[target] += 1
                if total_value(p, y) > best_value and violations(p, y) == 0:
                    best, best_value = y, total_value(p, y)
        for closing in np.unique(p.area[x > 0]):
            for opening in range(p.area.max() + 1):
                y = None if opening == closing else rebuild(p, x, closing, opening)
                if y is not None and total_value(p, y) > best_value and violations(p, y) == 0:
                    best, best_value = y, total_value(p, y)
        if best is None:
            return x
        x, value = best, best_value


def exact(p, time_limit=60):
    """Exact optimum as a mixed-integer program. One binary per segment and agent, so concave
    values fill in order. Used only to check the annealer; it knows nothing about the search."""
    cells, depth = len(p.area), p.max_area
    areas = p.area.max() + 1
    moves = 0 if p.max_moves is None else cells
    size = cells * depth + areas + moves
    gains = (p.values[:, 1:] - p.values[:, :-1]).ravel()
    scale = float(np.abs(gains).max()) or 1.0
    cost = np.concatenate([-gains / scale, np.zeros(areas + moves)])
    agent_vars = lambda i: range(i * depth, (i + 1) * depth)
    rows, low, high = [], [], []

    def add(coefficients, lower, upper):
        rows.append(coefficients)
        low.append(lower)
        high.append(upper)

    add({v: 1 for i in range(cells) for v in agent_vars(i)}, p.agents, p.agents)
    for a in range(areas):
        used = cells * depth + a
        team = {v: 1 for i in np.flatnonzero(p.area == a) for v in agent_vars(i)}
        add({**team, used: -p.min_team}, 0, np.inf)
        add({**team, used: -p.max_area}, -np.inf, 0)
    add({cells * depth + a: 1 for a in range(areas)}, 0, p.max_areas)
    add({v: 1 for i in np.flatnonzero(p.offplan) for v in agent_vars(i)}, p.offplan_low, p.offplan_high)
    if moves:
        first = cells * depth + areas
        for i in range(cells):
            add({**{v: 1 for v in agent_vars(i)}, first + i: -1}, -np.inf, int(p.current[i]))
        add({first + i: 1 for i in range(cells)}, 0, p.max_moves)
    matrix = sparse.lil_matrix((len(rows), size))
    for r, coefficients in enumerate(rows):
        for column, value in coefficients.items():
            matrix[r, column] = value
    integrality = np.concatenate([np.ones(size - moves), np.zeros(moves)])
    upper = np.concatenate([np.ones(size - moves), np.full(moves, depth)])
    result = optimize.milp(cost, constraints=optimize.LinearConstraint(matrix.tocsr(), low, high),
                           integrality=integrality, bounds=optimize.Bounds(0, upper),
                           options={'time_limit': time_limit, 'mip_rel_gap': 0})
    if result.x is None:
        raise ValueError(f'No exact solution: {result.message}')
    return np.rint(result.x[:cells * depth]).reshape(cells, depth).sum(axis=1).astype(int)
