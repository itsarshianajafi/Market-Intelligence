"""Run Part 4: recommend an allocation for the forecast quarter and evaluate the method."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from . import evaluate, figures
from .data import KEYS, SCHEMA_VERSION, deployment_candidates, load_inputs, sha256
from .model import captured_deals, scenarios, value_table
from .search import anneal, exact, limits, make_problem, total_value, violations

DEFAULT_CONFIG = Path(__file__).with_name('config.json')
OUTPUT_COLUMNS = ['schema_version', 'run_id', 'area', 'registration_type', 'forecast_quarter',
                  'agents', 'forecast_sales', 'forecast_status', 'price_status', 'ticket_aed',
                  'expected_deals', 'expected_commission_aed', 'next_agent_value_aed',
                  'selection_rate', 'trend_label', 'trend_score', 'note']
NOTES = {'insufficient_data': 'No usable forecast: insufficient_data',
         'missing_input': 'No usable forecast: missing_input',
         'ok': 'Forecast below min_forecast_sales', 'fallback': 'Forecast below min_forecast_sales'}


def options_of(cfg):
    return {'use_scenarios': cfg['use_scenarios'], 'trend_weight': cfg['trend_weight']}


def load_current(cfg, candidates):
    """Optional CSV (area, registration_type, agents): where the team sits today."""
    if not cfg.get('current_allocation'):
        return None
    current = pd.read_csv(cfg['current_allocation'])
    merged = candidates[KEYS].merge(current, on=KEYS, how='left')
    return merged.agents.fillna(0).astype(int).to_numpy()


def live_problem(candidates, inputs, cfg, agents=None):
    agents = agents or cfg['agents']
    rng = np.random.default_rng(cfg['seed'])
    values = evaluate.planned_values(candidates, inputs['errors'], agents, cfg, rng, **options_of(cfg))
    return make_problem(candidates, values, agents, cfg, load_current(cfg, candidates)), rng


def robustness(candidates, inputs, cfg):
    """Replan on single draws of forecast error. How often is each segment still chosen?"""
    rng = np.random.default_rng([cfg['seed'], 1])
    cap = limits(cfg['agents'], cfg)
    chosen = np.zeros(len(candidates))
    values = evaluate.deal_value(candidates.ticket.to_numpy(), candidates.rate.to_numpy(), cfg)
    for _ in range(cfg['robustness_runs']):
        draw = scenarios(candidates, inputs['errors'], cfg, rng, count=1)[:, 0]
        problem = make_problem(candidates, value_table(draw, values, cap, cfg), cfg['agents'], cfg,
                               load_current(cfg, candidates))
        chosen += anneal(problem, evaluate.FAST, rng) > 0
    return chosen / cfg['robustness_runs']


def team_curve(candidates, inputs, cfg):
    rows = []
    for agents in cfg['team_sizes']:
        problem, rng = live_problem(candidates, inputs, {**cfg, 'current_allocation': None}, agents)
        began = perf_counter()
        x = exact(problem)
        middle = perf_counter()
        searched = anneal(problem, cfg['anneal'], rng)
        rows.append({'agents': agents, 'expected_commission_aed': total_value(problem, x),
                     'areas_used': len(set(problem.area[x > 0].tolist())),
                     'offplan_agents': int(x[problem.offplan].sum()),
                     'annealing_gap': 1 - total_value(problem, searched) / total_value(problem, x),
                     'exact_seconds': middle - began, 'annealing_seconds': perf_counter() - middle})
    curve = pd.DataFrame(rows)
    curve['value_per_added_agent_aed'] = (curve.expected_commission_aed.diff() / curve.agents.diff())
    return curve


def output_table(candidates, x, problem, selection, inputs, cfg, run_id):
    rng = np.random.default_rng([cfg['seed'], 2])
    demand = scenarios(candidates, inputs['errors'], cfg, rng) if cfg['use_scenarios'] \
        else candidates.demand.to_numpy()[:, None]
    deals = captured_deals(x[:, None], demand, cfg).mean(axis=1)
    rows = np.arange(len(x))
    next_value = problem.values[rows, np.minimum(x + 1, problem.max_area)] - problem.values[rows, x]
    plan = candidates.rename(columns={'demand': 'forecast_sales', 'status': 'forecast_status',
                                      'ticket': 'ticket_aed'}).assign(
        agents=x, expected_deals=deals, next_agent_value_aed=next_value, selection_rate=selection,
        expected_commission_aed=deals * candidates.ticket * candidates.rate)
    plan['note'] = np.where(x > 0, 'Allocated', 'Usable forecast, not selected')
    forecasts = inputs['forecasts']
    rest = forecasts[forecasts.target.eq('sales_count')].merge(candidates[KEYS], on=KEYS, how='left', indicator=True)
    rest = rest[rest['_merge'].eq('left_only')]
    # Big enough, but dropped for having no sale in the ticket window (finish_candidates).
    unpriced = rest.status.isin(['ok', 'fallback']) & rest.forecast_value.ge(cfg['min_forecast_sales'])
    rest = pd.DataFrame({'area': rest.area, 'registration_type': rest.registration_type, 'agents': 0,
                         'forecast_sales': rest.forecast_value, 'forecast_status': rest.status,
                         'note': rest.status.map(NOTES).mask(unpriced, 'No recent sales to value a deal')})
    trends = inputs['trends'][inputs['trends'].quarter.eq(inputs['manifest']['origin_quarter'])]
    rest = rest.merge(trends[KEYS + ['trend_label', 'trend_score']], on=KEYS, how='left')
    rest['trend_label'] = rest.trend_label.fillna('Insufficient data')
    out = pd.concat([plan, rest], ignore_index=True).assign(
        schema_version=SCHEMA_VERSION, run_id=run_id,
        forecast_quarter=inputs['manifest']['forecast_quarter'])
    out = out.sort_values(['agents', 'expected_commission_aed'], ascending=False, na_position='last')
    return out[OUTPUT_COLUMNS].round({'forecast_sales': 2, 'ticket_aed': 0, 'expected_deals': 3,
                                      'expected_commission_aed': 0, 'next_agent_value_aed': 0,
                                      'selection_rate': 3, 'trend_score': 3})


def plan_for(inputs, candidates):
    """Live plan under a config as {segment: agents}, used to compare assumptions."""
    def live(cfg):
        problem, rng = live_problem(candidates.assign(rate=candidates.registration_type.map(cfg['commission_rate'])),
                                    inputs, cfg)
        x = anneal(problem, evaluate.FAST, rng)
        return {k: int(v) for k, v in zip(zip(candidates.area, candidates.registration_type), x) if v}
    return live


def evaluate_all(inputs, candidates, cfg, report_dir):
    """Backtest, freeze the policy on 2024, then report 2025-26 and the sensitivity checks."""
    results = evaluate.backtest(inputs, cfg)
    name, validation = evaluate.select_variant(results, cfg)
    options = evaluate.VARIANTS[name]
    cfg = {**cfg, **options}
    limited = evaluate.limited_moves(inputs, cfg, options, cfg['backtest_moves_limit'])
    results = pd.concat([results.replace({'method': {name: 'selected'}}), limited], ignore_index=True)
    results.to_csv(report_dir / 'backtest.csv', index=False)
    summary = evaluate.method_summary(results)
    summary.to_csv(report_dir / 'backtest_summary.csv', index=False)
    table = results[results.split.eq('test')].pivot(index='forecast_quarter', columns='method', values='share_of_oracle')
    gap = evaluate.solver_gap(inputs, cfg, options)
    repeated = evaluate.repeated_runs(inputs, cfg, options, cfg['repeated_runs'])
    repeated.to_csv(report_dir / 'repeated_runs.csv', index=False)
    curves = evaluate.convergence(inputs, cfg, options)
    curves.to_csv(report_dir / 'convergence.csv', index_label='forecast_quarter')
    figures.convergence(curves, report_dir / 'convergence.png')
    live = plan_for(inputs, candidates)
    sensitivity = evaluate.sensitivity(inputs, cfg, options, name, live)
    sensitivity.to_csv(report_dir / 'sensitivity.csv', index=False)
    result = {'selected_variant': name, 'validation_share_of_oracle': validation,
              'test_summary': summary.to_dict('records'),
              'test_quarters_selected_beats': {m: int((table['selected'] > table[m]).sum())
                                               for m in table if m != 'selected'},
              'paired_tests': [evaluate.paired(results, 'selected', 'share_of_forecast_value'),
                               evaluate.paired(results, 'selected', 'optimiser_naive_input'),
                               evaluate.paired(results, 'selected_move_limit', 'selected')],
              'repeated_runs': evaluate.repeated_summary(repeated), 'solver_gap': gap}
    (report_dir / 'evaluation.json').write_text(json.dumps(result, indent=2, default=float) + '\n')
    figures.backtest(summary, report_dir / 'backtest.png')
    return cfg, result


def run(cfg, evaluation=True):
    report_dir = Path(cfg['report_dir'])
    report_dir.mkdir(parents=True, exist_ok=True)
    inputs = load_inputs(cfg)
    candidates = deployment_candidates(inputs, cfg)
    result = None
    if evaluation:
        cfg, result = evaluate_all(inputs, candidates, cfg, report_dir)
    problem, rng = live_problem(candidates, inputs, cfg)
    searched, best = anneal(problem, cfg['anneal'], rng), exact(problem)
    source = 'annealing' if total_value(problem, searched) >= total_value(problem, best) - 1e-6 else 'exact_check'
    x = searched if source == 'annealing' else best     # annealing has no guarantee; never ship the worse plan
    selection = robustness(candidates, inputs, cfg)
    # Where the files go does not change the plan, so it is not part of the run's identity.
    identity = json.dumps({k: v for k, v in sorted(cfg.items()) if k not in ('output', 'manifest', 'report_dir')},
                          sort_keys=True, default=str)
    run_id = 'part4-' + hashlib.sha256((inputs['manifest']['run_id'] + identity).encode()).hexdigest()[:16]
    out = output_table(candidates, x, problem, selection, inputs, cfg, run_id)
    out.to_csv(cfg['output'], index=False)
    curve = team_curve(candidates, inputs, cfg)
    curve.to_csv(report_dir / 'team_size.csv', index=False)
    quarter = inputs['manifest']['forecast_quarter']
    if cfg.get('figures', True):
        figures.allocation(out, quarter, cfg['agents'], report_dir / 'allocation.png')
        figures.team_size(curve, report_dir / 'team_size.png')
    manifest = {
        'schema_version': SCHEMA_VERSION, 'run_id': run_id,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'forecast_quarter': quarter, 'forecast_run_id': inputs['manifest']['run_id'],
        'agents': cfg['agents'], 'candidates': len(candidates), 'segments_used': int(np.count_nonzero(x)),
        'areas_used': len(set(problem.area[x > 0].tolist())), 'feasible': violations(problem, x) == 0,
        'plan_source': source, 'annealing_value': total_value(problem, searched),
        'exact_value': total_value(problem, best),
        'solver_gap': 1 - total_value(problem, searched) / total_value(problem, best),
        'source_hashes': {str(cfg[k]): sha256(cfg[k]) for k in
                          ['forecasts', 'market_trends', 'monthly_sales', 'predictions']},
        'assumptions_not_from_data': {k: cfg[k] for k in ['agents', 'deals_per_agent', 'max_market_share',
                                                          'commission_rate', 'min_team_per_area', 'max_area_share',
                                                          'max_areas', 'offplan_share']},
        'policy': options_of(cfg), 'output_sha256': sha256(cfg['output'])}
    Path(cfg['manifest']).write_text(json.dumps(manifest, indent=2, default=float) + '\n')
    return out, manifest, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--agents', type=int, help='Team size; overrides the config')
    parser.add_argument('--current', help='CSV of today\'s allocation (area, registration_type, agents)')
    parser.add_argument('--max-moves', type=int, help='Most agents that may change segment; needs --current')
    parser.add_argument('--skip-evaluation', action='store_true', help='Only the live plan; a few seconds')
    parser.add_argument('--output-dir', type=Path,
                        help='Write the plan, manifest and reports here instead of the shared files')
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text())
    if args.agents is not None:
        cfg['agents'] = args.agents
    cfg['current_allocation'] = args.current or cfg['current_allocation']
    cfg['max_moves'] = args.max_moves if args.max_moves is not None else cfg['max_moves']
    if cfg['agents'] < 1:
        parser.error('--agents must be at least 1')
    if cfg['max_moves'] is not None and not cfg['current_allocation']:
        parser.error('--max-moves needs --current: moves are counted from today\'s allocation')
    if cfg != json.loads(DEFAULT_CONFIG.read_text()) and not args.output_dir:
        parser.error('These settings differ from src/allocation/config.json; add --output-dir so the '
                     'shared allocation.csv stays the default plan')
    if args.output_dir:
        cfg.update(output=args.output_dir / 'allocation.csv', report_dir=args.output_dir,
                   manifest=args.output_dir / 'allocation_manifest.json')
    out, manifest, _ = run(cfg, evaluation=not args.skip_evaluation)
    picked = out[out.agents > 0][['area', 'registration_type', 'agents', 'forecast_sales', 'ticket_aed',
                                  'expected_commission_aed', 'selection_rate', 'trend_label']]
    print(picked.to_string(index=False))
    print(json.dumps({k: manifest[k] for k in ['agents', 'candidates', 'areas_used', 'solver_gap']}, indent=2))


if __name__ == '__main__':
    main()
