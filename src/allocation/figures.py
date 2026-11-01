"""Report figures for Part 4 (PNG, light theme). Same look as Part 2."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

from src.trend_analysis import figures as part2  # noqa: F401  (applies the shared rcParams)

READY, OFFPLAN, MUTED = '#2a78d6', '#eb6834', '#898781'
NAMES = {'even_split': 'Even split, biggest segments', 'share_of_last_sales': 'Share of last quarter sales',
         'share_of_forecast': 'Share of forecast sales',
         'share_of_forecast_value': 'Share of forecast value', 'optimiser_naive_input': 'Optimiser, last quarter as forecast',
         'selected': 'Optimiser, Part 3 forecast', 'selected_move_limit': 'Optimiser, move limit'}


def allocation(table, quarter, agents, path):
    """Agents per area for the live quarter, split into Off-Plan and Ready."""
    picked = table[table.agents > 0]
    wide = picked.pivot_table(index='area', columns='registration_type', values='agents', aggfunc='sum', fill_value=0)
    wide = wide.reindex(columns=['Off-Plan', 'Ready'], fill_value=0)
    wide = wide.loc[wide.sum(axis=1).sort_values().index]
    fig, ax = plt.subplots(figsize=(7.5, 0.5 * len(wide) + 1.4))
    ax.barh(wide.index, wide['Off-Plan'], color=OFFPLAN, height=0.6, label='Off-Plan')
    ax.barh(wide.index, wide['Ready'], left=wide['Off-Plan'], color=READY, height=0.6, label='Ready',
            edgecolor=part2.SURFACE, linewidth=2)
    for y, total in enumerate(wide.sum(axis=1)):
        ax.text(total + 0.08, y, str(int(total)), va='center', color=part2.MUTED)
    ax.set_xlabel('Agents')
    ax.xaxis.get_major_locator().set_params(integer=True)
    ax.grid(axis='y', visible=False)
    ax.set_title(f'Recommended allocation of {agents} agents, {quarter}', loc='left')
    ax.legend(loc='lower right')
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def backtest(summary, path):
    """Held-out result per method as a share of the best possible plan."""
    rows = summary[summary.method.isin(NAMES)].sort_values('share_of_oracle')
    fig, ax = plt.subplots(figsize=(7.5, 0.5 * len(rows) + 1.4))
    colors = [READY if m == 'selected' else MUTED for m in rows.method]
    ax.barh([NAMES[m] for m in rows.method], rows.share_of_oracle, color=colors, height=0.6)
    for y, value in enumerate(rows.share_of_oracle):
        ax.text(value + 0.008, y, f'{value:.1%}', va='center', color=part2.MUTED)
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_xlim(0, 1.08)
    ax.grid(axis='y', visible=False)
    ax.set_xlabel('Share of the hindsight-best plan, mean of test quarters 2025Q1 to 2026Q3')
    ax.set_title('Backtest on real sales', loc='left')
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def team_size(curve, path):
    """Value of a bigger team: expected commission against agents."""
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    ax.plot(curve.agents, curve.expected_commission_aed / 1e6, color=READY, marker='o', markersize=5)
    ax.set_xlabel('Agents')
    ax.set_ylabel('Expected commission (AED million per quarter)')
    ax.set_ylim(bottom=0)
    ax.set_title('What each team size could earn, under the assumed response', loc='left')
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def convergence(curves, path):
    """Annealing's gap to the exact optimum as iterations pass, mean and spread of all quarters."""
    curves = curves.dropna(axis=1)      # start where every quarter has a feasible plan
    mean, spread = curves.mean(), curves.std()
    steps = curves.columns.to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    ax.fill_between(steps, (mean - spread).clip(lower=0), mean + spread, color=READY, alpha=0.15, linewidth=0)
    ax.plot(steps, mean, color=READY)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_ylim(bottom=0)
    ax.set_xlabel('Iterations in total (three restarts of 30,000)')
    ax.set_ylabel('Gap to exact optimum')
    ax.set_title('Convergence over 11 quarters (mean, shaded = 1 std)', loc='left')
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
