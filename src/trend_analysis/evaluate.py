"""Evaluation without true labels: forward check, agreement, stability and sensitivity."""
import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score

from .baselines import kmeans_labels
from .features import build_features
from .fuzzy import classify, fit_scales


def agreement(a, b):
    """Share of rows with the same label, and Cohen's kappa (agreement beyond chance)."""
    a, b = pd.Series(a).reset_index(drop=True), pd.Series(b).reset_index(drop=True)
    keep = a.notna() & b.notna()
    return {'rows': int(keep.sum()), 'agreement': float((a[keep] == b[keep]).mean()),
            'kappa': float(cohen_kappa_score(a[keep], b[keep]))}


def forward_check(ok, label_col):
    """Next year's price change (q+1 to q+5) for each label.

    `excess` is the change minus that quarter's median over all segments, so a
    market-wide boom does not make every label look right.
    """
    rows = ok.loc[ok.next_status.eq('ok') & ok[label_col].notna()]
    excess = rows.next_log_price_change - rows.groupby('quarter').next_log_price_change.transform('median')
    out = rows.assign(excess=excess, up=rows.next_log_price_change > 0).groupby(label_col).agg(
        rows=('excess', 'size'), mean_next_change=('next_log_price_change', 'mean'),
        mean_excess_change=('excess', 'mean'), share_rising_next=('up', 'mean'))
    return out.rename_axis('label').reset_index().assign(method=label_col)


def score_correlation(ok):
    """Spearman correlation of trend score (and of raw price change) with next year's change."""
    rows = ok.loc[ok.next_status.eq('ok')]
    return {'rows': len(rows),
            'trend_score': float(rows.trend_score.corr(rows.next_log_price_change, method='spearman')),
            'price_change_only': float(rows.log_price_change.corr(rows.next_log_price_change,
                                                                  method='spearman'))}


def persistence(ok, label_col):
    """Share of segments whose label next quarter is the same as this quarter."""
    rows = ok.sort_values(['area', 'registration_type', 'quarter'])
    nxt = rows.groupby(['area', 'registration_type'])[label_col].shift(-1)
    consecutive = rows.groupby(['area', 'registration_type']).quarter.shift(-1) == rows.quarter + 1
    keep = consecutive & nxt.notna()
    return float((rows.loc[keep, label_col] == nxt[keep]).mean())


def summary(values):
    return {'mean': float(np.mean(values)), 'std': float(np.std(values, ddof=1)), 'runs': len(values)}


def bootstrap_stability(ok, cfg, reference):
    """Refit the membership breakpoints on resampled rows and relabel; repeat with fixed seeds."""
    rng = np.random.default_rng(cfg['seed'])
    agree, rising, declining = [], [], []
    for _ in range(cfg['bootstrap_runs']):
        sample = ok.iloc[rng.integers(0, len(ok), len(ok))]
        labels = classify(ok, fit_scales(sample, cfg)).trend_label
        agree.append((labels == reference).mean())
        rising.append((labels == 'Rising').mean())
        declining.append((labels == 'Declining').mean())
    return {'agreement_with_full_fit': summary(agree), 'share_rising': summary(rising),
            'share_declining': summary(declining)}


def kmeans_stability(ok, cfg, reference):
    """k-means with one random start per seed, compared with the reference clustering."""
    agree = [agreement(kmeans_labels(ok, seed, n_init=1), reference)['agreement']
             for seed in range(cfg['kmeans_runs'])]
    return {'agreement_with_reference': summary(agree)}


def sensitivity(monthly, last_quarter, cfg, base):
    """Change one setting at a time and compare the labels with the default run."""
    variants = [('min_sales', 10), ('min_sales', 50),
                ('scale_percentiles', [20, 70]), ('scale_percentiles', [30, 80]),
                ('volatility_percentiles', [50, 80]), ('min_cell_sales', 1)]
    keys = ['area', 'registration_type', 'quarter']
    rows = []
    for name, value in variants:
        variant = {**cfg, name: value}
        df = build_features(monthly, last_quarter, variant)
        ok = df.loc[df.status.eq('ok')]
        ok = ok.join(classify(ok, fit_scales(ok, variant)))
        both = ok[keys + ['trend_label']].merge(base[keys + ['trend_label']], on=keys)
        rows.append({'setting': name, 'value': str(value), 'ok_rows': len(ok),
                     'share_rising': (ok.trend_label == 'Rising').mean(),
                     'share_declining': (ok.trend_label == 'Declining').mean(),
                     'agreement_with_default': (both.trend_label_x == both.trend_label_y).mean()})
    return pd.DataFrame(rows)
