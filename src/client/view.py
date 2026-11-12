"""Turn the shared results into the few plain facts the client view shows.

Everything here is read from the files Parts 1 to 4 already wrote. Nothing is recomputed.
"""
import json

import numpy as np
import pandas as pd

from src.dashboard.data import PRICE, ROOT, SALES, quarter_name

MAP = ROOT / 'data/reference/dubai_map.json'
START = '2020-01'       # the analysis window of Parts 2 to 4

KEYS = ['area', 'registration_type']
FIRM = 0.9      # a segment still picked in 90% of the stress tests is a firm pick


def display(area, names):
    """(name people use, DLD name or '' when they are the same)."""
    return (names[area], area) if area in names else (area, '')


def base_map():
    """Coastline, motorways and a point per area, fetched once from OpenStreetMap by src.client.basemap."""
    return json.loads(MAP.read_text()) if MAP.exists() else {'coast': [], 'roads': [], 'places': {}, 'attribution': ''}


def monthly_series(monthly, cutoff):
    """Sales per month since 2020 by registration type. A last month the export cuts short is left out."""
    recent = monthly[monthly.month >= START]
    cutoff = pd.Timestamp(cutoff)
    if cutoff < cutoff + pd.offsets.MonthEnd(0):
        recent = recent[recent.month < cutoff.strftime('%Y-%m')]
    table = recent.groupby(['month', 'registration_type']).transaction_count.sum().unstack(fill_value=0)
    return [{'month': month, 'offplan': int(row['Off-Plan']), 'ready': int(row['Ready'])} for month, row in table.iterrows()]


def price_series(monthly, scope, latest):
    """Typical price per m2 each quarter: the sales-weighted geometric mean of the monthly medians,
    the same measure Part 3 forecasts. It is not adjusted for the mix of homes sold."""
    rows = monthly[monthly.property_type.isin(scope) & (monthly.month >= START) & monthly.median_price_per_m2_aed.gt(0)]
    quarter = pd.PeriodIndex(rows.month, freq='Q').astype(str)
    rows = rows.assign(quarter=quarter, weighted=np.log(rows.median_price_per_m2_aed) * rows.transaction_count)
    sums = rows[rows.quarter <= latest].groupby(['quarter', 'registration_type'])[['weighted', 'transaction_count']].sum()
    price = np.exp(sums.weighted / sums.transaction_count).unstack()
    return [{'quarter': quarter_name(q), 'offplan': float(row['Off-Plan']), 'ready': float(row['Ready'])}
            for q, row in price.iterrows()]


def area_points(bundle):
    """Every area that has a forecast and a place on the map: expected sales, direction and agents in the plan."""
    forecasts, trends, plan = bundle['forecasts'], bundle['trends'], bundle['allocation']
    places = base_map()['places']
    sales = forecasts[forecasts.target.eq(SALES) & forecasts.forecast_value.notna()]
    latest = trends[trends.quarter.eq(bundle['forecast_manifest']['origin_quarter']) & trends.status.eq('ok')]
    agents = plan[plan.agents.gt(0)].groupby('area').agents.sum()
    words = {'Rising': 'rising', 'Stable': 'steady', 'Declining': 'falling'}
    out = []
    for area, rows in sales.groupby('area'):
        if area not in places:
            continue
        name, dld = display(area, bundle['names'])
        own = latest[latest.area.eq(area)].sort_values('sales_count', ascending=False)     # the busier segment decides
        last = rows.last_actual.sum(min_count=1)
        out.append({'name': name, 'dld': dld, 'lat': places[area]['lat'], 'lon': places[area]['lon'],
                    'forecast': float(rows.forecast_value.sum()),
                    'low': float(rows.range_low.sum(min_count=1)) if rows.range_low.notna().all() else None,
                    'high': float(rows.range_high.sum(min_count=1)) if rows.range_high.notna().all() else None,
                    'change': float(rows.forecast_value.sum() / last - 1) if last and last > 0 else None,
                    'direction': words[own.trend_label.iloc[0]] if len(own) else None,
                    'agents': int(agents.get(area, 0))})
    return sorted(out, key=lambda point: -point['forecast'])


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
    counts = trends[trends.status.eq('ok')].groupby(['quarter', 'trend_label']).size().unstack(fill_value=0)
    counts = counts.reindex(columns=['Rising', 'Stable', 'Declining'], fill_value=0)
    prices = price_series(monthly, bundle['forecasts'].property_scope.iloc[0].split('|'), latest)
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
        'monthly': monthly_series(monthly, bundle['quality']['date_max']),
        'prices': prices,
        'direction_history': [{'quarter': quarter_name(q), 'rising': int(row.Rising), 'steady': int(row.Stable),
                               'falling': int(row.Declining)} for q, row in counts.iterrows()],
        'areas': area_points(bundle),
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


METHODS = [('selected', 'This planner'), ('share_of_forecast_value', 'Agents by forecast value'),
           ('even_split', 'Even split, biggest areas'), ('share_of_last_sales', 'Agents by last quarter\'s sales')]


def backtest(evidence):
    """How plans made this way did on past quarters, against simple rules of thumb."""
    score = evidence['backtest'].set_index('method')
    return {'optimiser': float(score.share_of_oracle['selected']),
            'rule': float(score.share_of_oracle['share_of_forecast_value']),
            'quarters': int(score.quarters['selected']),
            'methods': [{'label': label, 'share': float(score.share_of_oracle[method])}
                        for method, label in METHODS if method in score.index]}


def segments(table, names):
    """Every segment the planner could choose from: expected sales, typical deal and agents given."""
    rows = table[table.ticket_aed.notna() & table.forecast_sales.gt(0)]
    return [{'name': display(r.area, names)[0], 'type': r.registration_type, 'sales': float(r.forecast_sales),
             'deal': float(r.ticket_aed), 'agents': int(r.agents)} for r in rows.itertuples()]


def team_curve():
    """Expected commission for different team sizes, from Part 4's report."""
    path = ROOT / 'reports/part4/team_size.csv'
    if not path.exists():
        return []
    curve = pd.read_csv(path)
    return [{'agents': int(r.agents), 'commission': float(r.expected_commission_aed)} for r in curve.itertuples()]


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
