"""Validate the prepared source and retain missingness before building quarterly targets."""
import csv
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

KEYS = ['area', 'registration_type']
CELL_KEY = ['area', 'property_type', 'unit_type', 'registration_type', 'month']
COUNT = 'sales_count'
PRICE = 'weighted_geomean_monthly_median_aed_m2'
TARGETS = {COUNT: 'sales_per_quarter', PRICE: 'AED_per_m2'}
REQUIRED = CELL_KEY + ['transaction_count', 'median_price_per_m2_aed']
WARNINGS = [
    'Only supplied records; completeness is not established. Three observed months is a support rule, not proof of full coverage.',
    'Missing rows are unknown, never inferred zero. Unobserved property/subtype cells may remain within observed segment months.',
    'Price is a count-weighted geometric mean of positive monthly medians, not a pooled quarterly median or mix-adjusted index.',
    'Price weight coverage is a support proxy, not transaction-level valid-price coverage.',
    'Unit/Villa can include commercial units. No procedure filter is available.',
    'Pseudo-real-time backtests use today\'s revised snapshot, not historical release vintages.',
    'Inverse log predictions are not automatically unbiased arithmetic means. No prediction intervals are estimated.',
    'Fallback history/input policy is evaluated separately; historical sample-limited errors do not guarantee accuracy for every segment or future quarter. Numerical model-failure fallbacks are not evaluated.',
    'Fractional sales_count values are continuous numerical forecasts of activity, not literal fractional transactions; CSV precision is retained.',
    '2026Q4 is a Q3-based projection generated during Q4, excluding October observations.',
    'Recorded sales activity is not buyer enquiries, agent demand, profit or a guarantee.'
]


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quarter(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}Q[1-4]', value):
        raise ValueError(f'Expected YYYYQn quarter, got {value!r}')
    return pd.Period(value, freq='Q')


def validate_config(cfg):
    names = ['panel_start', 'train_start', 'validation_start', 'validation_end',
             'test_start', 'test_end', 'origin_quarter', 'forecast_quarter']
    q = {k: quarter(cfg[k]) for k in names}
    if not (q['panel_start'] < q['train_start'] < q['validation_start'] <= q['validation_end']
            < q['test_start'] <= q['test_end'] <= q['origin_quarter']):
        raise ValueError('Training, validation and test periods must be chronological and disjoint')
    if cfg['horizon_quarters'] != 1 or q['forecast_quarter'] != q['origin_quarter'] + 1:
        raise ValueError('Only exactly one quarter ahead is supported')
    if cfg['property_types'] != ['Unit', 'Villa'] or set(cfg['registration_types']) != {'Ready', 'Off-Plan'}:
        raise ValueError('Supported population is Unit|Villa and separate Ready/Off-Plan')
    for name in ['min_training_pairs', 'min_fallback_quarters', 'provisional_quarters']:
        if type(cfg[name]) is not int or cfg[name] < 1:
            raise ValueError(f'{name} must be a positive integer')
    if not 0 < cfg['min_price_coverage'] <= 1 or cfg['min_price_sales'] < 1:
        raise ValueError('Invalid price support thresholds')
    if not cfg['ridge_alphas'] or any(not np.isfinite(a) or a <= 0 for a in cfg['ridge_alphas']):
        raise ValueError('Ridge alphas must be finite and positive')
    inputs = {Path(cfg[k]).resolve() for k in ['input', 'quality_report', 'context'] if cfg.get(k)}
    outputs = [Path(cfg[k]).resolve() for k in ['output', 'manifest']]
    report = Path(cfg['report_dir']).resolve()
    artifacts = ['predictions.csv', 'metrics.csv', 'evaluation.json', 'run_config.json',
                 'data_profile.json', 'actual_vs_forecast.png', 'baseline_comparison.png']
    outputs += [report / a for a in artifacts]
    if len(set(outputs)) != len(outputs) or inputs.intersection(outputs):
        raise ValueError('Output paths must be distinct and must not overwrite inputs')
    # A misconfigured report directory must not replace another member's report.
    if report == Path('reports/part2').resolve():
        raise ValueError('Part 2 reports are read-only inputs/context')


def last_calendar_complete_quarter(date_max):
    date = pd.Timestamp(date_max)
    q = date.to_period('Q')
    return q if date.normalize() >= q.end_time.normalize() else q - 1


def load_inputs(cfg):
    """Validate before filtering; preserve literal labels and explicitly missing subtypes."""
    path = Path(cfg['input'])
    with path.open(newline='', encoding='utf-8-sig') as f:
        headers = next(csv.reader(f), [])
    if len(headers) != len(set(headers)):
        raise ValueError('Duplicate input headers')
    df = pd.read_csv(path, keep_default_na=False)
    missing = set(REQUIRED) - set(df)
    if missing:
        raise ValueError(f'Missing source columns: {sorted(missing)}')
    if df.empty:
        raise ValueError('Monthly source contains no rows')
    for name in ['area', 'property_type', 'registration_type', 'month']:
        if not df[name].map(lambda s: isinstance(s, str) and bool(s.strip())).all():
            raise ValueError(f'Missing or invalid {name}')
    # Do not coalesce a missing subtype with a source literal such as "Unknown".
    df['unit_type'] = df.unit_type.replace('', pd.NA)
    if df.duplicated(CELL_KEY).any():
        raise ValueError('Duplicate composite monthly key, including missing subtype')
    if not df.month.str.fullmatch(r'\d{4}-(0[1-9]|1[0-2])').all():
        raise ValueError('month must be YYYY-MM')
    df['month'] = pd.PeriodIndex(df.month, freq='M')
    counts = pd.to_numeric(df.transaction_count, errors='coerce')
    if (counts.isna() | ~np.isfinite(counts) | counts.lt(0) | counts.mod(1).ne(0)).any():
        raise ValueError('transaction_count must be finite nonnegative integers')
    df['transaction_count'] = counts.astype('int64')
    price = df.median_price_per_m2_aed.replace('', np.nan)
    parsed = pd.to_numeric(price, errors='coerce')
    if (price.notna() & (parsed.isna() | ~np.isfinite(parsed))).any():
        raise ValueError('Malformed or nonfinite price median')
    # Zero/negative numeric medians are unsupported price inputs, not count failures.
    df['median_price_per_m2_aed'] = parsed
    report = json.loads(Path(cfg['quality_report']).read_text())
    for key in ['date_min', 'date_max', 'coverage_note', 'monthly_sales_rows', 'sales_transactions', 'inputs']:
        if key not in report:
            raise ValueError(f'Quality report missing {key}')
    try:
        lower, upper = pd.Timestamp(report['date_min']), pd.Timestamp(report['date_max'])
        if pd.isna(lower) or pd.isna(upper) or lower > upper:
            raise ValueError('invalid bounds')
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid quality report date bounds') from exc
    if df.month.min() < lower.to_period('M') or df.month.max() > upper.to_period('M'):
        raise ValueError('Monthly dates conflict with quality report bounds')
    if len(df) != report['monthly_sales_rows'] or int(counts.sum()) != report['sales_transactions']:
        raise ValueError('Monthly rows/counts do not reconcile with quality report')
    origin = quarter(cfg['origin_quarter'])
    if origin > last_calendar_complete_quarter(upper):
        raise ValueError('Requested origin is not calendar-complete in source')
    hashes = {cfg[k]: fingerprint(cfg[k]) for k in ['input', 'quality_report']}
    if cfg.get('context') and Path(cfg['context']).exists():
        hashes[cfg['context']] = fingerprint(cfg['context'])
    profile = {'source_rows': len(df), 'source_hashes': hashes,
               'audit_hash_match': {Path(p).name: h == AUDIT_HASHES.get(Path(p).name)
                                    for p, h in hashes.items()},
               'missing_subtype_rows': int(df.unit_type.isna().sum()),
               'nonpositive_price_rows': int(parsed.le(0).sum()),
               'missing_price_rows': int(parsed.isna().sum()), 'quality_report': report}
    profile['source_evidence'] = {
        'verified_aggregate_rows': len(df), 'verified_aggregate_sales_sum': int(counts.sum()),
        'observed_sales_month_min': str(df.month.min()), 'observed_sales_month_max': str(df.month.max()),
        'reported_clean_record_date_min': report['date_min'],
        'reported_clean_record_date_max': report['date_max'],
        'reported_prepared_at_utc': report.get('prepared_at_utc'),
        'raw_provenance': 'Source filenames, hashes and catalogue references are upstream reports; Part 3 has not independently rehashed or authenticated the raw exports.',
        'extraction_scope': 'Observed dates are not proof of the requested export period, query filters, or complete retrieval of all parts.',
        'market_completeness': 'Not established. Aggregate reconciliation and observed months do not prove complete market coverage.',
        'field_limits': 'Monthly cells retain counts, medians and subtypes but omit transaction IDs, procedure and transaction-level valid-price denominators.',
        'evidence_needed': [
            'Recorded export query dates, filters and source version or revision timestamp.',
            'An authenticated export manifest listing every part or page, its row count and hash.',
            'Reconciliation of the complete raw export and documented exclusions to authoritative totals for the same scope.',
            'Upstream confirmation of missing-month semantics; archived release vintages for true real-time backtesting.'
        ]}
    scope = df.property_type.isin(cfg['property_types']) & df.registration_type.isin(cfg['registration_types'])
    df['quarter'] = df.month.dt.asfreq('Q')
    keep = scope & df.quarter.between(quarter(cfg['panel_start']), origin)
    profile.update({'out_of_population_rows': int((~scope).sum()),
                    'excluded_after_origin_rows': int((scope & df.quarter.gt(origin)).sum()),
                    'excluded_before_panel_rows': int((scope & df.quarter.lt(quarter(cfg['panel_start']))).sum()),
                    'selected_rows': int(keep.sum())})
    return df.loc[keep].copy(), report, profile


AUDIT_HASHES = {
    'monthly_sales.csv': '14e525c3212daad62f40c21ccc874ae501699126f21e8df31305497bccadea38',
    'quality_report.json': '604cdc2df1b057d56c557ccb25555168fb7218beacbc680cf7c71b03c77de921',
    'market_trends.csv': 'ae1253c6fa9b5951a6d26ab3b2209580bfe7dc6a2db10c7a8f3273e891fe3924'}


def build_panel(monthly, cfg):
    """A complete calendar, with exact supplied sums retained even for partial quarters.

    A usable count needs records in all three segment months. This rule concerns the
    supplied population only; it cannot certify missing property/subtype cells.
    """
    if monthly.empty:
        raise ValueError('No Unit/Villa rows within the configured historical window')
    gkeys = KEYS + ['quarter']
    grouped = monthly.groupby(gkeys, sort=True)
    out = grouped.agg(observed_sales=('transaction_count', 'sum'),
                      month_coverage=('month', 'nunique'))
    priced = monthly.loc[monthly.median_price_per_m2_aed.gt(0) & monthly.transaction_count.gt(0)].copy()
    priced['weighted_log'] = np.log(priced.median_price_per_m2_aed) * priced.transaction_count
    support = priced.groupby(gkeys).agg(price_weight=('transaction_count', 'sum'),
        weighted_log=('weighted_log', 'sum'), price_months=('month', 'nunique'))
    out = out.join(support)
    out['price_weight'] = out.price_weight.fillna(0)
    out['price_months'] = out.price_months.fillna(0)
    out['price_coverage'] = out.price_weight / out.observed_sales.replace(0, np.nan)
    out['price_proxy_observed'] = np.exp(out.weighted_log / out.price_weight.replace(0, np.nan))
    out[COUNT] = out.observed_sales.where(out.month_coverage.eq(3))
    price_ok = (out.month_coverage.eq(3) & out.price_months.eq(3)
                & out.observed_sales.ge(cfg['min_price_sales'])
                & out.price_coverage.ge(cfg['min_price_coverage']))
    out[PRICE] = out.price_proxy_observed.where(price_ok)
    segments = monthly[KEYS].drop_duplicates().sort_values(KEYS)
    calendar = pd.period_range(cfg['panel_start'], cfg['origin_quarter'], freq='Q')
    grid = pd.MultiIndex.from_tuples([(*s, q) for s in segments.itertuples(index=False, name=None)
                                     for q in calendar], names=gkeys)
    out = out.reindex(grid).drop(columns='weighted_log')
    out['month_coverage'] = out.month_coverage.fillna(0).astype(int)
    out['price_months'] = out.price_months.fillna(0).astype(int)
    out['seen'] = out.observed_sales.notna().groupby(level=KEYS).cumsum().gt(0)
    out['provisional'] = out.index.get_level_values('quarter') > quarter(cfg['origin_quarter']) - cfg['provisional_quarters']
    return out.reset_index()
