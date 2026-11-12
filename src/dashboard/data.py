"""Read a coherent set of shared outputs without changing source files."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.forecasting.data import fingerprint
from src.forecasting.run import validate_output
from src.trend_analysis.fuzzy import fired_rules, ramp, three_sets

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / 'data/shared'
FILES = ['monthly_sales.csv', 'quality_report.json', 'market_trends.csv',
         'forecasts.csv', 'forecast_manifest.json', 'allocation.csv', 'allocation_manifest.json']
REPORTS = ['part2/evaluation.json', 'part2/forward_check.csv', 'part3/metrics.csv', 'part3/predictions.csv',
           'part4/evaluation.json', 'part4/backtest_summary.csv']
SALES, PRICE = 'sales_count', 'weighted_geomean_monthly_median_aed_m2'
STATUS = {'ok': 'Model forecast', 'fallback': 'Last quarter repeated (short history)',
          'insufficient_data': 'Not enough history', 'missing_input': 'No recent data'}


def source_signature():
    """Invalidate the UI cache and custom plans whenever an upstream file changes."""
    paths = [SHARED / name for name in FILES] + [ROOT / 'reports' / name for name in REPORTS]
    return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in paths)


def load_bundle():
    """Validate source fingerprints before exposing forecasts or recommendations."""
    before = source_signature()
    quality = json.loads((SHARED / 'quality_report.json').read_text())
    forecast_manifest = json.loads((SHARED / 'forecast_manifest.json').read_text())
    allocation_manifest = json.loads((SHARED / 'allocation_manifest.json').read_text())
    for manifest in [forecast_manifest, allocation_manifest]:
        for name, expected in manifest['source_hashes'].items():
            path = ROOT / name
            if fingerprint(path) != expected:
                raise ValueError(f'{Path(name).name} differs from the saved analysis. Refresh Parts 2–4 together.')
    for name, manifest in [('forecasts.csv', forecast_manifest), ('allocation.csv', allocation_manifest)]:
        if fingerprint(SHARED / name) != manifest['output_sha256']:
            raise ValueError(f'{name} does not match its manifest. Regenerate its outputs.')
    if allocation_manifest['forecast_run_id'] != forecast_manifest['run_id']:
        raise ValueError('The allocation and forecasts belong to different runs.')
    monthly = pd.read_csv(SHARED / 'monthly_sales.csv')
    if len(monthly) != quality['monthly_sales_rows'] or int(monthly.transaction_count.sum()) != quality['sales_transactions']:
        raise ValueError('Monthly sales do not reconcile with the quality report.')
    forecasts = pd.read_csv(SHARED / 'forecasts.csv', dtype={'schema_version': str})
    validate_output(forecasts, forecast_manifest)
    monthly['date'] = pd.to_datetime(monthly.month + '-01')
    trends = pd.read_csv(SHARED / 'market_trends.csv')
    allocation = pd.read_csv(SHARED / 'allocation.csv', dtype={'schema_version': str})
    if before != source_signature():
        raise ValueError('Source files changed while reading. Wait for the update to finish and refresh.')
    return dict(monthly=monthly, quality=quality, forecasts=forecasts,
                forecast_manifest=forecast_manifest, allocation_manifest=allocation_manifest,
                trends=trends, allocation=allocation)


def filter_rows(frame, area='All areas', registration='Both'):
    """Apply the same segment identity to each view; empty results remain empty."""
    selected = frame
    if area != 'All areas':
        selected = selected[selected.area.eq(area)]
    if registration != 'Both':
        selected = selected[selected.registration_type.eq(registration)]
    return selected.copy()


def monthly_summary(frame):
    """Sum counts and consideration; do not present averages of medians as medians."""
    return frame.groupby('date')[['transaction_count', 'total_price_aed']].sum().rename(
        columns={'transaction_count': 'Sales', 'total_price_aed': 'Transaction value (AED)'})


def load_evidence():
    """Evaluation results the parts already wrote; shown as they are, never recomputed here."""
    reports = ROOT / 'reports'
    read = lambda name: json.loads((reports / name).read_text())
    return dict(trends=read('part2/evaluation.json'), forward=pd.read_csv(reports / 'part2/forward_check.csv'),
                metrics=pd.read_csv(reports / 'part3/metrics.csv'), allocation=read('part4/evaluation.json'),
                backtest=pd.read_csv(reports / 'part4/backtest_summary.csv'))


def method_name(model_id):
    """Part 3's model ids in plain words."""
    if model_id.startswith('ridge'):
        return 'Ridge regression'
    return {'naive_v1': 'Last quarter repeated', 'seasonal_naive_v1': 'Same quarter last year'}.get(model_id, '—')


def quarter_name(code):
    """'2026Q3' -> 'Jul–Sep 2026': people think in months, not quarter codes."""
    quarter = pd.Period(code, freq='Q')
    return f'{quarter.start_time:%b}–{quarter.end_time:%b} {quarter.year}'


def quarter_progress(monthly, forecasts, forecast_quarter, date_max):
    """Sales already recorded in the forecast quarter, per segment, and the share of its days observed.

    The forecast quarter can already be running when the data was exported. Returns (None, 0.0)
    when the data stops before it starts.
    """
    quarter = pd.Period(forecast_quarter, freq='Q')
    seen = (min(pd.Timestamp(date_max), quarter.end_time).normalize() - quarter.start_time).days + 1
    if seen <= 0:
        return None, 0.0
    scope = forecasts.property_scope.iloc[0].split('|')
    rows = monthly[monthly.property_type.isin(scope) & (pd.PeriodIndex(monthly.month, freq='Q') == quarter)]
    so_far = rows.groupby(['area', 'registration_type']).transaction_count.sum().rename('sales_so_far')
    return so_far.reset_index(), seen / ((quarter.end_time.normalize() - quarter.start_time).days + 1)


def range_text(low, high):
    """'330 – 860', or blank when Part 3 gave no range."""
    return '' if pd.isna(low) or pd.isna(high) else f'{float(low):,.0f} – {float(high):,.0f}'


def forecast_table(forecasts, so_far=None, share=0.0):
    """One row per segment: the forecast quarter's sales and price beside the last complete quarter.

    With `so_far` (from quarter_progress) it adds the sales already recorded, the full-quarter total
    at that pace, and whether that total is inside the forecast's likely range.
    """
    wide = forecasts.pivot(index=['area', 'registration_type'], columns='target',
                           values=['forecast_value', 'last_actual', 'status', 'range_low', 'range_high']).reset_index()
    out = wide[['area', 'registration_type']].droplevel(1, axis=1)
    for name, target in [('sales', SALES), ('price', PRICE)]:
        forecast = pd.to_numeric(wide[('forecast_value', target)])
        last = pd.to_numeric(wide[('last_actual', target)])
        out[f'{name}_forecast'], out[f'{name}_last'] = forecast, last
        out[f'{name}_change_pct'] = (forecast / last.where(last > 0) - 1) * 100
        out[f'{name}_range'] = [range_text(low, high) for low, high in
                                zip(wide[('range_low', target)], wide[('range_high', target)])]
    out['status'] = wide[('status', SALES)].map(STATUS)
    if so_far is not None:
        out = out.merge(so_far, on=['area', 'registration_type'], how='left')
        out['sales_pace'] = out.sales_so_far / share
        low, high = wide[('range_low', SALES)].astype(float), wide[('range_high', SALES)].astype(float)
        out['pace_note'] = np.select([out.sales_pace.isna() | low.isna(), out.sales_pace < low, out.sales_pace > high],
                                     ['', 'Below the range', 'Above the range'], 'Inside the range')
    return out.sort_values('sales_forecast', ascending=False, na_position='last').reset_index(drop=True)


def explain_trend(row, scales):
    """Replay Part 2's fuzzy rules for one segment so the label can be shown step by step.

    market_trends.csv stores rounded percentage changes; the rules use log changes, so the
    degrees here can differ from the stored ones in the third decimal.
    """
    frame = pd.DataFrame({'log_price_change': [np.log1p(row.price_change_yoy)],
                          'log_volume_change': [np.log1p(row.volume_change_yoy)],
                          'volatility': [row.volatility]})
    sets = {}
    for name, column, scale in [('Price', 'log_price_change', 'price'),
                                ('Sales volume', 'log_volume_change', 'volume')]:
        down, flat, up = three_sets(frame[column], *scales[scale])
        sets[name] = {'Falling': float(down[0]), 'Flat': float(flat[0]), 'Rising': float(up[0])}
    high = float(np.nan_to_num(ramp(frame.volatility, *scales['volatility']))[0])
    sets['Volatility'] = {'Low': 1 - high, 'High': high}
    rules = pd.DataFrame([{'Rule': meaning, 'Says': label, 'Weight': weight, 'Strength': float(weight * fire[0])}
                          for label, weight, meaning, fire in fired_rules(frame, scales)])
    degrees = rules.groupby('Says').Strength.max().to_dict()
    return sets, rules.sort_values('Strength', ascending=False).reset_index(drop=True), degrees
