"""Report figures for Part 2 (PNG, light theme)."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .fuzzy import three_sets, ramp

# Diverging for direction (orange = down, grey = flat, blue = up); categorical for methods.
LABEL_COLORS = {'Declining': '#eb6834', 'Stable': '#898781', 'Rising': '#2a78d6'}
METHOD_COLORS = {'trend_label': '#2a78d6', 'baseline_label': '#eb6834', 'kmeans_label': '#1baf7a'}
METHOD_NAMES = {'trend_label': 'Fuzzy', 'baseline_label': 'Crisp rules', 'kmeans_label': 'k-means'}
INK, MUTED, GRID, SURFACE = '#0b0b0b', '#52514e', '#e1e0d9', '#fcfcfb'

plt.rcParams.update({
    'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE,
    'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': MUTED, 'xtick.color': MUTED,
    'ytick.color': MUTED, 'text.color': INK, 'axes.spines.top': False,
    'axes.spines.right': False, 'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'font.size': 9, 'axes.titlesize': 10, 'axes.titleweight': 'bold',
    'legend.frameon': False, 'lines.linewidth': 2})


def membership_functions(ok, scales, path):
    """Input membership functions over the real data distribution."""
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.4))
    for ax, (column, key, title) in zip(axes, [
            ('log_price_change', 'price', 'Price change per m² (log, YoY)'),
            ('log_volume_change', 'volume', 'Sales volume change (log, YoY)'),
            ('volatility', 'volatility', 'Volatility (std of QoQ change)')]):
        values = ok[column].dropna()
        lo, hi = np.percentile(values, [1, 99])
        x = np.linspace(lo, hi, 400)
        ax.hist(values.clip(lo, hi), bins=50, density=True, color=GRID, edgecolor=SURFACE)
        twin = ax.twinx()
        twin.grid(False)
        twin.spines[['top', 'right']].set_visible(False)
        if key == 'volatility':
            high = ramp(x, *scales[key])
            sets = [('Low', 1 - high, LABEL_COLORS['Stable']), ('High', high, LABEL_COLORS['Declining'])]
        else:
            down, flat, up = three_sets(x, *scales[key])
            sets = [('Falling', down, LABEL_COLORS['Declining']), ('Flat', flat, LABEL_COLORS['Stable']),
                    ('Rising', up, LABEL_COLORS['Rising'])]
        for name, mu, color in sets:
            twin.plot(x, mu, color=color, label=name)
        twin.set_ylim(0, 1.05)
        twin.set_yticks([0, 0.5, 1])
        ax.set_yticks([])
        ax.set_title(title, loc='left')
        twin.legend(loc='upper center', bbox_to_anchor=(0.5, -0.1), ncols=3, fontsize=8)
    axes[0].set_ylabel('Data (histogram)')
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def label_share(ok, path):
    """Share of segments in each fuzzy label, per quarter."""
    share = pd.crosstab(ok.quarter.astype(str), ok.trend_label, normalize='index')
    fig, ax = plt.subplots(figsize=(10, 3.4))
    bottom = np.zeros(len(share))
    for name in ['Declining', 'Stable', 'Rising']:
        ax.bar(share.index, share[name], bottom=bottom, color=LABEL_COLORS[name], label=name,
               width=0.8, edgecolor=SURFACE, linewidth=1)
        bottom += share[name].to_numpy()
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1))
    ax.set_xticks(range(0, len(share), 4), share.index[::4])
    ax.set_title('Share of segments by fuzzy trend label (segments with enough sales)', loc='left')
    ax.legend(ncols=3, loc='upper left', bbox_to_anchor=(0, -0.12))
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def forward_check(forward, path):
    """Mean next-year price change above the market median, by label and method."""
    labels = ['Declining', 'Stable', 'Rising']
    fig, ax = plt.subplots(figsize=(6, 3.2))
    width = 0.26
    for i, (method, color) in enumerate(METHOD_COLORS.items()):
        rows = forward.loc[forward.method == method].set_index('label').reindex(labels)
        ax.bar(np.arange(3) + (i - 1) * width, rows.mean_excess_change * 100, width - 0.03,
               color=color, label=METHOD_NAMES[method])
    ax.axhline(0, color='#c3c2b7', linewidth=1)
    ax.set_xticks(range(3), labels)
    ax.set_ylabel('Next-year change vs market (pp)')
    ax.set_title('Forward check: labels do not predict next year', loc='left')
    ax.legend(ncols=3, loc='upper left', bbox_to_anchor=(0, -0.12))
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def latest_quarter(ok, quarter, path, top=10):
    """Highest and lowest trend scores in the latest quarter."""
    rows = ok.loc[ok.quarter == quarter].sort_values('trend_score')
    rows = pd.concat([rows.head(top), rows.tail(top)]).drop_duplicates()
    names = rows.area.str.title() + ' (' + rows.registration_type + ')'
    fig, ax = plt.subplots(figsize=(7, 0.28 * len(rows) + 1.2))
    ax.barh(names, rows.trend_score, color=[LABEL_COLORS[x] for x in rows.trend_label], height=0.7)
    ax.axvline(0, color='#c3c2b7', linewidth=1)
    ax.set_xlim(-0.7, 0.7)
    ax.set_xlabel('Fuzzy trend score (−1 declining, +1 rising)')
    ax.set_title(f'Lowest and highest trend scores, {quarter} (provisional)', loc='left')
    handles = [matplotlib.patches.Patch(color=c, label=n) for n, c in LABEL_COLORS.items()]
    fig.legend(handles=handles, ncols=3, loc='lower center')
    ax.grid(axis='y', visible=False)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def make_all(ok, scales, forward, last_quarter, report_dir):
    membership_functions(ok, scales, report_dir / 'membership_functions.png')
    label_share(ok, report_dir / 'label_share_by_quarter.png')
    forward_check(forward, report_dir / 'forward_check.png')
    latest_quarter(ok, last_quarter, report_dir / 'latest_quarter_scores.png')
