"""Load the outputs of Parts 1-3 and turn them into candidate segments for one quarter."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

KEYS = ['area', 'registration_type']
ACTIVITY = 'sales_count'
PRICE = 'weighted_geomean_monthly_median_aed_m2'
USABLE = {'ok', 'fallback'}
SCHEMA_VERSION = '1.0'


def sha256(path):
    """Hash ignoring line endings: Git on Windows checks these files out with CRLF."""
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def load_inputs(cfg):
    """Read the shared files. Refuses a forecast file that does not match its manifest."""
    manifest = json.loads(Path(cfg['forecast_manifest']).read_text())
    if manifest['schema_version'] != SCHEMA_VERSION:
        raise ValueError(f"Unsupported forecast schema {manifest['schema_version']}")
    if sha256(cfg['forecasts']) != manifest['output_sha256']:
        raise ValueError('forecasts.csv does not match forecast_manifest.json')
    forecasts = pd.read_csv(cfg['forecasts'], dtype={'schema_version': str})
    monthly = pd.read_csv(cfg['monthly_sales'])
    monthly = monthly[monthly.property_type.isin(cfg['property_types'])
                      & monthly.registration_type.isin(cfg['commission_rate'])]
    predictions = pd.read_csv(cfg['predictions'])
    if set(predictions.run_id) != {manifest['run_id']}:
        raise ValueError('predictions.csv is not from the same Part 3 run as forecasts.csv; rerun Part 3')
    trends = pd.read_csv(cfg['market_trends'])
    if not trends.quarter.eq(manifest['origin_quarter']).any():
        raise ValueError(f"market_trends.csv has no rows for {manifest['origin_quarter']}; rerun Part 2")
    return {'forecasts': forecasts, 'manifest': manifest, 'quarterly': quarterly(monthly),
            'trends': trends, 'predictions': predictions,
            'errors': forecast_errors(predictions, manifest['selected_methods'][ACTIVITY])}


def quarterly(monthly):
    """Recorded sales per segment and quarter. total_price sums monthly medians times counts, not
    real totals, so that a single AED 500M sale cannot set what a typical deal in the segment is worth."""
    quarters = pd.PeriodIndex(monthly.month, freq='M').asfreq('Q').astype(str)
    frame = monthly.assign(quarter=quarters, total_price=monthly.transaction_count * monthly.median_price_aed)
    return frame.groupby(KEYS + ['quarter'], as_index=False).agg(
        sales=('transaction_count', 'sum'), total_price=('total_price', 'sum'))


def forecast_errors(predictions, model_id):
    """Log errors of the selected activity model, with the quarter they became known."""
    rows = predictions[predictions.target.eq(ACTIVITY) & predictions.model_id.eq(model_id)
                       & predictions.scored.astype(bool)].dropna(subset=['actual', 'prediction'])
    return rows.assign(log_error=np.log1p(rows.actual) - np.log1p(rows.prediction))[
        ['split', 'forecast_quarter', 'prediction', 'log_error']].reset_index(drop=True)


def known_errors(errors, target_quarter):
    """Errors allowed when deciding for target_quarter, so no outcome leaks into its own plan.

    2024 has no earlier errors, so validation quarters use the other 2024 quarters. Test and
    live quarters use only errors of quarters already finished.
    """
    if target_quarter in set(errors.forecast_quarter[errors.split.eq('validation')]):
        return errors[errors.split.eq('validation') & errors.forecast_quarter.ne(target_quarter)]
    return errors[errors.forecast_quarter < target_quarter]


def trailing_tickets(table, origin, window):
    """Typical sale value over the last `window` quarters up to and including the origin."""
    quarters = [str(p) for p in pd.period_range(end=pd.Period(origin, freq='Q'), periods=window)]
    recent = table[table.quarter.isin(quarters)].groupby(KEYS, as_index=False)[['sales', 'total_price']].sum()
    recent = recent[recent.sales > 0]
    return recent.assign(ticket=recent.total_price / recent.sales)[KEYS + ['ticket']]


def finish_candidates(frame, inputs, origin, cfg):
    """Add what one deal is worth, and the trend at the origin. Drops segments with no recent sale."""
    tickets = trailing_tickets(inputs['quarterly'], origin, cfg['ticket_window_quarters'])
    trends = inputs['trends'][inputs['trends'].quarter.eq(origin)]
    out = frame.merge(tickets, on=KEYS).merge(
        trends[KEYS + ['trend_label', 'trend_score']], on=KEYS, how='left')
    low, high = cfg['price_ratio_clip']
    out['ticket'] = out.ticket * out.price_ratio.clip(low, high)
    out['rate'] = out.registration_type.map(cfg['commission_rate'])
    out['trend_label'] = out.trend_label.fillna('Insufficient data')
    return out.sort_values(KEYS).reset_index(drop=True)


def deployment_candidates(inputs, cfg):
    """Segments with a usable activity forecast. Blank forecasts stay out, never become zero."""
    fc = inputs['forecasts']
    activity = fc[fc.target.eq(ACTIVITY) & fc.status.isin(USABLE)
                  & fc.forecast_value.ge(cfg['min_forecast_sales'])]
    frame = activity.rename(columns={'forecast_value': 'demand', 'last_actual': 'last_sales'})[
        KEYS + ['demand', 'last_sales', 'status']]
    price = fc[fc.target.eq(PRICE) & fc.status.isin(USABLE)].rename(columns={'status': 'price_status'})
    price = price.assign(price_ratio=price.forecast_value / price.last_actual)
    frame = frame.merge(price[KEYS + ['price_ratio', 'price_status']], on=KEYS, how='left')
    frame['price_ratio'] = frame.price_ratio.fillna(1.0)
    frame['price_status'] = frame.price_status.fillna('unavailable')
    return finish_candidates(frame, inputs, inputs['manifest']['origin_quarter'], cfg)


def backtest_candidates(inputs, origin, cfg):
    """The same candidates as of a past origin, with what really happened the next quarter."""
    pred = inputs['predictions']
    selected = inputs['manifest']['selected_methods']
    target_quarter = str(pd.Period(origin, freq='Q') + 1)

    def column(target, model_id, name):
        rows = pred[pred.target.eq(target) & pred.model_id.eq(model_id) & pred.origin_quarter.eq(origin)]
        return rows.dropna(subset=['prediction']).rename(columns={'prediction': name})[KEYS + [name]]

    frame = column(ACTIVITY, selected[ACTIVITY], 'demand')
    frame = frame[frame.demand >= cfg['min_forecast_sales']].merge(column(ACTIVITY, 'naive_v1', 'last_sales'), on=KEYS, how='left')
    price = column(PRICE, selected[PRICE], 'price').merge(column(PRICE, 'naive_v1', 'last_price'), on=KEYS)
    frame = frame.merge(price.assign(price_ratio=price.price / price.last_price)[KEYS + ['price_ratio']],
                        on=KEYS, how='left')
    frame['price_ratio'] = frame.price_ratio.fillna(1.0)
    frame['last_sales'] = frame.last_sales.fillna(frame.demand)
    frame['status'] = 'ok'
    actual = inputs['quarterly'][inputs['quarterly'].quarter.eq(target_quarter)]
    out = finish_candidates(frame, inputs, origin, cfg).merge(
        actual[KEYS + ['sales', 'total_price']], on=KEYS, how='left')
    out['actual_sales'] = out.sales.fillna(0.0)
    out['actual_ticket'] = (out.total_price / out.sales).fillna(0.0)
    return out.drop(columns=['sales', 'total_price'])
