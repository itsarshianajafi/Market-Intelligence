"""Run Part 2: label every segment and quarter, write market_trends.csv and the evaluation."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import evaluate
from .baselines import crisp_labels, kmeans_labels
from .features import build_features, last_complete_quarter, load_monthly
from .fuzzy import classify, fit_scales

DEFAULT_CONFIG = Path(__file__).with_name('config.json')
OUTPUT_COLUMNS = ['area', 'registration_type', 'quarter', 'sales_count', 'sales_count_prev_year',
                  'price_change_yoy', 'volume_change_yoy', 'volatility', 'price_coverage',
                  'status', 'provisional', 'trend_label', 'trend_score', 'rising_degree',
                  'stable_degree', 'declining_degree', 'baseline_label', 'kmeans_label']


def label(cfg):
    """Features plus fuzzy, crisp and k-means labels. Returns (all rows, scales, monthly, last quarter)."""
    monthly = load_monthly(cfg['input'], cfg['property_types'])
    last_quarter = last_complete_quarter(cfg['quality_report'])
    df = build_features(monthly, last_quarter, cfg)
    ok = df.status.eq('ok')
    scales = fit_scales(df.loc[ok], cfg)
    df = df.join(classify(df.loc[ok], scales))
    df.loc[ok, 'baseline_label'] = crisp_labels(df.loc[ok], scales)
    df.loc[ok, 'kmeans_label'] = kmeans_labels(df.loc[ok], cfg['seed'])
    df['trend_label'] = df.trend_label.fillna('Insufficient data')
    return df, scales, monthly, last_quarter


def shared_output(df):
    """The file for Parts 3 and 4: human-readable percentages, rounded."""
    out = df.assign(sales_count=df.sales, sales_count_prev_year=df.sales_prev_year.astype('Int64'),
                    price_change_yoy=np.expm1(df.log_price_change),
                    volume_change_yoy=df.sales / df.sales_prev_year - 1,
                    quarter=df.quarter.astype(str))
    out['volume_change_yoy'] = out.volume_change_yoy.replace(np.inf, np.nan)
    return out[OUTPUT_COLUMNS].round(4).sort_values(['quarter', 'area', 'registration_type'])


def run(cfg):
    df, scales, monthly, last_quarter = label(cfg)
    output = Path(cfg['output'])
    output.parent.mkdir(parents=True, exist_ok=True)
    shared_output(df).to_csv(output, index=False)

    ok = df.loc[df.status.eq('ok')].copy()
    methods = ['trend_label', 'baseline_label', 'kmeans_label']
    report_dir = Path(cfg['report_dir'])
    report_dir.mkdir(parents=True, exist_ok=True)
    forward = pd.concat([evaluate.forward_check(ok, m) for m in methods])
    forward.round(4).to_csv(report_dir / 'forward_check.csv', index=False)
    sens = evaluate.sensitivity(monthly, last_quarter, cfg, ok)
    sens.round(4).to_csv(report_dir / 'sensitivity.csv', index=False)
    result = {
        'last_complete_quarter': str(last_quarter),
        'rows': len(df), 'ok_rows': len(ok),
        'sales_share_ok': float(ok.sales.sum() / df.sales.sum()),
        'scales': {k: [float(v) for v in pair] for k, pair in scales.items()},
        'label_counts': {m: ok[m].value_counts().to_dict() for m in methods},
        'agreement': {'fuzzy_vs_crisp': evaluate.agreement(ok.trend_label, ok.baseline_label),
                      'fuzzy_vs_kmeans': evaluate.agreement(ok.trend_label, ok.kmeans_label),
                      'crisp_vs_kmeans': evaluate.agreement(ok.baseline_label, ok.kmeans_label)},
        'score_correlation_next_year': evaluate.score_correlation(ok),
        'persistence_next_quarter': {m: evaluate.persistence(ok, m) for m in methods},
        'bootstrap': evaluate.bootstrap_stability(ok, cfg, ok.trend_label.to_numpy()),
        'kmeans_seeds': evaluate.kmeans_stability(ok, cfg, ok.kmeans_label.to_numpy()),
        'config': cfg,
    }
    (report_dir / 'evaluation.json').write_text(json.dumps(result, indent=2, default=str) + '\n')
    return df, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    cfg = json.loads(parser.parse_args().config.read_text())
    _, result = run(cfg)
    print(json.dumps({k: result[k] for k in ['last_complete_quarter', 'ok_rows', 'label_counts',
                                             'agreement', 'score_correlation_next_year']},
                     indent=2, default=str))


if __name__ == '__main__':
    main()
