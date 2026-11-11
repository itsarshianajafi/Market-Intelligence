"""Calendar-aligned origin features; future outcomes remain separate from model inputs."""
import numpy as np
import pandas as pd

from .data import COUNT, KEYS, quarter

NUMERIC = ['level', 'previous', 'seasonal', 'trailing_mean', 'trailing_available',
           'target_sin', 'target_cos', 'history_quarters']
CATEGORICAL = KEYS
FEATURES = NUMERIC + CATEGORICAL


def transform(values, target):
    return np.log1p(values) if target == COUNT else np.log(values)


def inverse(values, target):
    return np.expm1(values) if target == COUNT else np.exp(values)


def make_features(panel, target, cfg):
    """At origin t, seasonal=t-3 predicts t+1. Every offset is a calendar offset.

    `actual` is metadata for fitting/scoring and is never in FEATURES. History and
    known_pairs are expanding counts at the origin, never full-series totals.
    """
    rows = panel.sort_values(KEYS + ['quarter']).copy()
    if rows.duplicated(KEYS + ['quarter']).any():
        raise ValueError('Panel keys must be unique')
    # Reindex here as well: callers cannot silently compress a calendar gap.
    pieces = []
    for _, group in rows.groupby(KEYS, sort=True):
        calendar = pd.period_range(group.quarter.min(), group.quarter.max(), freq='Q')
        aligned = group.set_index('quarter').reindex(calendar)
        for key in KEYS:
            aligned[key] = group.iloc[0][key]
        pieces.append(aligned.rename_axis('quarter').reset_index())
    if not pieces:
        raise ValueError('Cannot build features from an empty panel')
    rows = pd.concat(pieces, ignore_index=True)
    by = rows.groupby(KEYS, sort=False)
    raw = rows[target]
    z = pd.Series(transform(raw, target), index=rows.index)
    rows['level'] = z
    rows['previous'] = z.groupby([rows[k] for k in KEYS]).shift(1)
    rows['seasonal'] = z.groupby([rows[k] for k in KEYS]).shift(3)
    rows['trailing_mean'] = z.groupby([rows[k] for k in KEYS]).transform(lambda s: s.rolling(4, min_periods=1).mean())
    rows['trailing_available'] = z.groupby([rows[k] for k in KEYS]).transform(lambda s: s.rolling(4, min_periods=1).count())
    rows['history_quarters'] = raw.notna().groupby([rows[k] for k in KEYS]).cumsum().astype(int)
    rows['naive'] = raw
    rows['seasonal_naive'] = by[target].shift(3)
    rows['actual'] = by[target].shift(-1)
    rows['origin_quarter'] = rows.quarter
    rows['target_quarter'] = rows.quarter + 1
    angle = 2 * np.pi * rows.target_quarter.dt.quarter / 4
    rows['target_sin'], rows['target_cos'] = np.sin(angle), np.cos(angle)
    rows['pair_valid'] = rows.level.notna() & rows.actual.notna() & rows.target_quarter.ge(quarter(cfg['train_start']))
    # A pair for origin t becomes known at t+1. Do not count this row's future actual.
    known = rows.pair_valid.groupby([rows[k] for k in KEYS]).cumsum()
    rows['known_pairs'] = known.groupby([rows[k] for k in KEYS]).shift(1).fillna(0).astype(int)
    return rows


def origin_candidates(rows, origin, cfg):
    """Eligibility is decided before seeing the next actual. Reasons are explicit."""
    candidates = rows.loc[rows.origin_quarter.eq(origin) & rows.seen.fillna(False)].copy()
    candidates['origin_reason'] = np.select(
        [candidates.level.isna(), candidates.known_pairs.lt(cfg['min_training_pairs']),
         candidates.seasonal_naive.isna()],
        ['origin_target_unsupported', 'fewer_than_min_training_pairs', 'missing_matching_season'], default='')
    return candidates


def fallback_supported(rows, cfg):
    """The current target already carries its month and price support gates."""
    return rows.naive.notna() & rows.history_quarters.ge(cfg['min_fallback_quarters'])


def training_rows(rows, origin, cfg):
    """Fit only known labels and segment histories eligible as of this origin."""
    eligible = origin_candidates(rows, origin, cfg)
    # Enough known training pairs is the history gate; a temporarily missing
    # current input need not erase the segment's earlier supported training pairs.
    eligible = eligible.loc[eligible.known_pairs.ge(cfg['min_training_pairs']), KEYS]
    train = rows.loc[rows.pair_valid & rows.target_quarter.le(origin)].copy()
    return train.merge(eligible, on=KEYS, how='inner', validate='many_to_one')
