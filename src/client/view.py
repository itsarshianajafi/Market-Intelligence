"""Turn the shared results into the few plain facts the client view shows.

Everything here is read from the files Parts 1 to 4 already wrote. Nothing is recomputed.
"""
import pandas as pd

from src.dashboard.data import SALES, quarter_name

KEYS = ['area', 'registration_type']
FIRM = 0.9      # a segment still picked in 90% of the stress tests is a firm pick


def display(area, names):
    """(name people use, DLD name or '' when they are the same)."""
    return (names[area], area) if area in names else (area, '')


def market(bundle):
    """The headline quarter, the last eight quarters, the direction of areas and the busiest areas."""
    monthly, trends, manifest = bundle['monthly'], bundle['trends'], bundle['forecast_manifest']
    latest = manifest['origin_quarter']
    quarters = pd.PeriodIndex(monthly.month, freq='Q').astype(str)
    by_type = monthly.groupby([quarters, 'registration_type']).transaction_count.sum().unstack(fill_value=0)
    year_ago = str(pd.Period(latest, freq='Q') - 4)

    def change(column=None):
        now, before = (by_type.loc[q].sum() if column is None else by_type.loc[q, column] for q in (latest, year_ago))
        return {'sales': int(now), 'before': int(before), 'change': float(now / before - 1)}

    history = by_type.loc[str(pd.Period(latest, freq='Q') - 7):latest]
    labelled = trends[trends.quarter.eq(latest) & trends.status.eq('ok')].trend_label.value_counts()
    forecasts = bundle['forecasts']
    sales = forecasts[forecasts.target.eq(SALES)].groupby('area')[['forecast_value', 'last_actual']].sum(min_count=1)
    busiest = sales.dropna(subset=['forecast_value']).nlargest(5, 'forecast_value')
    held = manifest['forecast_ranges'][SALES]['ok']
    return {
        'quarter': quarter_name(latest), 'year_ago': quarter_name(year_ago),
        'forecast_quarter': quarter_name(manifest['forecast_quarter']),
        'cutoff': pd.Timestamp(bundle['quality']['date_max']).strftime('%d %b %Y').lstrip('0'),
        'total': change(), 'offplan': change('Off-Plan'), 'ready': change('Ready'),
        'history': [{'quarter': quarter_name(q), 'offplan': int(row['Off-Plan']), 'ready': int(row['Ready'])}
                    for q, row in history.iterrows()],
        'direction': {'steady': int(labelled.get('Stable', 0)), 'rising': int(labelled.get('Rising', 0)),
                      'falling': int(labelled.get('Declining', 0))},
        'busiest': [{'name': display(area, bundle['names'])[0], 'dld': display(area, bundle['names'])[1],
                     'forecast': float(row.forecast_value),
                     'change': float(row.forecast_value / row.last_actual - 1) if row.last_actual > 0 else None}
                    for area, row in busiest.iterrows()],
        'forecast_check': {'inside': held['test_coverage'], 'level': held['level'], 'low': held['low'], 'high': held['high']},
    }


def plan(table, manifest, names):
    """One card per area in the plan, biggest team first, plus the totals and the assumptions used."""
    chosen = table[table.agents.gt(0)]
    cards = []
    for area, rows in chosen.groupby('area', sort=False):
        name, dld = display(area, names)
        cards.append({
            'name': name, 'dld': dld, 'agents': int(rows.agents.sum()),
            'teams': [{'type': r.registration_type, 'agents': int(r.agents)} for r in rows.itertuples()],
            'sales': float(rows.forecast_sales.sum()),
            'deal_low': float(rows.ticket_aed.min()), 'deal_high': float(rows.ticket_aed.max()),
            'commission': float(rows.expected_commission_aed.sum()),
            'firm': bool(rows.selection_rate.min() >= FIRM), 'rising': bool(rows.trend_label.eq('Rising').any())})
    cards.sort(key=lambda card: (-card['agents'], -card['commission']))
    offplan = int(chosen.agents[chosen.registration_type.eq('Off-Plan')].sum())
    assumed = manifest['assumptions_not_from_data']
    return {
        'agents': int(chosen.agents.sum()), 'areas': int(chosen.area.nunique()),
        'commission': float(chosen.expected_commission_aed.sum()), 'deals': float(chosen.expected_deals.sum()),
        'offplan_agents': offplan, 'ready_agents': int(chosen.agents.sum()) - offplan, 'cards': cards,
        'assumptions': {'agents': assumed['agents'], 'deals_per_agent': assumed['deals_per_agent'],
                        'ready_rate': assumed['commission_rate']['Ready'],
                        'offplan_rate': assumed['commission_rate']['Off-Plan'],
                        'market_share': assumed['max_market_share'],
                        'offplan_change': manifest.get('what_if_demand_change', {}).get('Off-Plan', 0.0),
                        'ready_change': manifest.get('what_if_demand_change', {}).get('Ready', 0.0)}}


def backtest(evidence):
    """How plans made this way did on past quarters, against the best rule of thumb."""
    score = evidence['backtest'].set_index('method')
    return {'optimiser': float(score.share_of_oracle['selected']),
            'rule': float(score.share_of_oracle['share_of_forecast_value']),
            'quarters': int(score.quarters['selected'])}


def compare(saved, custom, names):
    """Agents per area in the saved plan and in a custom one, and how many agents sit somewhere new."""
    before = saved[saved.agents.gt(0)].groupby('area').agents.sum()
    after = custom[custom.agents.gt(0)].groupby('area').agents.sum()
    areas = before.index.union(after.index)
    rows = [{'name': display(area, names)[0], 'before': int(before.get(area, 0)), 'after': int(after.get(area, 0))}
            for area in areas]
    rows.sort(key=lambda row: (-row['before'], -row['after'], row['name']))
    both = custom[KEYS + ['agents']].merge(saved[KEYS + ['agents']], on=KEYS, how='left', suffixes=('', '_saved'))
    old, new = saved.expected_commission_aed.sum(), custom.expected_commission_aed.sum()
    return {'rows': rows, 'moved': int((both.agents - both.agents_saved.fillna(0)).clip(lower=0).sum()),
            'commission_before': float(old), 'commission_change': float(new / old - 1)}
