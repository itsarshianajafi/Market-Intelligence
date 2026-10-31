"""Figures from the saved common-cohort test predictions, with native-unit labels."""
import os
from pathlib import Path
import tempfile

os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir()) / 'market-intelligence-mpl'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .data import TARGETS, KEYS

LABELS = {'sales_count': 'Recorded sales activity',
    'weighted_geomean_monthly_median_aed_m2': 'Price proxy: count-weighted geometric mean\nof monthly medians'}


def make_all(predictions, metrics, selected, folder):
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(2, 2, figsize=(14, 8), constrained_layout=True)
    for row, (target, unit) in enumerate(TARGETS.items()):
        test = predictions.loc[predictions.split.eq('test') & predictions.scored
            & predictions.target.eq(target) & predictions.model_id.eq(selected[target])].copy()
        if test.empty:
            for ax in axes[row]:
                ax.text(.5, .5, 'No common supported test cohort', ha='center', transform=ax.transAxes)
            continue
        test['absolute_error'] = test.error.abs()
        ranking = test.groupby(KEYS).absolute_error.mean().sort_values()
        # Show the median-error segment and the worst-error segment without cherry-picking.
        for col, position in enumerate([len(ranking) // 2, len(ranking) - 1]):
            segment = ranking.index[position]
            data = test.loc[test.area.eq(segment[0]) & test.registration_type.eq(segment[1])].sort_values('forecast_quarter')
            # A missing score breaks the line instead of joining across a gap.
            calendar = pd.period_range(predictions.loc[predictions.split.eq('test'), 'forecast_quarter'].min(),
                                       predictions.loc[predictions.split.eq('test'), 'forecast_quarter'].max(), freq='Q').astype(str)
            data = data.set_index('forecast_quarter').reindex(calendar).rename_axis('forecast_quarter').reset_index()
            ax = axes[row, col]
            ax.plot(data.forecast_quarter, data.actual, 'o-', label='Actual')
            ax.plot(data.forecast_quarter, data.prediction, 's--', label=selected[target])
            ax.set(title=f"{LABELS[target]}: {'median' if col == 0 else 'worst'} segment MAE\n{segment[0]} / {segment[1]}", ylabel=unit)
            ax.tick_params(axis='x', rotation=30)
            ax.grid(alpha=.2)
            ax.legend(fontsize=8)
    fig.suptitle('One-quarter-ahead held-out forecasts: 2025Q1 to 2026Q3\nSupplied records; revised snapshot; price proxy is not a quarterly transaction median', fontsize=12)
    fig.savefig(folder / 'actual_vs_forecast.png', dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)
    for ax, (target, unit) in zip(axes, TARGETS.items()):
        data = metrics.loc[metrics.split.eq('test') & metrics.target.eq(target) & metrics.forecast_quarter.eq('all')].sort_values('model_id')
        x = np.arange(len(data))
        ax.bar(x - .18, data.mae, width=.36, label='MAE')
        ax.bar(x + .18, data.rmse, width=.36, label='RMSE')
        names = [m.replace('seasonal_naive_v1', 'Seasonal naive').replace('naive_v1', 'Naive').replace('ridge_log_v1_alpha_', 'Ridge alpha=') for m in data.model_id]
        ax.set(xticks=x, xticklabels=names, ylabel=unit,
               title=f'{LABELS[target]}\nCommon rows per method: {int(data.n.iloc[0]) if len(data) else 0}')
        ax.tick_params(axis='x', rotation=15)
        ax.legend()
        ax.grid(axis='y', alpha=.2)
    fig.suptitle('Held-out comparison: method and alpha selected using 2024 validation only\n2025Q1 to 2026Q3; dependent temporal origins; incomplete coverage remains unverified', fontsize=12)
    fig.savefig(folder / 'baseline_comparison.png', dpi=160)
    plt.close(fig)
