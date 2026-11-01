"""Artificial test cases only, except the last class, which runs on the shared output files."""
from itertools import product
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from src.allocation import evaluate
from src.allocation.data import (backtest_candidates, deployment_candidates, known_errors, load_inputs,
                                 quarterly, sha256, trailing_tickets)
from src.allocation.model import captured_deals, scenarios, value_table
from src.allocation.run import DEFAULT_CONFIG, OUTPUT_COLUMNS, run
from src.allocation.search import (anneal, exact, greedy, hill_climb, limits, make_problem, total_value,
                                   violations)

CFG = json.loads(DEFAULT_CONFIG.read_text())
SETTINGS = {**CFG['anneal'], 'iterations': 4000, 'restarts': 2}


def candidates(rows):
    return pd.DataFrame(rows, columns=['area', 'registration_type', 'demand', 'ticket', 'rate', 'status']).assign(
        trend_score=np.nan, trend_label='Stable')


def small_problem(agents=6, seed=0, **change):
    """Five areas with Ready and Off-Plan segments and random concave values."""
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({'area': [f'A{i // 2}' for i in range(10)],
                          'registration_type': ['Ready', 'Off-Plan'] * 5})
    cfg = {**CFG, 'max_areas': 3, **change}
    depth = limits(agents, cfg) + 1
    gains = np.sort(rng.uniform(1, 100, size=(10, depth - 1)), axis=1)[:, ::-1]
    values = np.hstack([np.zeros((10, 1)), gains.cumsum(axis=1)])
    return make_problem(frame, values, agents, cfg)


def brute_force(p):
    """Every allocation of a tiny problem; the reference the solvers must match."""
    best, best_value = None, -np.inf
    for x in product(range(p.max_area + 1), repeat=len(p.area)):
        if sum(x) == p.agents and violations(p, x) == 0:
            value = total_value(p, np.array(x))
            if value > best_value:
                best, best_value = np.array(x), value
    return best, best_value


class ResponseTests(unittest.TestCase):
    def test_one_agent_is_near_full_productivity_in_a_big_segment(self):
        self.assertAlmostEqual(float(captured_deals(1, 100000, CFG)), CFG['deals_per_agent'], places=2)

    def test_diminishing_returns_and_ceiling(self):
        deals = captured_deals(np.arange(40), 100, CFG)
        steps = np.diff(deals)
        self.assertTrue((steps > 0).all() and (np.diff(steps) < 0).all())
        self.assertLess(deals[-1], 0.05 * 100 + 1e-9)

    def test_zero_demand_gives_zero_not_nan(self):
        self.assertEqual(float(captured_deals(3, 0, CFG)), 0.0)

    def test_value_table_averages_scenarios(self):
        table = value_table(np.array([[100.0, 300.0]]), np.array([10.0]), 3, CFG)
        expected = (captured_deals(2, 100, CFG) + captured_deals(2, 300, CFG)) / 2 * 10
        self.assertAlmostEqual(table[0, 2], float(expected))
        self.assertEqual(table[0, 0], 0)


class ScenarioTests(unittest.TestCase):
    errors = pd.DataFrame({'split': 'test', 'forecast_quarter': ['2025Q1'] * 3 + ['2025Q2'] * 3,
                           'prediction': [10, 100, 1000] * 2, 'log_error': [0.1, -0.1, 0.2, 0.3, -0.2, 0.0]})
    frame = candidates([('A', 'Ready', 50, 1e6, 0.02, 'ok'), ('B', 'Ready', 50, 1e6, 0.02, 'fallback')])

    def test_same_seed_same_scenarios(self):
        one = scenarios(self.frame, self.errors, CFG, np.random.default_rng(1))
        two = scenarios(self.frame, self.errors, CFG, np.random.default_rng(1))
        np.testing.assert_array_equal(one, two)
        self.assertEqual(one.shape, (2, CFG['scenarios']))
        self.assertTrue((one >= 0).all())

    def test_fallback_forecasts_are_less_certain(self):
        draws = scenarios(self.frame, self.errors, CFG, np.random.default_rng(1), count=4000)
        self.assertGreater(np.log1p(draws[1]).std(), np.log1p(draws[0]).std())

    def test_no_errors_means_the_forecast_itself(self):
        draws = scenarios(self.frame, self.errors.iloc[:0], CFG, np.random.default_rng(1))
        np.testing.assert_array_equal(draws[:, 0], [50, 50])


class LeakageTests(unittest.TestCase):
    errors = pd.DataFrame({'split': ['validation'] * 2 + ['test'] * 2,
                           'forecast_quarter': ['2024Q1', '2024Q2', '2025Q1', '2025Q2'],
                           'prediction': 10.0, 'log_error': 0.0})

    def test_test_quarter_only_sees_finished_quarters(self):
        self.assertEqual(known_errors(self.errors, '2025Q2').forecast_quarter.tolist(),
                         ['2024Q1', '2024Q2', '2025Q1'])

    def test_validation_quarter_never_sees_itself_or_the_test(self):
        self.assertEqual(known_errors(self.errors, '2024Q1').forecast_quarter.tolist(), ['2024Q2'])

    def test_ticket_ignores_quarters_after_the_origin(self):
        table = pd.DataFrame({'area': 'A', 'registration_type': 'Ready', 'quarter': ['2025Q1', '2025Q2'],
                              'sales': [10, 10], 'total_price': [1e7, 9e7]})
        self.assertEqual(trailing_tickets(table, '2025Q1', 4).ticket.iloc[0], 1e6)


class DataTests(unittest.TestCase):
    def test_single_huge_sale_does_not_set_the_typical_deal(self):
        monthly = pd.DataFrame({'area': 'A', 'registration_type': 'Ready', 'month': ['2025-01', '2025-02'],
                                'transaction_count': [10, 10], 'median_price_aed': [1e6, 1e6],
                                'total_price_aed': [1e7, 5e8]})
        self.assertEqual(quarterly(monthly).total_price.iloc[0], 2e7)

    def test_hash_ignores_line_endings(self):
        with tempfile.TemporaryDirectory() as folder:
            lf, crlf = Path(folder) / 'a.csv', Path(folder) / 'b.csv'
            lf.write_bytes(b'a,b\n1,2\n')
            crlf.write_bytes(b'a,b\r\n1,2\r\n')
            self.assertEqual(sha256(lf), sha256(crlf))


class ConstraintTests(unittest.TestCase):
    def test_lone_agent_breaks_the_team_minimum(self):
        p = small_problem()
        x = np.zeros(10, dtype=int)
        x[[0, 2]] = [5, 1]
        self.assertGreater(violations(p, x), 0)

    def test_team_split_inside_one_area_is_one_team(self):
        p = small_problem()
        x = np.zeros(10, dtype=int)
        x[[0, 1, 2, 3, 4, 5]] = 1
        self.assertEqual(violations(p, x), 0)

    def test_too_many_areas(self):
        p = small_problem(agents=8)
        x = np.zeros(10, dtype=int)
        x[[0, 2, 4, 6]] = 2
        self.assertEqual(violations(p, x), 1 + max(0, p.offplan_low))

    def test_impossible_team_is_refused(self):
        with self.assertRaises(ValueError):
            limits(1, CFG)

    def test_too_few_areas_for_the_team_is_refused(self):
        with self.assertRaises(ValueError):
            small_problem(agents=40, max_areas=1)


class SolverTests(unittest.TestCase):
    def test_exact_matches_brute_force(self):
        for seed in range(3):
            p = small_problem(seed=seed)
            _, value = brute_force(p)
            self.assertAlmostEqual(total_value(p, exact(p)), value, places=6)

    def test_anneal_is_feasible_and_near_optimal(self):
        for seed in range(5):
            p = small_problem(agents=8, seed=seed)
            x = anneal(p, SETTINGS, np.random.default_rng(seed))
            self.assertEqual(violations(p, x), 0)
            self.assertGreater(total_value(p, x), 0.97 * total_value(p, exact(p)))

    def test_anneal_is_reproducible(self):
        p = small_problem(agents=8)
        one, two = (anneal(p, SETTINGS, np.random.default_rng(3)) for _ in range(2))
        np.testing.assert_array_equal(one, two)

    def test_move_limit_is_respected(self):
        p = small_problem(agents=8)
        p.current, p.max_moves = exact(small_problem(agents=8, seed=9)), 2
        for x in (anneal(p, SETTINGS, np.random.default_rng(0)), exact(p)):
            self.assertEqual(violations(p, x), 0)
            self.assertLessEqual(np.maximum(x - p.current, 0).sum(), 2)

    def test_off_plan_limits_are_respected(self):
        p = small_problem(agents=10, max_areas=4, offplan_share=[0.4, 0.6])
        for x in (anneal(p, SETTINGS, np.random.default_rng(0)), exact(p)):
            self.assertTrue(4 <= x[p.offplan].sum() <= 6)

    def test_trace_only_improves(self):
        p = small_problem(agents=8)
        trace = []
        anneal(p, SETTINGS, np.random.default_rng(0), trace=trace)
        known = np.array(trace)[~np.isnan(trace)]
        self.assertGreater(len(known), 0)
        self.assertTrue((np.diff(known) >= 0).all())

    def test_hill_climb_never_makes_a_plan_worse(self):
        p = small_problem(agents=8)
        plain = anneal(p, {**SETTINGS, 'iterations': 300, 'polish': False}, np.random.default_rng(0))
        climbed = hill_climb(p, plain)
        self.assertGreaterEqual(total_value(p, climbed), total_value(p, plain))
        self.assertEqual(violations(p, climbed), 0)

    def test_greedy_places_every_agent(self):
        p = small_problem(agents=8)
        self.assertEqual(greedy(p).sum(), 8)


class RuleOfThumbTests(unittest.TestCase):
    def test_proportional_spends_all_agents_within_the_cap(self):
        x = evaluate.proportional([1000, 10, 10, 1], 10, 3, 5)
        self.assertEqual(x.sum(), 10)
        self.assertEqual(x.max(), 5)
        self.assertEqual(x[3], 0)

    def test_even_split(self):
        np.testing.assert_array_equal(evaluate.even([1, 9, 5, 7], 6, 3, 5), [0, 2, 2, 2])


class StatisticsTests(unittest.TestCase):
    def test_paired_comparison_counts_wins_losses_and_ties(self):
        rows = [dict(split='test', forecast_quarter=q, method=m, share_of_oracle=v) for q, a, b in
                [('Q1', 0.9, 0.5), ('Q2', 0.8, 0.5), ('Q3', 0.7, 0.7), ('Q4', 0.4, 0.5)]
                for m, v in (('a', a), ('b', b))]
        result = evaluate.paired(pd.DataFrame(rows), 'a', 'b')
        self.assertEqual((result['wins'], result['losses'], result['ties']), (2, 1, 1))
        self.assertAlmostEqual(result['mean_difference'], 0.15)


class SharedFileTests(unittest.TestCase):
    """Runs on data/shared. Reads Part 3's files; writes only to a temporary folder."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        base = Path(cls.folder.name)
        cls.cfg = {**CFG, 'output': str(base / 'allocation.csv'), 'manifest': str(base / 'manifest.json'),
                   'report_dir': str(base / 'part4'), 'figures': False, 'robustness_runs': 2,
                   'anneal': {**CFG['anneal'], 'iterations': 3000, 'restarts': 1}}
        cls.out, cls.manifest, _ = run(cls.cfg, evaluation=False)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_output_contract(self):
        self.assertEqual(list(self.out.columns), OUTPUT_COLUMNS)
        self.assertEqual(self.out.agents.sum(), self.cfg['agents'])
        self.assertFalse(self.out.duplicated(['area', 'registration_type']).any())
        self.assertTrue(self.manifest['feasible'])

    def test_blank_forecasts_never_get_agents_or_a_zero(self):
        blank = self.out[self.out.forecast_status.isin(['missing_input', 'insufficient_data'])]
        self.assertGreater(len(blank), 0)
        self.assertEqual(blank.agents.sum(), 0)
        self.assertTrue(blank.forecast_sales.isna().all())

    def test_every_forecast_segment_is_accounted_for(self):
        forecasts = pd.read_csv(self.cfg['forecasts'])
        self.assertEqual(len(self.out), forecasts[forecasts.target.eq('sales_count')].shape[0])

    def test_tampered_forecasts_are_refused(self):
        tampered = Path(self.folder.name) / 'tampered.csv'
        tampered.write_text(Path(self.cfg['forecasts']).read_text() + '\n')
        with self.assertRaises(ValueError):
            load_inputs({**self.cfg, 'forecasts': str(tampered)})

    def test_backtest_candidates_only_use_the_past_for_decisions(self):
        inputs = load_inputs(self.cfg)
        early = backtest_candidates(inputs, '2024Q4', self.cfg)
        changed = dict(inputs)
        future = inputs['quarterly'].quarter > '2024Q4'
        changed['quarterly'] = inputs['quarterly'].assign(
            total_price=inputs['quarterly'].total_price.where(~future, 1.0))
        again = backtest_candidates(changed, '2024Q4', self.cfg)
        np.testing.assert_allclose(early.ticket, again.ticket)
        np.testing.assert_allclose(early.demand, again.demand)

    def test_small_segments_are_not_candidates(self):
        inputs = load_inputs(self.cfg)
        self.assertGreaterEqual(deployment_candidates(inputs, self.cfg).demand.min(), self.cfg['min_forecast_sales'])


if __name__ == '__main__':
    unittest.main()
