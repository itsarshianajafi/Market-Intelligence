"""Quarterly trend features per segment (area + off-plan/ready) from Part 1's monthly sales."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

KEYS = ['area', 'registration_type']
# A cell is one kind of property in one segment; prices are only compared within a cell.
CELL = KEYS + ['property_type', 'unit_type']


def load_monthly(path, property_types):
    """Read monthly_sales.csv, keeping only the property types we analyse."""
    monthly = pd.read_csv(path)
    monthly = monthly.loc[monthly.property_type.isin(property_types)].copy()
    monthly['unit_type'] = monthly.unit_type.fillna('Unknown')
    monthly['quarter'] = pd.PeriodIndex(monthly.month, freq='Q')
    return monthly


def last_complete_quarter(report_path):
    """Latest quarter fully covered by the export, from Part 1's quality report."""
    date_max = pd.Timestamp(json.loads(Path(report_path).read_text())['date_max'])
    quarter = date_max.to_period('Q')
    return quarter if date_max >= quarter.end_time.normalize() else quarter - 1


def cell_quarters(monthly):
    """Sales count and log price per m2 for each cell and quarter."""
    sales = monthly.groupby(CELL + ['quarter']).transaction_count.sum().rename('sales')
    priced = monthly.dropna(subset=['median_price_per_m2_aed'])
    # Sales-weighted mean of the monthly log medians (a weighted geometric mean).
    priced = priced.assign(weighted=np.log(priced.median_price_per_m2_aed) * priced.transaction_count)
    sums = priced.groupby(CELL + ['quarter'])[['weighted', 'transaction_count']].sum()
    cells = sales.to_frame().join(sums)
    cells['log_price'] = cells.weighted / cells.transaction_count
    return cells.rename(columns={'transaction_count': 'priced_sales'}).drop(columns='weighted')


def matched_change(cells, lag, min_cell_sales):
    """Mix-adjusted log price change per segment against `lag` quarters earlier.

    Each cell is compared with itself, then the changes are averaged with weight
    min(sales now, sales before). A shift from flats to villas does not look like
    a price change this way.
    """
    now = cells.reset_index()
    before = now.assign(quarter=now.quarter + lag)
    pairs = now.merge(before, on=CELL + ['quarter'], suffixes=('', '_before'))
    pairs['weight'] = np.minimum(pairs.priced_sales, pairs.priced_sales_before)
    pairs = pairs.loc[pairs.weight >= min_cell_sales]
    pairs = pairs.assign(weighted=(pairs.log_price - pairs.log_price_before) * pairs.weight)
    out = pairs.groupby(KEYS + ['quarter']).agg(
        weighted=('weighted', 'sum'), weight=('weight', 'sum'), matched_sales=('sales', 'sum'))
    return pd.DataFrame({'change': out.weighted / out.weight, 'matched_sales': out.matched_sales})


def build_features(monthly, last_quarter, cfg):
    """One row per segment and quarter from start_quarter to last_quarter, with no gaps."""
    cells = cell_quarters(monthly)
    sales = cells.groupby(KEYS + ['quarter']).sales.sum()
    segments = sales.index.droplevel('quarter').unique()
    first = pd.Period(cfg['start_quarter'], freq='Q') - 4 - cfg['volatility_window']
    quarters = pd.period_range(first, last_quarter, freq='Q')
    grid = pd.MultiIndex.from_tuples([(*s, q) for s in segments for q in quarters],
                                     names=KEYS + ['quarter'])
    df = pd.DataFrame(index=grid)
    df['sales'] = sales.reindex(grid, fill_value=0)
    df['sales_prev_year'] = df.groupby(level=KEYS).sales.shift(4)
    yoy = matched_change(cells, 4, cfg['min_cell_sales']).reindex(grid)
    df['log_price_change'] = yoy.change
    df['price_coverage'] = yoy.matched_sales / df.sales
    ratio = (df.sales / df.sales_prev_year).replace([0, np.inf], np.nan)
    df['log_volume_change'] = np.log(ratio)
    # Volatility: spread of the last few quarter-on-quarter price changes.
    qoq = matched_change(cells, 1, cfg['min_cell_sales']).change.reindex(grid)
    window = cfg['volatility_window']
    df['volatility'] = qoq.groupby(level=KEYS).transform(
        lambda s: s.rolling(window, min_periods=window - 1).std())
    df['status'] = np.where(
        df.sales.ge(cfg['min_sales']) & df.sales_prev_year.ge(cfg['min_sales'])
        & df.price_coverage.ge(cfg['min_coverage']) & df.log_price_change.notna(),
        'ok', 'insufficient_data')
    # Change from q+1 to q+5: shares no quarter with this row's change (q-4 to q), so noise in
    # quarter q cannot fake mean reversion. Forward check only, never a model input.
    df['next_log_price_change'] = df.groupby(level=KEYS).log_price_change.shift(-5)
    df['next_status'] = df.groupby(level=KEYS).status.shift(-5)
    df = df.loc[df.index.get_level_values('quarter') >= pd.Period(cfg['start_quarter'], freq='Q')]
    df = df.loc[df.sales.gt(0) | df.sales_prev_year.gt(0)]
    df['provisional'] = df.index.get_level_values('quarter') > last_quarter - cfg['provisional_quarters']
    return df.reset_index()
