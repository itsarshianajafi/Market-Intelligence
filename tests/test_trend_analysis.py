"""Artificial test cases only: these are not real market figures."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from src.trend_analysis.baselines import crisp_labels, kmeans_labels
from src.trend_analysis.evaluate import forward_check, persistence
from src.trend_analysis.features import build_features, last_complete_quarter, load_monthly
from src.trend_analysis.fuzzy import classify, three_sets
from src.trend_analysis.run import DEFAULT_CONFIG, OUTPUT_COLUMNS, run

CFG = {**json.loads(DEFAULT_CONFIG.read_text()), 'start_quarter': '2021Q1', 'min_sales': 10,
       'bootstrap_runs': 3, 'kmeans_runs': 2, 'figures': False}
Q = pd.Period('2022Q2', freq='Q')
SCALES = {'price': (0.05, 0.2), 'volume': (0.2, 0.8), 'volatility': (0.05, 0.15)}


def month_rows(area, unit_type, prices, count=10, registration='Ready', start='2020-01'):
    """One row per month; prices maps a year to a price per m2 for every month of that year."""
    months = pd.period_range(start, '2022-12', freq='M')
    return [dict(area=area, property_type='Unit', unit_type=unit_type, registration_type=registration,
                 month=str(m), transaction_count=count(m.year) if callable(count) else count,
                 median_price_per_m2_aed=prices[m.year]) for m in months]


def features(rows, cfg=CFG):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'monthly.csv'
        pd.DataFrame(rows).to_csv(path, index=False)
        return build_features(load_monthly(path, cfg['property_types']), pd.Period('2022Q4'), cfg)


def frame(price, volume=0.0, volatility=0.0):
    return pd.DataFrame({'log_price_change': [price], 'log_volume_change': [volume],
                         'volatility': [volatility]})


class FeatureTests(unittest.TestCase):
    def test_last_complete_quarter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'report.json'
            for date_max, expected in [('2026-10-27', '2026Q3'), ('2026-09-30', '2026Q3')]:
                path.write_text(json.dumps({'date_max': date_max}))
                self.assertEqual(str(last_complete_quarter(path)), expected)

    def test_matched_price_change(self):
        df = features(month_rows('A', 'Flat', {2020: 10_000, 2021: 10_000, 2022: 11_000}))
        row = df.loc[df.quarter == pd.Period('2022Q2')].iloc[0]
        self.assertAlmostEqual(row.log_price_change, np.log(1.1))
        self.assertEqual(row.status, 'ok')

    def test_mix_shift_is_not_a_price_change(self):
        # Prices never change, but sales move from flats to cheaper villas in 2022.
        rows = (month_rows('A', 'Flat', {y: 10_000 for y in (2020, 2021, 2022)},
                           count=lambda y: 5 if y == 2022 else 30)
                + month_rows('A', 'Villa', {y: 5_000 for y in (2020, 2021, 2022)},
                             count=lambda y: 30 if y == 2022 else 5))
        row = features(rows).query("quarter == @Q").iloc[0]
        self.assertAlmostEqual(row.log_price_change, 0)

    def test_few_sales_are_insufficient(self):
        df = features(month_rows('A', 'Flat', {2020: 1, 2021: 1, 2022: 1}, count=2))
        self.assertTrue(df.status.eq('insufficient_data').all())

    def test_off_plan_and_ready_are_separate_segments(self):
        rows = (month_rows('A', 'Flat', {2020: 10, 2021: 10, 2022: 20})
                + month_rows('A', 'Flat', {2020: 10, 2021: 10, 2022: 10}, registration='Off-Plan'))
        q = features(rows).query("quarter == @Q").set_index('registration_type')
        self.assertAlmostEqual(q.loc['Ready', 'log_price_change'], np.log(2))
        self.assertAlmostEqual(q.loc['Off-Plan', 'log_price_change'], 0)


class FuzzyTests(unittest.TestCase):
    def test_memberships_sum_to_one(self):
        x = np.linspace(-1, 1, 41)
        self.assertTrue(np.allclose(sum(three_sets(x, 0.05, 0.2)), 1))

    def test_clear_cases(self):
        for price, volume, expected in [(0.4, 0.3, 'Rising'), (-0.4, -0.3, 'Declining'),
                                        (0.01, 0.0, 'Stable'), (0.4, -1.0, 'Stable')]:
            result = classify(frame(price, volume), SCALES).iloc[0]
            self.assertEqual(result.trend_label, expected, (price, volume))
        self.assertGreater(classify(frame(0.4), SCALES).trend_score.iloc[0], 0.3)
        self.assertLess(classify(frame(-0.4), SCALES).trend_score.iloc[0], -0.3)

    def test_high_volatility_pulls_score_towards_stable(self):
        calm = classify(frame(0.15, volatility=0.0), SCALES).trend_score.iloc[0]
        jumpy = classify(frame(0.15, volatility=0.5), SCALES).trend_score.iloc[0]
        self.assertLess(jumpy, calm)

    def test_missing_volatility_is_not_high(self):
        self.assertAlmostEqual(classify(frame(0.4, volatility=np.nan), SCALES).trend_score.iloc[0],
                               classify(frame(0.4, volatility=0.0), SCALES).trend_score.iloc[0])


class BaselineAndEvaluationTests(unittest.TestCase):
    def test_crisp_threshold_is_fuzzy_crossover(self):
        labels = crisp_labels(pd.DataFrame({'log_price_change': [0.13, 0.12, -0.13]}), SCALES)
        self.assertEqual(list(labels), ['Rising', 'Stable', 'Declining'])

    def test_kmeans_names_clusters_by_price(self):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({'log_price_change': np.repeat([-0.3, 0.0, 0.3], 20) + rng.normal(0, 0.01, 60),
                           'log_volume_change': np.repeat([-0.5, 0.0, 0.5], 20) + rng.normal(0, 0.01, 60),
                           'volatility': rng.normal(0.1, 0.001, 60)})
        labels = kmeans_labels(df, seed=0)
        self.assertEqual(list(labels[[0, 20, 40]]), ['Declining', 'Stable', 'Rising'])

    def test_forward_check_removes_market_wide_move(self):
        ok = pd.DataFrame({'quarter': ['Q'] * 4, 'label': ['Rising', 'Rising', 'Stable', 'Stable'],
                           'next_status': 'ok', 'next_log_price_change': [0.3, 0.3, 0.1, 0.1]})
        out = forward_check(ok, 'label').set_index('label')
        self.assertAlmostEqual(out.loc['Rising', 'mean_excess_change'], 0.1)
        self.assertAlmostEqual(out.loc['Stable', 'mean_excess_change'], -0.1)

    def test_persistence_skips_gaps(self):
        q = pd.PeriodIndex(['2021Q1', '2021Q2', '2021Q4'], freq='Q')
        ok = pd.DataFrame({'area': 'A', 'registration_type': 'Ready', 'quarter': q,
                           'label': ['Rising', 'Rising', 'Stable']})
        self.assertEqual(persistence(ok, 'label'), 1.0)


class RunTests(unittest.TestCase):
    def test_end_to_end_output(self):
        rows = []
        for i, growth in enumerate([0.5, 0.3, 0.1, 0.0, -0.1, -0.3]):
            rows += month_rows(f'Area {i}', 'Flat', {2020: 100, 2021: 100 * (1 + growth / 2),
                                                     2022: 100 * (1 + growth)},
                              count=lambda y, i=i: 20 + i * (y - 2019))
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pd.DataFrame(rows).to_csv(tmp / 'monthly.csv', index=False)
            (tmp / 'report.json').write_text(json.dumps({'date_max': '2022-12-31'}))
            cfg = {**CFG, 'input': tmp / 'monthly.csv', 'quality_report': tmp / 'report.json',
                   'output': tmp / 'trends.csv', 'report_dir': tmp / 'reports'}
            run(cfg)
            out = pd.read_csv(tmp / 'trends.csv')
            self.assertEqual(list(out.columns), OUTPUT_COLUMNS)
            self.assertTrue(out.loc[out.quarter == '2022Q4', 'provisional'].all())
            self.assertFalse(out.loc[out.quarter == '2022Q3', 'provisional'].any())
            self.assertTrue((tmp / 'reports' / 'evaluation.json').exists())


if __name__ == '__main__':
    unittest.main()
