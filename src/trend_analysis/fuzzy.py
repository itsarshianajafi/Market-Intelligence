"""Mamdani fuzzy classifier: is a segment's market rising, stable or declining?

Inputs (per segment and quarter): year-on-year log change in price per m2,
year-on-year log change in sales volume, and price volatility.
"""
import numpy as np
import pandas as pd

# Stable first so a tie between Stable and a direction goes to Stable.
CLASSES = ['Stable', 'Rising', 'Declining']
# Output sets on a trend score from -1 (declining) to 1 (rising).
UNIVERSE = np.linspace(-1, 1, 201)


def ramp(x, a, b):
    """0 at or below a, 1 at or above b, linear in between."""
    return np.clip((np.asarray(x, dtype=float) - a) / (b - a), 0, 1)


def triangle(x, left, peak, right):
    """Triangular membership function."""
    return np.maximum(np.minimum((x - left) / (peak - left), (right - x) / (right - peak)), 0)


OUTPUT_SETS = {'Declining': triangle(UNIVERSE, -2, -1, 0),
               'Stable': triangle(UNIVERSE, -1, 0, 1),
               'Rising': triangle(UNIVERSE, 0, 1, 2)}


def three_sets(x, a, b):
    """Falling, flat and rising memberships of a signed change. They always sum to 1.

    Fully flat within +-a, fully rising (or falling) beyond +-b.
    """
    up, down = ramp(x, a, b), ramp(-np.asarray(x, dtype=float), a, b)
    return down, 1 - up - down, up


def fit_scales(df, cfg):
    """Membership breakpoints from the data: percentiles of the size of each change."""
    low, high = cfg['scale_percentiles']
    vol_low, vol_high = cfg['volatility_percentiles']
    scales = {'price': tuple(np.nanpercentile(df.log_price_change.abs(), [low, high])),
              'volume': tuple(np.nanpercentile(df.log_volume_change.abs(), [low, high])),
              'volatility': tuple(np.nanpercentile(df.volatility, [vol_low, vol_high]))}
    if any(not a < b for a, b in scales.values()):
        raise ValueError(f'Not enough variation to set membership functions: {scales}')
    return scales


def fired_rules(df, scales):
    """The rule base: (output class, rule weight, meaning, firing strength per row)."""
    p_fall, p_flat, p_rise = three_sets(df.log_price_change, *scales['price'])
    v_fall, _, v_rise = three_sets(df.log_volume_change, *scales['volume'])
    # Missing volatility (too few quarters) gives no evidence of high volatility.
    vol_high = np.nan_to_num(ramp(df.volatility, *scales['volatility']))
    return [  # AND = min, NOT x = 1 - x
        ('Rising', 1.0, 'Prices up and buyers not leaving', np.minimum(p_rise, 1 - v_fall)),
        ('Declining', 1.0, 'Prices down and no buying rush', np.minimum(p_fall, 1 - v_rise)),
        ('Stable', 1.0, 'Prices flat', p_flat),
        ('Stable', 0.7, 'Mixed signals: prices up, sales down', np.minimum(p_rise, v_fall)),
        ('Stable', 0.7, 'Mixed signals: prices down, sales up', np.minimum(p_fall, v_rise)),
        ('Rising', 0.5, 'Demand picking up first: prices flat, sales up', np.minimum(p_flat, v_rise)),
        ('Declining', 0.5, 'Demand drying up first: prices flat, sales down', np.minimum(p_flat, v_fall)),
        ('Stable', 0.5, 'Jumpy prices are less trustworthy', vol_high),
    ]


def rule_strengths(df, scales):
    """Fire the rule base. Returns the strength of each output class per row."""
    strength = {c: np.zeros(len(df)) for c in CLASSES}
    for label, weight, _meaning, fire in fired_rules(df, scales):
        strength[label] = np.maximum(strength[label], weight * fire)
    return strength


def classify(df, scales):
    """Fuzzy label, class degrees and a defuzzified trend score in [-1, 1]."""
    strength = rule_strengths(df, scales)
    # Clip each output set at its class strength, join with max, take the centroid.
    aggregated = np.max([np.minimum(strength[c][:, None], OUTPUT_SETS[c]) for c in CLASSES], axis=0)
    score = (aggregated * UNIVERSE).sum(axis=1) / aggregated.sum(axis=1)
    degrees = np.column_stack([strength[c] for c in CLASSES])
    return pd.DataFrame({'trend_label': np.array(CLASSES)[degrees.argmax(axis=1)],
                         'trend_score': score,
                         'rising_degree': strength['Rising'],
                         'stable_degree': strength['Stable'],
                         'declining_degree': strength['Declining']}, index=df.index)
