"""Walk-forward backtest: plan each past quarter with what was known, score it on what happened."""
from time import perf_counter

import numpy as np
import pandas as pd
from scipy import stats

from .data import KEYS, backtest_candidates, known_errors
from .model import deal_value, scenarios, value_table
from .search import anneal, exact, greedy, hill_climb, limits, make_problem, total_value, violations

# Simplest first, so that a tie on validation goes to the simpler policy.
VARIANTS = {
    'point': dict(use_scenarios=False, trend_weight=0.0),
    'point_trend_025': dict(use_scenarios=False, trend_weight=0.25),
    'point_trend_050': dict(use_scenarios=False, trend_weight=0.5),
    'scenarios': dict(use_scenarios=True, trend_weight=0.0),
    'scenarios_trend_025': dict(use_scenarios=True, trend_weight=0.25),
    'scenarios_trend_050': dict(use_scenarios=True, trend_weight=0.5),
}
FAST = {'iterations': 12000, 'restarts': 1, 'start_temperature': 0.25, 'end_temperature': 0.02, 'penalty': 0.2}


def planned_values(candidates, errors, agents, cfg, rng, use_scenarios, trend_weight, demand='demand'):
    frame = candidates.assign(demand=candidates[demand])
    table = scenarios(frame, errors, cfg, rng) if use_scenarios else frame.demand.to_numpy()
    trend = 1 + trend_weight * frame.trend_score.fillna(0).to_numpy()
    return value_table(table, deal_value(frame.ticket.to_numpy(), frame.rate.to_numpy(), cfg) * trend,
                       limits(agents, cfg), cfg)


def plan(candidates, errors, agents, cfg, rng, settings=None, current=None, **options):
    values = planned_values(candidates, errors, agents, cfg, rng, **options)
    problem = make_problem(candidates, values, agents, cfg, current)
    return anneal(problem, settings or cfg['anneal'], rng)


def proportional(weights, agents, segments, cap):
    """Plain rule of thumb: agents in proportion to weights over the largest segments."""
    weights = np.asarray(weights, dtype=float)
    top = np.argsort(-weights, kind='stable')[:segments]
    x = np.zeros(len(weights), dtype=int)
    for _ in range(agents):     # highest-averages rounding, one agent at a time
        room = top[x[top] < cap]
        x[room[np.argmax(weights[room] / (x[room] + 1))]] += 1
    return x


def even(weights, agents, segments, cap):
    return proportional(np.where(np.argsort(np.argsort(-np.asarray(weights))) < segments, 1.0, 0.0),
                        agents, segments, cap)


def truth_problem(candidates, agents, cfg, current=None):
    """The same model and constraints, but with the sales and prices that really happened."""
    values = value_table(candidates.actual_sales.to_numpy(),
                         deal_value(candidates.actual_ticket.to_numpy(), candidates.rate.to_numpy(), cfg),
                         limits(agents, cfg), cfg)
    return make_problem(candidates, values, agents, cfg, current)


def score(rows, candidates, x, truth, oracle, method, split, quarter, previous):
    moved = None
    held = dict(zip(zip(candidates.area, candidates.registration_type), x))
    if method in previous:
        moved = sum(max(0, v - previous[method].get(k, 0)) for k, v in held.items())
    previous[method] = held
    rows.append({'split': split, 'forecast_quarter': quarter, 'method': method,
                 'realised_value': total_value(truth, x), 'oracle_value': oracle,
                 'share_of_oracle': total_value(truth, x) / oracle, 'moves': moved,
                 'segments': int(np.count_nonzero(x)), 'feasible': violations(truth, x) == 0})


def origins(inputs):
    pred = inputs['predictions']
    table = pred[['split', 'origin_quarter', 'forecast_quarter']].drop_duplicates()
    return table.sort_values('origin_quarter').itertuples(index=False)


def backtest(inputs, cfg, agents=None, variants=None, settings=None, rules=True):
    """Score every policy for every past quarter. One seeded generator per policy and quarter."""
    agents = agents or cfg['agents']
    variants = VARIANTS if variants is None else variants
    rows, previous, cap = [], {}, limits(agents, cfg)
    for index, (split, origin, quarter) in enumerate(origins(inputs)):
        candidates = backtest_candidates(inputs, origin, cfg)
        errors = known_errors(inputs['errors'], quarter)
        truth = truth_problem(candidates, agents, cfg)
        oracle = total_value(truth, exact(truth))
        plans = {}
        if rules:
            plans['even_split'] = even(candidates.last_sales, agents, cfg['max_areas'], cap)
            plans['share_of_last_sales'] = proportional(candidates.last_sales, agents, cfg['max_areas'], cap)
            plans['share_of_forecast'] = proportional(candidates.demand, agents, cfg['max_areas'], cap)
            worth = candidates.demand * deal_value(candidates.ticket.to_numpy(), candidates.rate.to_numpy(), cfg)
            plans['share_of_forecast_value'] = proportional(worth, agents, cfg['max_areas'], cap)
        for number, (name, options) in enumerate(variants.items()):
            rng = np.random.default_rng([cfg['seed'], index, number])
            plans[name] = plan(candidates, errors, agents, cfg, rng, settings, **options)
        if rules:
            rng = np.random.default_rng([cfg['seed'], index, 99])
            plans['optimiser_naive_input'] = plan(candidates, errors, agents, cfg, rng, settings,
                                                  use_scenarios=False, trend_weight=0.0, demand='last_sales')
        for method, x in plans.items():
            score(rows, candidates, x, truth, oracle, method, split, quarter, previous)
    return pd.DataFrame(rows)


def select_variant(results, cfg):
    """Pick on 2024 only. A later variant must beat earlier ones by tie_margin to be chosen."""
    means = results[results.split.eq('validation')].groupby('method').share_of_oracle.mean()
    best = max(VARIANTS, key=lambda name: means[name])
    for name in VARIANTS:
        if means[name] >= means[best] - cfg['tie_margin']:
            return name, {k: float(means[k]) for k in VARIANTS}


def limited_moves(inputs, cfg, options, limit):
    """Replay the test with a limit on how many agents may change segment each quarter."""
    agents, rows, held, previous = cfg['agents'], [], None, {}
    test = [o for o in origins(inputs) if o[0] == 'test']
    for index, (split, origin, quarter) in enumerate(test):
        candidates = backtest_candidates(inputs, origin, cfg)
        errors = known_errors(inputs['errors'], quarter)
        truth = truth_problem(candidates, agents, cfg)
        rng = np.random.default_rng([cfg['seed'], index, 77])
        if held is None:
            x = plan(candidates, errors, agents, cfg, rng, **options)
        else:
            current = np.array([held.get(k, 0) for k in zip(candidates.area, candidates.registration_type)])
            lost = agents - int(current.sum())   # a segment left the candidate list; they must move
            limited = {**cfg, 'max_moves': max(limit, lost)}
            x = plan(candidates, errors, agents, limited, rng, current=current, **options)
        held = dict(zip(zip(candidates.area, candidates.registration_type), x))
        score(rows, candidates, x, truth, total_value(truth, exact(truth)), 'selected_move_limit',
              split, quarter, previous)
    return pd.DataFrame(rows)


def solver_gap(inputs, cfg, options):
    """How close the annealer gets to the exact optimum on each real planning problem."""
    gaps = []
    for index, (split, origin, quarter) in enumerate(origins(inputs)):
        candidates = backtest_candidates(inputs, origin, cfg)
        rng = np.random.default_rng([cfg['seed'], index, 55])
        values = planned_values(candidates, known_errors(inputs['errors'], quarter), cfg['agents'],
                                cfg, rng, **options)
        problem = make_problem(candidates, values, cfg['agents'], cfg)
        best = total_value(problem, exact(problem))
        gaps.append(1 - total_value(problem, anneal(problem, cfg['anneal'], rng)) / best)
    return {'quarters': len(gaps), 'mean_gap': float(np.mean(gaps)), 'max_gap': float(np.max(gaps))}


def repeated_runs(inputs, cfg, options, runs):
    """Solve every quarter `runs` times with different seeds: quality, runtime and solver variants."""
    rows = []
    for index, (split, origin, quarter) in enumerate(origins(inputs)):
        candidates = backtest_candidates(inputs, origin, cfg)
        truth = truth_problem(candidates, cfg['agents'], cfg)
        oracle = total_value(truth, exact(truth))
        rng = np.random.default_rng([cfg['seed'], index, 1000])
        values = planned_values(candidates, known_errors(inputs['errors'], quarter), cfg['agents'],
                                cfg, rng, **options)
        problem = make_problem(candidates, values, cfg['agents'], cfg)
        began = perf_counter()
        best = total_value(problem, exact(problem))
        exact_seconds = perf_counter() - began
        start = greedy(problem)
        for run in range(runs):
            rng = np.random.default_rng([cfg['seed'], index, 2000 + run])
            began = perf_counter()
            annealed = anneal(problem, {**cfg['anneal'], 'polish': False}, rng)
            middle = perf_counter()
            polished = hill_climb(problem, annealed)
            rows.append({'split': split, 'forecast_quarter': quarter, 'run': run,
                         'gap_annealing': 1 - total_value(problem, annealed) / best,
                         'gap_annealing_hill_climb': 1 - total_value(problem, polished) / best,
                         'gap_greedy': 1 - total_value(problem, start) / best,
                         'greedy_broken_constraints': violations(problem, start),
                         'share_of_oracle': total_value(truth, polished) / oracle,
                         'annealing_seconds': middle - began, 'hill_climb_seconds': perf_counter() - middle,
                         'exact_seconds': exact_seconds})
    return pd.DataFrame(rows)


def repeated_summary(table):
    """Spread between seeds (solver randomness) and between quarters (market), kept apart."""
    test = table[table.split.eq('test')]
    seeds = test.groupby('run').share_of_oracle.mean()
    quarters = test.groupby('forecast_quarter').share_of_oracle.mean()
    broken = table.groupby('forecast_quarter').greedy_broken_constraints.first()
    summary = {'runs': int(table.run.nunique()), 'quarters': int(table.forecast_quarter.nunique()),
               'test_share_of_oracle_mean': float(quarters.mean()),
               'test_std_between_seeds': float(seeds.std()), 'test_std_between_quarters': float(quarters.std()),
               'greedy_quarters_feasible': int(broken.eq(0).sum())}
    for column in ['gap_annealing', 'gap_annealing_hill_climb', 'annealing_seconds',
                   'hill_climb_seconds', 'exact_seconds']:
        summary[column] = {'mean': float(table[column].mean()), 'std': float(table[column].std()),
                           'max': float(table[column].max())}
    return summary


def paired(results, method, other):
    """Paired quarter-by-quarter comparison on the test, with a Wilcoxon signed-rank test."""
    wide = results[results.split.eq('test')].pivot(index='forecast_quarter', columns='method',
                                                   values='share_of_oracle')
    difference = wide[method] - wide[other]
    changed = difference[difference.abs() > 1e-12]
    return {'method': method, 'against': other, 'mean_difference': float(difference.mean()),
            'std_difference': float(difference.std()), 'wins': int((changed > 0).sum()),
            'losses': int((changed < 0).sum()), 'ties': int(len(difference) - len(changed)),
            'wilcoxon_p': float(stats.wilcoxon(changed).pvalue)}


def convergence(inputs, cfg, options):
    """Gap to the exact optimum as iterations pass, one row per quarter."""
    curves, quarters = [], []
    for index, (split, origin, quarter) in enumerate(origins(inputs)):
        candidates = backtest_candidates(inputs, origin, cfg)
        rng = np.random.default_rng([cfg['seed'], index, 3000])
        values = planned_values(candidates, known_errors(inputs['errors'], quarter), cfg['agents'],
                                cfg, rng, **options)
        problem = make_problem(candidates, values, cfg['agents'], cfg)
        trace = []
        anneal(problem, {**cfg['anneal'], 'polish': False}, rng, trace=trace)
        curves.append(1 - np.array(trace) / total_value(problem, exact(problem)))
        quarters.append(quarter)
    return pd.DataFrame(np.array(curves), index=quarters, columns=[500 * i for i in range(len(curves[0]))])


def method_summary(results):
    test = results[results.split.eq('test')]
    summary = test.groupby('method').agg(
        share_of_oracle=('share_of_oracle', 'mean'), worst_quarter=('share_of_oracle', 'min'),
        realised_value=('realised_value', 'sum'), mean_moves=('moves', 'mean'),
        feasible_quarters=('feasible', 'sum'), quarters=('feasible', 'size'))
    return summary.sort_values('share_of_oracle', ascending=False).reset_index()


SENSITIVITY = [
    ('agents = 10', dict(agents=10)), ('agents = 40', dict(agents=40)),
    ('deals_per_agent = 1', dict(deals_per_agent=1.0)), ('deals_per_agent = 4', dict(deals_per_agent=4.0)),
    ('max_market_share = 2%', dict(max_market_share=0.02)), ('max_market_share = 10%', dict(max_market_share=0.1)),
    ('equal commission 2%', dict(commission_rate={'Ready': 0.02, 'Off-Plan': 0.02})),
    ('objective = deals', dict(objective='deals')),
    ('max_areas = 5', dict(max_areas=5)), ('max_areas = 12', dict(max_areas=12)),
]


def sensitivity(inputs, base, options, name, plan_live):
    """Change one assumption at a time. Is the method still ahead, and does the live plan change?"""
    live = plan_live(base)
    rows = []
    for label, change in [('default', {})] + SENSITIVITY:
        cfg = {**base, **change}
        results = backtest(inputs, cfg, variants={name: options}, settings=FAST)
        means = results[results.split.eq('test')].groupby('method').share_of_oracle.mean()
        wins = results[results.split.eq('test')].pivot(index='forecast_quarter', columns='method',
                                                       values='share_of_oracle')
        changed = plan_live(cfg)
        same = sum(min(live.get(k, 0), v) for k, v in changed.items())
        rows.append({'setting': label, 'optimiser': means[name],
                     'share_of_forecast_value': means['share_of_forecast_value'],
                     'share_of_forecast': means['share_of_forecast'],
                     'quarters_beating_value_rule': int((wins[name] > wins['share_of_forecast_value']).sum()),
                     'agents_same_as_default_plan': same, 'agents': cfg['agents']})
    return pd.DataFrame(rows)
