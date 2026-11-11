"""Artificial forecasting fixtures. Real export completeness is not established by tests."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from src.forecasting.data import (COUNT, PRICE, KEYS, TARGETS, build_panel, fingerprint,
    last_calendar_complete_quarter, load_inputs, quarter, validate_config)
from src.forecasting.evaluate import (MIN_RANGE_ERRORS, evaluate, evaluate_fallbacks, forecast_ranges, metrics,
    select_validation, walk_forward)
from src.forecasting.features import FEATURES, make_features, origin_candidates, training_rows
from src.forecasting.models import NAIVE, SEASONAL, fit_ridge, predict_ridge, ridge_id
from src.forecasting.run import DEFAULT_CONFIG, OUTPUT_KEY, deployment, run, validate_output


def config():
    return json.loads(DEFAULT_CONFIG.read_text())


def synthetic_monthly():
    rows = []
    for area, registration, multiplier in [('TEST A', 'Ready', 1), ('TEST B', 'Ready', 2),
                                             ('TEST A', 'Off-Plan', 3)]:
        for month in pd.period_range('2020-01', '2026-10', freq='M'):
            t = month.ordinal - pd.Period('2020-01', freq='M').ordinal
            rows.append(dict(area=area, registration_type=registration, property_type='Unit',
                unit_type='', month=str(month), transaction_count=multiplier * (30 + t // 3),
                median_price_per_m2_aed=multiplier * (8000 + t * 20)))
    return pd.DataFrame(rows)


def write_sources(root, frame=None):
    frame = synthetic_monthly() if frame is None else frame
    cfg = config()
    cfg.update(input=str(root / 'monthly.csv'), quality_report=str(root / 'quality.json'),
               context=str(root / 'optional-trends.csv'), output=str(root / 'forecasts.csv'),
               manifest=str(root / 'manifest.json'), report_dir=str(root / 'reports'), figures=False)
    frame.to_csv(cfg['input'], index=False)
    report = dict(date_min='2020-01-01', date_max='2026-10-27', coverage_note='Synthetic supplied records only',
                  monthly_sales_rows=len(frame), sales_transactions=int(frame.transaction_count.sum()),
                  inputs=[{'input_file': 'SYNTHETIC_TEST_ONLY', 'sha256': '0' * 64}])
    Path(cfg['quality_report']).write_text(json.dumps(report))
    return cfg


def panel_and_features(cfg=None, frame=None):
    cfg = config() if cfg is None else cfg
    with tempfile.TemporaryDirectory() as folder:
        source_cfg = write_sources(Path(folder), frame)
        # Keep callers' temporal and support settings.
        source_cfg.update({k: v for k, v in cfg.items() if k not in
                           ['input', 'quality_report', 'context', 'output', 'manifest', 'report_dir']})
        monthly, _, _ = load_inputs(source_cfg)
        panel = build_panel(monthly, source_cfg)
    return panel, {t: make_features(panel, t, cfg) for t in TARGETS}


class SourceTests(unittest.TestCase):
    def check_bad(self, mutate, message):
        with tempfile.TemporaryDirectory() as folder:
            cfg = write_sources(Path(folder))
            mutate(synthetic_monthly()).to_csv(cfg['input'], index=False)
            with self.assertRaisesRegex(ValueError, message):
                load_inputs(cfg)

    def test_required_schema(self):
        self.check_bad(lambda d: d.drop(columns='unit_type'), 'Missing source columns')

    def test_duplicate_key_including_missing_subtype(self):
        self.check_bad(lambda d: pd.concat([d, d.iloc[[0]]]), 'Duplicate composite')

    def test_duplicate_headers_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = write_sources(Path(folder))
            path = Path(cfg['input'])
            lines = path.read_text().splitlines()
            lines[0] = lines[0].replace('unit_type', 'area')
            path.write_text('\n'.join(lines) + '\n')
            with self.assertRaisesRegex(ValueError, 'Duplicate input headers'):
                load_inputs(cfg)

    def test_bad_month(self):
        def corrupt_one(d):
            d.loc[0, 'month'] = '2026-13'
            return d
        self.check_bad(corrupt_one, 'YYYY-MM')

    def test_bad_counts(self):
        for value in [-1, 1.5, np.inf, 'unknown']:
            with self.subTest(value=value):
                self.check_bad(lambda d: d.assign(transaction_count=value), 'nonnegative integers')

    def test_bad_price(self):
        for value in ['broken', np.inf]:
            with self.subTest(value=value):
                self.check_bad(lambda d: d.assign(median_price_per_m2_aed=value), 'price median')

    def test_missing_price_does_not_remove_counts(self):
        p, _ = panel_and_features(frame=synthetic_monthly().assign(median_price_per_m2_aed=np.nan))
        self.assertTrue(p[COUNT].notna().all())
        self.assertTrue(p[PRICE].isna().all())

    def test_missing_subtype_not_merged_with_literal(self):
        d = synthetic_monthly()
        extra = d.iloc[[0]].assign(unit_type='Unknown', transaction_count=10)
        with tempfile.TemporaryDirectory() as folder:
            cfg = write_sources(Path(folder), pd.concat([d, extra]))
            monthly, _, _ = load_inputs(cfg)
            self.assertTrue(monthly.unit_type.isna().any())
            self.assertIn('Unknown', monthly.unit_type.dropna().tolist())
            panel = build_panel(monthly, cfg)
            row = panel.loc[panel.area.eq('TEST A') & panel.registration_type.eq('Ready')].iloc[0]
            self.assertEqual(row[COUNT], 100)

    def test_quality_reconciliation(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = write_sources(Path(folder))
            p = Path(cfg['quality_report'])
            report = json.loads(p.read_text())
            report['sales_transactions'] += 1
            p.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'reconcile'):
                load_inputs(cfg)

    def test_quality_bounds_and_unfinished_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = write_sources(Path(folder))
            cfg.update(origin_quarter='2026Q4', forecast_quarter='2027Q1')
            with self.assertRaisesRegex(ValueError, 'calendar-complete'):
                load_inputs(cfg)

    def test_fingerprint_ignores_line_endings(self):
        with tempfile.TemporaryDirectory() as folder:
            unix, windows = Path(folder) / 'unix.csv', Path(folder) / 'windows.csv'
            unix.write_bytes(b'a,b\n1,2\n')
            windows.write_bytes(b'a,b\r\n1,2\r\n')
            self.assertEqual(fingerprint(unix), fingerprint(windows))

    def test_origin_behind_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = write_sources(Path(folder))
            cfg.update(origin_quarter='2026Q2', forecast_quarter='2026Q3', test_end='2026Q2')
            with self.assertRaisesRegex(ValueError, 'complete to 2026Q3'):
                load_inputs(cfg)

    def test_calendar_complete_is_not_coverage_claim(self):
        self.assertEqual(str(last_calendar_complete_quarter('2026-10-27')), '2026Q3')
        self.assertEqual(str(last_calendar_complete_quarter('2026-09-30')), '2026Q3')
        self.assertEqual(str(last_calendar_complete_quarter('2026-09-29')), '2026Q2')

    def test_config_rejects_horizon_splits_and_collisions(self):
        cases = [{'horizon_quarters': 4}, {'test_start': '2024Q4'},
                 {'output': config()['input']}, {'origin_quarter': '2026Q5'},
                 {'min_training_pairs': 0}, {'ridge_alphas': [0]},
                 {'property_types': ['Land']}, {'report_dir': 'reports/part2'}]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_config({**config(), **change})

    def test_empty_scoped_population(self):
        with self.assertRaisesRegex(ValueError, 'No Unit/Villa'):
            panel_and_features(frame=synthetic_monthly().assign(property_type='Land'))


class QuarterlyTests(unittest.TestCase):
    def test_exact_count_and_geometric_weight(self):
        d = synthetic_monthly()
        mask = d.area.eq('TEST A') & d.registration_type.eq('Ready') & d.month.lt('2020-04')
        d.loc[mask, 'transaction_count'] = [10, 20, 30]
        d.loc[mask, 'median_price_per_m2_aed'] = [100, 400, 1600]
        p, _ = panel_and_features(frame=d)
        row = p.loc[p.area.eq('TEST A') & p.registration_type.eq('Ready')].iloc[0]
        self.assertEqual(row[COUNT], 60)
        self.assertAlmostEqual(row[PRICE], np.exp((10*np.log(100)+20*np.log(400)+30*np.log(1600))/60))
        self.assertEqual(row.price_weight, 60)
        self.assertEqual(row.price_coverage, 1)

    def test_unknown_partial_and_observed_zero(self):
        d = synthetic_monthly()
        a = d.area.eq('TEST A') & d.registration_type.eq('Ready')
        d = d.loc[~(a & d.month.eq('2020-02'))].copy()
        d.loc[a.reindex(d.index) & d.month.between('2020-04', '2020-06'), 'transaction_count'] = 0
        p, _ = panel_and_features(frame=d)
        s = p.loc[p.area.eq('TEST A') & p.registration_type.eq('Ready')].set_index('quarter')
        self.assertTrue(pd.isna(s.loc[quarter('2020Q1'), COUNT]))
        self.assertEqual(s.loc[quarter('2020Q1'), 'observed_sales'], 60)
        self.assertEqual(s.loc[quarter('2020Q1'), 'month_coverage'], 2)
        self.assertEqual(s.loc[quarter('2020Q2'), COUNT], 0)
        self.assertTrue(pd.isna(s.loc[quarter('2020Q2'), PRICE]))

    def test_population_and_partial_october_excluded(self):
        d = synthetic_monthly()
        land = d.assign(property_type='Land', transaction_count=1000000)
        unknown_reg = d.loc[d.registration_type.eq('Ready')].assign(registration_type='Unspecified', transaction_count=1000000)
        p, _ = panel_and_features(frame=pd.concat([d, land, unknown_reg]))
        self.assertEqual(p.quarter.max(), quarter('2026Q3'))
        self.assertEqual(p.loc[p.area.eq('TEST A') & p.registration_type.eq('Ready'), COUNT].iloc[-1], 168)
        self.assertEqual(p.registration_type.nunique(), 2)

    def test_price_month_support_and_low_sales(self):
        d = synthetic_monthly()
        mask = d.area.eq('TEST A') & d.registration_type.eq('Ready')
        d.loc[mask & d.month.eq('2020-01'), 'median_price_per_m2_aed'] = 0
        d.loc[mask & d.month.between('2020-04', '2020-06'), 'transaction_count'] = 1
        p, _ = panel_and_features(frame=d)
        s = p.loc[p.area.eq('TEST A') & p.registration_type.eq('Ready')]
        self.assertTrue(pd.isna(s.iloc[0][PRICE]))
        self.assertAlmostEqual(s.iloc[0].price_coverage, 2/3)
        self.assertEqual(s.iloc[0][COUNT], 90)
        self.assertTrue(pd.isna(s.iloc[1][PRICE]))
        self.assertEqual(s.iloc[1][COUNT], 3)

    def test_count_weight_coverage_gate(self):
        d = synthetic_monthly()
        missing = d.assign(property_type='Villa', median_price_per_m2_aed=np.nan,
                           transaction_count=d.transaction_count * 3)
        p, _ = panel_and_features(frame=pd.concat([d, missing]))
        self.assertTrue(p.price_coverage.eq(.25).all())
        self.assertTrue(p[PRICE].isna().all())
        self.assertTrue(p[COUNT].notna().all())


class FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel, cls.tables = panel_and_features()

    def test_exact_seasonal_offset(self):
        s = self.tables[COUNT]
        row = s.loc[s.area.eq('TEST A') & s.registration_type.eq('Ready') & s.origin_quarter.eq(quarter('2021Q1'))].iloc[0]
        self.assertEqual(row.naive, 102)
        self.assertEqual(row.seasonal_naive, 93)  # 2020Q2, the match for target 2021Q2.
        self.assertEqual(row.actual, 105)
        self.assertAlmostEqual(row.seasonal, np.log1p(93))

    def test_lags_separate_area_and_registration(self):
        s = self.tables[COUNT]
        rows = s.loc[s.origin_quarter.eq(quarter('2021Q1'))].set_index(KEYS)
        self.assertEqual(rows.loc[('TEST A', 'Off-Plan'), 'naive'], 306)
        self.assertEqual(rows.loc[('TEST B', 'Ready'), 'seasonal_naive'], 186)

    def test_calendar_gap_does_not_shift_lags(self):
        p = self.panel.loc[~self.panel.quarter.eq(quarter('2020Q4'))]
        s = make_features(p, COUNT, config())
        rows = s.loc[s.origin_quarter.eq(quarter('2021Q1'))]
        self.assertTrue(rows.previous.isna().all())
        self.assertTrue(rows.seasonal_naive.notna().all())

    def test_later_outcomes_cannot_change_earlier_features(self):
        changed = self.panel.copy()
        changed.loc[changed.quarter.gt(quarter('2023Q4')), [COUNT, PRICE]] = 1e12
        for target in TARGETS:
            before = self.tables[target]
            after = make_features(changed, target, config())
            keep = before.origin_quarter.le(quarter('2023Q4'))
            assert_frame_equal(before.loc[keep, FEATURES + ['known_pairs']], after.loc[keep, FEATURES + ['known_pairs']])

    def test_actual_excluded_and_history_origin_only(self):
        self.assertNotIn('actual', FEATURES)
        self.assertNotIn(COUNT, FEATURES)
        self.assertNotIn(PRICE, FEATURES)
        first_validation = self.tables[COUNT].loc[self.tables[COUNT].origin_quarter.eq(quarter('2023Q4'))]
        self.assertTrue(first_validation.known_pairs.eq(12).all())

    def test_training_cutoff_and_dynamic_cohort(self):
        table = self.tables[COUNT]
        train = training_rows(table, quarter('2023Q4'), config())
        self.assertEqual(train.target_quarter.max(), quarter('2023Q4'))
        self.assertEqual(train.target_quarter.min(), quarter('2021Q1'))
        self.assertEqual(len(train), 36)
        self.assertTrue(origin_candidates(table, quarter('2022Q4'), config()).origin_reason.ne('').all())

    def test_truncated_history_matches_earlier_origin_fit(self):
        cfg = config()
        origin = quarter('2023Q4')
        for target in TARGETS:
            full = self.tables[target]
            truncated = make_features(self.panel.loc[self.panel.quarter.le(origin)], target, cfg)
            a, b = origin_candidates(full, origin, cfg), origin_candidates(truncated, origin, cfg)
            assert_frame_equal(a[FEATURES + ['known_pairs']].reset_index(drop=True),
                               b[FEATURES + ['known_pairs']].reset_index(drop=True))
            full_train = training_rows(full, origin, cfg)
            past_train = training_rows(truncated, origin, cfg)
            columns = FEATURES + ['actual', 'origin_quarter', 'target_quarter']
            assert_frame_equal(full_train[columns], past_train[columns])
            np.testing.assert_allclose(
                predict_ridge(fit_ridge(full_train, target, 1), a, target),
                predict_ridge(fit_ridge(past_train, target, 1), b, target), rtol=1e-12)

    def test_fallback_never_carries_stale_actual(self):
        cfg = config()
        panel = self.panel.copy()
        latest = panel.quarter.eq(quarter(cfg['origin_quarter']))
        panel.loc[latest, [COUNT, PRICE]] = np.nan
        panel.loc[latest, 'month_coverage'] = 0
        tables = {t: make_features(panel, t, cfg) for t in TARGETS}
        selected = {t: None for t in TARGETS}
        output = deployment(tables, selected, selected, cfg, 'synthetic-stale-check', '2026-10-27')
        self.assertTrue(output.history_quarters.ge(4).all())
        self.assertTrue(output.status.eq('missing_input').all())
        self.assertTrue(output.forecast_value.isna().all())

    def test_new_future_segment_not_eligible_in_past(self):
        p = self.panel.copy()
        extra = p.loc[p.area.eq('TEST B') & p.quarter.ge(quarter('2025Q1'))].assign(area='FUTURE TEST')
        features = make_features(pd.concat([p, extra]), COUNT, config())
        candidates = origin_candidates(features, quarter('2023Q4'), config())
        self.assertNotIn('FUTURE TEST', candidates.area.tolist())


class ModelEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel, cls.tables = panel_and_features()

    def test_train_only_pipeline_and_unseen_category(self):
        train = training_rows(self.tables[COUNT], quarter('2023Q4'), config())
        model = fit_ridge(train, COUNT, 1)
        preprocess = model.named_steps['preprocess']
        self.assertAlmostEqual(preprocess.named_transformers_['numeric'].named_steps['impute'].statistics_[0], train.level.median())
        scaler_before = preprocess.named_transformers_['numeric'].named_steps['scale'].mean_.copy()
        candidate = origin_candidates(self.tables[COUNT], quarter('2024Q1'), config()).copy()
        candidate['area'] = 'UNSEEN CATEGORY'
        candidate['level'] = 20.
        prediction = predict_ridge(model, candidate, COUNT)
        self.assertTrue(np.isfinite(prediction).all())
        np.testing.assert_array_equal(scaler_before, preprocess.named_transformers_['numeric'].named_steps['scale'].mean_)
        self.assertNotIn('UNSEEN CATEGORY', preprocess.named_transformers_['identity'].categories_[0])

    def test_valid_ridge_domains_and_empty_train(self):
        for target in TARGETS:
            train = training_rows(self.tables[target], quarter('2023Q4'), config())
            current = origin_candidates(self.tables[target], quarter('2023Q4'), config())
            predicted = predict_ridge(fit_ridge(train, target, .1), current, target)
            self.assertTrue(np.isfinite(predicted).all())
            self.assertTrue((predicted >= 0).all() if target == COUNT else (predicted > 0).all())
            self.assertIsNone(fit_ridge(train.iloc[:0], target, .1))

    def test_metrics_edge_cases(self):
        m = metrics([0, 10], [2, 8], True)
        self.assertEqual(m, dict(n=2, mae=2, rmse=2, wape=.4))
        self.assertIsNone(metrics([0], [1], True)['wape'])
        self.assertIsNone(metrics([], [], True)['mae'])
        self.assertIsNone(metrics([10], [12], False)['wape'])
        with self.assertRaises(ValueError):
            metrics([np.nan], [0])

    def test_common_rows_and_training_cutoffs(self):
        cfg = config()
        predicted, coverage = walk_forward(self.tables, '2024Q1', '2024Q4', 'validation', cfg, cfg['ridge_alphas'])
        for _, g in predicted.groupby(['target', 'forecast_quarter']):
            self.assertEqual(g.groupby('model_id').scored.sum().nunique(), 1)
            keys = [set(zip(s.area, s.registration_type)) for _, s in g.loc[g.scored].groupby('model_id')]
            self.assertTrue(all(k == keys[0] for k in keys))
        self.assertTrue((predicted.train_max_target_quarter <= predicted.origin_quarter).all())
        self.assertEqual(len(coverage), 8)
        with self.assertRaisesRegex(ValueError, 'validation rows only'):
            select_validation(predicted.assign(split='test'), cfg)

    def test_test_mutation_does_not_change_selection(self):
        cfg = config()
        validation, _ = walk_forward(self.tables, '2024Q1', '2024Q4', 'validation', cfg, cfg['ridge_alphas'])
        original = select_validation(validation, cfg)
        changed = self.panel.copy()
        changed.loc[changed.quarter.ge(quarter('2025Q1')), [COUNT, PRICE]] = 1e8
        tables = {t: make_features(changed, t, cfg) for t in TARGETS}
        validation2, _ = walk_forward(tables, '2024Q1', '2024Q4', 'validation', cfg, cfg['ridge_alphas'])
        self.assertEqual(select_validation(validation2, cfg), original)
        # Fit-dependent validation forecasts must also be invariant, not just the winner.
        assert_frame_equal(validation, validation2)

    def test_baseline_winner_is_selected_and_ties_are_stable(self):
        cfg = config()
        records = []
        for target in TARGETS:
            for model in [NAIVE, SEASONAL] + [ridge_id(a) for a in cfg['ridge_alphas']]:
                records.append(dict(split='validation', target=target, model_id=model,
                    forecast_quarter='2024Q1', scored=True, actual=100.,
                    prediction=100. if model in [NAIVE, SEASONAL] else 101.))
        methods, alphas = select_validation(pd.DataFrame(records), cfg)
        self.assertTrue(all(v == NAIVE for v in methods.values()))
        self.assertTrue(all(v == .1 for v in alphas.values()))

    def test_empty_valid_cohort_honest_metrics(self):
        cfg = {**config(), 'min_training_pairs': 1000}
        predictions, table, result = evaluate(self.tables, cfg)
        self.assertFalse(predictions.scored.any())
        self.assertTrue(table.n.eq(0).all())
        self.assertTrue(all(v is None for v in result['selected_methods'].values()))


class FallbackEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frame = synthetic_monthly()
        frame = frame.loc[~frame.area.eq('TEST B') | frame.month.ge('2022-01')]
        cls.panel, cls.tables = panel_and_features(frame=frame)
        cls.result = evaluate_fallbacks(cls.tables, config())

    def test_origin_cohort_and_independent_count_metrics(self):
        rows = pd.DataFrame(self.result['predictions'])
        self.assertEqual(set(rows.area), {'TEST B'})
        self.assertEqual(set(rows.registration_type), {'Ready'})
        self.assertTrue(rows.history_quarters.ge(4).all())
        summaries = pd.DataFrame(self.result['summaries'])
        count = summaries.loc[summaries.split.eq('validation') & summaries.target.eq(COUNT)
                              & summaries.forecast_quarter.eq('all')].iloc[0]
        # Four predictions each miss by six; the four actual counts sum to 1,140.
        self.assertEqual(count.n, 4)
        self.assertEqual(count.eligible_predictions, 4)
        self.assertEqual(count.excluded_predictions, 0)
        self.assertEqual(count.scored_segments, 1)
        self.assertEqual(count.scored_quarters, 4)
        self.assertEqual(count.mae, 6)
        self.assertEqual(count.rmse, 6)
        self.assertAlmostEqual(count.wape, 24 / 1140)
        test = rows.loc[rows.split.eq('test') & rows.target.eq(COUNT)]
        self.assertEqual(test.forecast_quarter.tolist(), ['2025Q1'])

    def test_same_fallback_membership_as_operational_policy(self):
        selected = {t: NAIVE for t in TARGETS}
        for forecast_quarter in ['2024Q1', '2024Q4', '2025Q1', '2025Q2']:
            origin = str(quarter(forecast_quarter) - 1)
            cfg = {**config(), 'origin_quarter': origin, 'forecast_quarter': forecast_quarter}
            out = deployment(self.tables, selected, selected, cfg, 'synthetic-policy-check', '2026-10-27')
            actual = {(r.area, r.registration_type, r.target): r.forecast_value
                      for r in out.loc[out.status.eq('fallback')].itertuples()}
            evaluated = {(r['area'], r['registration_type'], r['target']): r['prediction']
                         for r in self.result['predictions'] if r['forecast_quarter'] == forecast_quarter}
            self.assertEqual(actual, evaluated)

    def test_next_actual_support_is_checked_after_cohort_selection(self):
        panel = self.panel.copy()
        missing = panel.area.eq('TEST B') & panel.quarter.eq(quarter('2024Q1'))
        panel.loc[missing, [COUNT, PRICE]] = np.nan
        panel.loc[missing, 'month_coverage'] = 2
        tables = {t: make_features(panel, t, config()) for t in TARGETS}
        result = evaluate_fallbacks(tables, config())
        rows = [r for r in result['predictions'] if r['forecast_quarter'] == '2024Q1']
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not r['scored'] for r in rows))
        self.assertTrue(all(r['exclusion_reason'] == 'next_actual_unsupported' for r in rows))
        self.assertTrue(all(pd.notna(r['prediction']) for r in rows))
        self.assertFalse(any(r['forecast_quarter'] == '2024Q2' for r in result['predictions']))
        coverage = [r for r in result['per_origin'] if r['forecast_quarter'] == '2024Q2']
        self.assertTrue(all(r['unavailable_reasons']['origin_target_unsupported'] == 1 for r in coverage))

    def test_future_data_cannot_change_validation_fallbacks(self):
        panel = self.panel.copy()
        panel.loc[panel.quarter.ge(quarter('2025Q1')), [COUNT, PRICE]] = np.nan
        future = self.panel.loc[self.panel.area.eq('TEST B') & self.panel.quarter.ge(quarter('2025Q1'))].assign(area='FUTURE ONLY')
        tables = {t: make_features(pd.concat([panel, future]), t, config()) for t in TARGETS}
        changed = evaluate_fallbacks(tables, config())
        for key in ['predictions', 'per_origin', 'summaries']:
            before = pd.DataFrame([r for r in self.result[key] if r['split'] == 'validation'])
            after = pd.DataFrame([r for r in changed[key] if r['split'] == 'validation'])
            assert_frame_equal(before, after)

    def test_no_fallback_cohort_has_null_metrics(self):
        _, dense = panel_and_features()
        result = evaluate_fallbacks(dense, config())
        self.assertEqual(result['predictions'], [])
        self.assertTrue(all(r['n'] == 0 and r['mae'] is None and r['wape'] is None
                            for r in result['summaries']))
        self.assertEqual(result['high_error_examples'], [])

    def test_minimum_history_zero_activity_and_price_support(self):
        frame = synthetic_monthly()
        frame = frame.loc[~frame.area.eq('TEST B') | frame.month.ge('2023-01')].copy()
        zero = frame.area.eq('TEST B') & frame.month.between('2023-10', '2023-12')
        frame.loc[zero, 'transaction_count'] = 0
        _, tables = panel_and_features(frame=frame)
        result = evaluate_fallbacks(tables, config())
        rows = [r for r in result['predictions'] if r['forecast_quarter'] == '2024Q1']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['target'], COUNT)
        self.assertEqual(rows[0]['history_quarters'], 4)
        self.assertEqual(rows[0]['prediction'], 0)
        self.assertTrue(rows[0]['scored'])


class RangeTests(unittest.TestCase):
    def predictions(self, quarters, ratio):
        """Forecast 100 everywhere; the actual is 100 * ratio(quarter index, row)."""
        rows = [dict(split='validation' if q < '2025' else 'test', target=COUNT, model_id=NAIVE,
                     forecast_quarter=q, prediction=100.0, actual=100.0 * ratio(i, j), scored=True)
                for i, q in enumerate(quarters) for j in range(MIN_RANGE_ERRORS)]
        return pd.DataFrame(rows)

    def test_limits_are_error_quantiles_and_contain_zero(self):
        spread = lambda i, j: np.exp(np.linspace(-1, 1, MIN_RANGE_ERRORS)[j])
        result = forecast_ranges(self.predictions(['2024Q1', '2025Q1'], spread), {COUNT: NAIVE}, [], config())
        ok = result[COUNT]['ok']
        errors = np.log1p(100 * np.exp(np.linspace(-1, 1, MIN_RANGE_ERRORS))) - np.log1p(100)
        self.assertAlmostEqual(ok['low'], np.quantile(errors, 0.1))
        self.assertAlmostEqual(ok['high'], np.quantile(errors, 0.9))
        self.assertIsNone(result[COUNT]['fallback']['low'])     # no fallback errors, so no range
        biased = forecast_ranges(self.predictions(['2024Q1'], lambda i, j: 2.0), {COUNT: NAIVE}, [], config())
        self.assertEqual(biased[COUNT]['ok']['low'], 0.0)       # all errors positive: still contains the forecast

    def test_coverage_uses_only_earlier_quarters(self):
        # Errors are zero until the last quarter, where every actual doubles.
        jump = lambda i, j: 2.0 if i == 2 else 1.0
        result = forecast_ranges(self.predictions(['2024Q1', '2025Q1', '2025Q2'], jump), {COUNT: NAIVE}, [], config())
        ok = result[COUNT]['ok']
        # 2025Q1 is covered by the 2024 errors; 2025Q2's doubling is outside a range that never saw it.
        self.assertEqual(ok['test_forecasts'], 2 * MIN_RANGE_ERRORS)
        self.assertAlmostEqual(ok['test_coverage'], 0.5)

    def test_too_few_errors_give_no_range(self):
        few = self.predictions(['2024Q1'], lambda i, j: 1.1).iloc[:MIN_RANGE_ERRORS - 1]
        ok = forecast_ranges(few, {COUNT: NAIVE}, [], config())[COUNT]['ok']
        self.assertIsNone(ok['low'])
        self.assertIsNone(ok['test_coverage'])


class OutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        d = synthetic_monthly()
        # Dense count but no price: activity remains independently usable.
        d.loc[d.area.eq('TEST B'), 'median_price_per_m2_aed'] = np.nan
        # A recent segment has fallback support but lacks 12 training pairs.
        recent = synthetic_monthly().loc[lambda s: s.area.eq('TEST B') & s.month.ge('2025-10')].assign(area='SHORT TEST')
        brief = synthetic_monthly().loc[lambda s: s.area.eq('TEST B') & s.month.ge('2026-07')].assign(area='BRIEF TEST')
        cls.cfg = write_sources(cls.root, pd.concat([d, recent, brief]))
        cls.before = {p: fingerprint(p) for p in [cls.cfg['input'], cls.cfg['quality_report']]}
        cls.out, cls.evaluation, cls.manifest = run(cls.cfg)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_real_files_readable_without_training_import(self):
        # These are the same standard CSV/JSON operations a separate Part 4 process uses.
        import csv
        with open(self.cfg['output'], newline='') as f:
            rows = list(csv.DictReader(f))
        manifest = json.loads(Path(self.cfg['manifest']).read_text())
        self.assertEqual(len(rows), 10)
        self.assertEqual(manifest['forecast_quarter'], '2026Q4')
        unavailable = [r for r in rows if r['status'] in ['missing_input', 'insufficient_data']]
        self.assertTrue(unavailable)
        self.assertTrue(all(r['forecast_value'] == '' for r in unavailable))
        self.assertEqual(manifest['output_sha256'], fingerprint(self.cfg['output']))

    def test_isolated_consumer_process(self):
        script = '''import csv, json, sys
with open(sys.argv[1], newline='') as f:
    rows = list(csv.DictReader(f))
with open(sys.argv[2]) as f:
    manifest = json.load(f)
assert len(rows) == manifest['output_rows']
assert all(r['run_id'] == manifest['run_id'] for r in rows)
assert all(r['forecast_value'] == '' for r in rows if r['status'] in ('missing_input', 'insufficient_data'))
assert 'src.forecasting' not in sys.modules
'''
        subprocess.run([sys.executable, '-I', '-c', script, self.cfg['output'], self.cfg['manifest']],
                       cwd=self.root, check=True, capture_output=True, text=True)

    def test_uniqueness_units_and_status_contract(self):
        validate_output(self.out, self.manifest)
        self.assertFalse(self.out.duplicated(OUTPUT_KEY).any())
        self.assertTrue(self.out.provisional_input.all())
        self.assertEqual(set(self.out.target), set(TARGETS))
        short = self.out.loc[self.out.area.eq('SHORT TEST')]
        self.assertTrue(short.status.eq('fallback').all())
        self.assertTrue(short.model_id.eq(NAIVE).all())
        brief = self.out.loc[self.out.area.eq('BRIEF TEST')]
        self.assertTrue(brief.status.eq('insufficient_data').all())
        self.assertTrue(brief.forecast_value.isna().all())

    def test_ranges_contain_the_forecast_and_stay_blank_when_unavailable(self):
        ranged = self.out.loc[self.out.range_low.notna()]
        self.assertTrue((ranged.range_low <= ranged.forecast_value).all())
        self.assertTrue((ranged.forecast_value <= ranged.range_high).all())
        unavailable = self.out.loc[~self.out.status.isin(['ok', 'fallback'])]
        self.assertTrue(unavailable[['range_low', 'range_high']].isna().all().all())
        bad = self.out.copy()
        row = bad.index[bad.status.eq('ok')][0]
        bad.loc[row, ['range_low', 'range_high']] = bad.loc[row, 'forecast_value'] + 1, bad.loc[row, 'forecast_value'] + 2
        with self.assertRaisesRegex(ValueError, 'contain its forecast'):
            validate_output(bad, self.manifest)

    def test_count_available_when_price_missing(self):
        area = self.out.loc[self.out.area.eq('TEST B')].set_index('target')
        self.assertIn(area.loc[COUNT, 'status'], ['ok', 'fallback'])
        self.assertEqual(area.loc[PRICE, 'status'], 'missing_input')
        self.assertTrue(pd.isna(area.loc[PRICE, 'forecast_value']))

    def test_bad_output_zero_and_duplicate_rejected(self):
        bad = self.out.copy()
        bad.loc[bad.status.eq('missing_input'), 'forecast_value'] = 0
        with self.assertRaisesRegex(ValueError, 'blank/null'):
            validate_output(bad, self.manifest)
        with self.assertRaisesRegex(ValueError, 'duplicate forecast key'):
            validate_output(pd.concat([self.out, self.out.iloc[[0]]]), self.manifest)

    def test_reproducibility_and_unchanged_upstream(self):
        output, evaluation, manifest = run(copy.deepcopy(self.cfg))
        assert_frame_equal(output, self.out)
        self.assertEqual(manifest['run_id'], self.manifest['run_id'])
        self.assertEqual(manifest['selected_methods'], self.manifest['selected_methods'])
        self.assertEqual(manifest['output_sha256'], self.manifest['output_sha256'])
        for p, expected in self.before.items():
            self.assertEqual(fingerprint(p), expected)

    def test_required_evaluation_artifacts(self):
        for file in ['predictions.csv', 'metrics.csv', 'evaluation.json', 'run_config.json', 'data_profile.json']:
            self.assertGreater((self.root / 'reports' / file).stat().st_size, 0)
        for file in ['evaluation.json', 'run_config.json', 'data_profile.json']:
            json.loads((self.root / 'reports' / file).read_text(), parse_constant=lambda x: self.fail(f'Non-JSON number: {x}'))

    def test_fallback_and_fractional_limitations_exported(self):
        self.assertTrue(any('historical sample-limited errors do not guarantee accuracy' in warning
                            for warning in self.manifest['warnings']))
        self.assertTrue(any('not literal fractional transactions' in warning
                            for warning in self.manifest['warnings']))
        self.assertTrue(any('historical sample-limited errors do not guarantee accuracy' in warning
                            for warning in self.evaluation['warnings']))
        self.assertIn('fallback_evaluation', self.evaluation)
        self.assertEqual(self.manifest['fallback_evaluation']['section'], 'fallback_evaluation')
        self.assertTrue(all(r['cohort'] == 'fallback'
                            for r in self.manifest['fallback_evaluation']['summaries']))


if __name__ == '__main__':
    unittest.main()
