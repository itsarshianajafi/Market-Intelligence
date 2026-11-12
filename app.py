"""Run with: streamlit run app.py"""
import json
import math

import altair as alt
import pandas as pd
import streamlit as st

from src.dashboard.data import (PRICE, ROOT, SALES, STATUS, explain_trend, filter_rows, forecast_table,
                                load_bundle, load_evidence, method_name, monthly_summary, quarter_name,
                                quarter_progress, range_text, source_signature)
from src.dashboard.planning import generate_plan

# Same colours as the report figures: direction is orange / grey / blue, registration is blue / aqua.
TREND = {'Rising': '#2a78d6', 'Stable': '#898781', 'Declining': '#eb6834'}
REGISTRATION = {'Off-Plan': '#2a78d6', 'Ready': '#1baf7a'}
ANALYSIS_START = '2020-01'
PLAN_METHODS = {
    'selected': 'Optimiser (the policy chosen on 2024)',
    'selected_move_limit': 'Optimiser with a limit on moves per quarter',
    'optimiser_naive_input': 'Optimiser fed last quarter\'s sales instead of the forecast',
    'share_of_forecast_value': 'Rule of thumb: agents in proportion to forecast value',
    'share_of_forecast': 'Rule of thumb: agents in proportion to forecast sales',
    'share_of_last_sales': 'Rule of thumb: agents in proportion to last quarter\'s sales',
    'even_split': 'Rule of thumb: even split over the biggest segments'}

st.set_page_config(page_title='Dubai Market Intelligence', page_icon='🏙️', layout='wide')
st.markdown('''<style>
.block-container {padding-top:2rem; max-width:1400px;}
[data-testid="stMetric"] {background:rgba(128,128,128,.07);padding:18px;border-radius:12px;}
</style>''', unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def cached_bundle(signature):
    return load_bundle(), load_evidence()


def download(frame, label, filename, key):
    st.download_button(label, frame.to_csv(index=False).encode('utf-8'), filename,
                       'text/csv', key=key)


def empty(frame):
    if frame.empty:
        st.info('No records match these filters. Try another area or segment.')
        return True
    return False


def colour(field, palette, title=None):
    return alt.Color(f'{field}:N', title=title, scale=alt.Scale(domain=list(palette), range=list(palette.values())),
                     legend=alt.Legend(orient='top'))


def percent(label, help=None):
    return st.column_config.NumberColumn(label, format='%+.1f%%', help=help)


def number(label, format='localized', help=None):
    return st.column_config.NumberColumn(label, format=format, help=help)


def degree(label, help=None):
    return st.column_config.ProgressColumn(label, min_value=0, max_value=1, format='%.2f', help=help)


def label_bars(labels):
    """Segments per trend label, always in the same order and colours."""
    counts = labels.value_counts().reindex(list(TREND), fill_value=0).rename_axis('Label').reset_index(name='Segments')
    return alt.Chart(counts).mark_bar(cornerRadiusEnd=4).encode(
        y=alt.Y('Label:N', sort=list(TREND), title=None), x=alt.X('Segments:Q', title='Segments'),
        color=alt.Color('Label:N', scale=alt.Scale(domain=list(TREND), range=list(TREND.values())), legend=None),
        tooltip=['Label', 'Segments']).properties(height=alt.Step(40))


def plan_bars(chosen):
    """Agents per area, split by off-plan and ready."""
    return alt.Chart(chosen).mark_bar(cornerRadiusEnd=4).encode(
        y=alt.Y('area:N', sort='-x', title=None, axis=alt.Axis(labelLimit=220)), x=alt.X('sum(agents):Q', title='Agents', axis=alt.Axis(tickMinStep=1)),
        color=colour('registration_type', REGISTRATION), order=alt.Order('registration_type:N'),
        tooltip=[alt.Tooltip('area', title='Area'), alt.Tooltip('registration_type', title='Type'),
                 alt.Tooltip('agents', title='Agents')]).properties(height=alt.Step(30))


def overview(bundle):
    st.header('Dubai’s property market, in context')
    st.write('Official sales records, the direction each area is moving in, a forecast for the next quarter '
             'and a plan for where a sales team should work.')
    q, monthly, trends = bundle['quality'], bundle['monthly'], bundle['trends']
    latest = trends.quarter.max()
    target_quarter = bundle['forecast_manifest']['forecast_quarter']
    quarters = pd.PeriodIndex(monthly.month, freq='Q').astype(str)
    by_quarter = monthly.groupby(quarters).transaction_count.sum()
    by_type = monthly.groupby([quarters, 'registration_type']).transaction_count.sum()
    year_ago = str(pd.Period(latest, freq='Q') - 4)
    labelled = trends[trends.quarter.eq(latest) & trends.status.eq('ok')]
    plan = bundle['allocation']
    chosen = plan[plan.agents.gt(0)]
    a, b, c, d = st.columns(4)
    a.metric(f'Sales, {quarter_name(latest)}', f'{by_quarter[latest]:,}',
             f'{by_quarter[latest] / by_quarter[year_ago] - 1:+.1%} vs {quarter_name(year_ago)}',
             help='The last complete quarter in the data.')
    b.metric('Areas in the data', monthly.area.nunique())
    c.metric('Segments with a trend label', len(labelled),
             help='A segment is one area, off-plan or ready. Segments with too few sales get no label.')
    months, year = quarter_name(target_quarter).rsplit(' ', 1)
    d.metric('Forecast for', months, year, delta_color='off', delta_arrow='off',
             help=f"The data ends on {q['date_max']}, so this is the quarter after the last complete one.")

    with st.container(border=True):
        st.markdown('**What this says**')
        change = {name: by_type[latest, name] / by_type[year_ago, name] - 1 for name in REGISTRATION}
        counts = labelled.trend_label.value_counts().reindex(list(TREND), fill_value=0)
        sales = bundle['forecasts'][bundle['forecasts'].target.eq(SALES)]
        biggest = sales.groupby('area').forecast_value.sum().nlargest(3)
        teams = chosen.groupby('area').agents.sum().sort_values(ascending=False)
        st.markdown(
            f"- **The market is {'down' if by_quarter[latest] < by_quarter[year_ago] else 'up'}.** "
            f"{quarter_name(latest)} had {by_quarter[latest]:,} sales, {by_quarter[latest] / by_quarter[year_ago] - 1:+.0%} "
            f"on a year earlier (off-plan {change['Off-Plan']:+.0%}, ready {change['Ready']:+.0%}).\n"
            f"- **Direction by area.** Of {len(labelled)} area segments with enough sales, {counts['Stable']} are "
            f"stable, {counts['Rising']} rising and {counts['Declining']} declining over the last year.\n"
            f"- **Most sales are expected in** {', '.join(f'{area} (about {value:,.0f})' for area, value in biggest.items())} "
            f"in {quarter_name(target_quarter)}. These are rough sizes, not exact numbers.\n"
            f"- **The plan puts {int(chosen.agents.sum())} agents in {chosen.area.nunique()} areas**, most in "
            f"{teams.index[0]} ({int(teams.iloc[0])}), where forecast sales, deal size and commission rate together "
            f"are worth most. It uses placeholder business assumptions until real ones are entered.")

    st.subheader('Sales per month')
    full = st.toggle('Show the full history', help='Records go back to 1975 but are sparse before 2019.')
    recent = monthly if full else monthly[monthly.month >= ANALYSIS_START]
    series = recent.groupby(['date', 'registration_type'], as_index=False).transaction_count.sum()
    st.altair_chart(alt.Chart(series).mark_line(strokeWidth=2).encode(
        x=alt.X('date:T', title=None), y=alt.Y('transaction_count:Q', title='Sales'),
        color=colour('registration_type', REGISTRATION),
        tooltip=[alt.Tooltip('date:T', title='Month', format='%b %Y'),
                 alt.Tooltip('registration_type', title='Type'),
                 alt.Tooltip('transaction_count', title='Sales', format=',')]).properties(height=320),
        width='stretch')
    st.caption(f"All property types. The last month ends on {q['date_max']}, so it is incomplete.")

    left, right = st.columns(2)
    with left:
        st.subheader(f'Market direction, {quarter_name(latest)}')
        st.altair_chart(label_bars(labelled.trend_label), width='stretch')
        missing = int(trends.quarter.eq(latest).sum() - len(labelled))
        st.caption(f'Labels describe the last year, they do not predict the next. '
                   f'{missing} more segments had too few sales to label.')
    with right:
        st.subheader(f'Saved agent plan, {quarter_name(target_quarter)}')
        st.altair_chart(plan_bars(chosen), width='stretch')
        st.caption('Uses placeholder business assumptions. Change them on the Agent Allocation page.')
    with st.expander('Source and data quality'):
        st.write(f"Official DLD / Data Dubai export. Observed records: {q['date_min']} to {q['date_max']}.")
        st.write('Observed dates do not establish complete market coverage. Downloading official exports remains manual; preparation and analysis are automated.')
        st.dataframe(pd.DataFrame([{'Check': key.replace('_', ' ').title(), 'Rows': q.get(key, 0)}
            for key in ['input_rows', 'invalid_rows', 'duplicate_rows', 'conflicting_id_rows', 'low_price_sales_rows', 'output_rows']]), hide_index=True)
        st.link_button('Official transaction catalogue', 'https://data.dubai/en/l/470061')


def explorer(bundle, area, registration):
    st.header('Data Explorer')
    st.caption('Monthly sales aggregates from official records. Off-plan and ready remain separate in the source table.')
    frame = filter_rows(bundle['monthly'], area, registration)
    types = st.multiselect('Property types', sorted(frame.property_type.dropna().unique()),
                           default=sorted(frame.property_type.dropna().unique()))
    frame = frame[frame.property_type.isin(types)]
    if empty(frame): return
    months = sorted(frame.month.unique())
    first = next((m for m in months if m >= ANALYSIS_START), months[0])
    start, end = st.select_slider('Month range', options=months, value=(first, months[-1]))
    frame = frame[frame.month.between(start, end)]
    a, b = st.columns(2)
    a.metric('Recorded sales', f'{frame.transaction_count.sum():,}')
    b.metric('Transaction value', f'AED {frame.total_price_aed.sum():,.0f}')
    st.line_chart(monthly_summary(frame)[['Sales']], color='#2a78d6', y_label='Sales')
    st.caption('Counts sum the selected monthly cells. Missing months are not inferred to be zero.')
    st.dataframe(frame.drop(columns='date'), hide_index=True, width='stretch', column_config={
        'area': 'Area', 'property_type': 'Property', 'unit_type': 'Unit type', 'registration_type': 'Type',
        'month': 'Month', 'transaction_count': number('Sales'), 'total_price_aed': number('Total value (AED)'),
        'median_price_aed': number('Median price (AED)'), 'median_area_m2': number('Median size (m²)', '%.1f'),
        'median_price_per_m2_aed': number('Median AED/m²')})
    download(frame.drop(columns='date'), 'Download selected data', 'selected_monthly_sales.csv', 'explorer-download')


def why_this_label(labelled, history, scales):
    """Replay the fuzzy rules for one segment: inputs, how strongly each set applies, which rules fire."""
    st.subheader('Why this label?')
    st.caption('Part 2 is a fuzzy classifier. Pick a segment to see its inputs, how far each one counts as '
               'falling, flat or rising, and which rules decided the label.')
    names = (labelled.area + ' · ' + labelled.registration_type).tolist()
    row = labelled.iloc[names.index(st.selectbox('Segment', names))]
    sets, rules, degrees = explain_trend(row, scales)
    a, b, c, d = st.columns(4)
    a.metric('Price per m², year on year', f'{row.price_change_yoy:+.1%}')
    b.metric('Sales volume, year on year', f'{row.volume_change_yoy:+.1%}')
    c.metric('Price volatility', '—' if pd.isna(row.volatility) else f'{row.volatility:.3f}',
             help='Spread of the recent quarter-on-quarter price changes.')
    d.metric('Label', row.trend_label, f'score {row.trend_score:+.2f}', delta_color='off', delta_arrow='off',
             help='Score runs from −1 (declining) to +1 (rising).')
    left, right = st.columns([1, 2])
    with left:
        st.markdown('**1. How far each input belongs to each set**')
        st.dataframe(pd.DataFrame([{'Input': name, 'Set': key, 'Degree': value}
                                   for name, group in sets.items() for key, value in group.items()]),
                     hide_index=True, width='stretch', column_config={'Degree': degree('Degree (0 to 1)')})
    with right:
        st.markdown('**2. Rules, strongest first**')
        st.dataframe(rules, hide_index=True, width='stretch', column_config={
            'Says': 'Says', 'Weight': number('Rule weight', '%.1f'),
            'Strength': degree('Strength', 'Rule weight × how true its condition is (AND = minimum).')})
    best = max(degrees, key=degrees.get)
    st.markdown('**3. Result:** ' + ', '.join(f'{name} {value:.2f}' for name, value in degrees.items())
                + f'. The strongest class is **{best}**, and a tie goes to Stable.')
    segment = history[history.area.eq(row.area) & history.registration_type.eq(row.registration_type)
                      & history.status.eq('ok')]
    st.markdown(f'**Trend score over time, {row.area} · {row.registration_type}**')
    st.line_chart(segment.set_index('quarter')[['trend_score']].rename(columns={'trend_score': 'Trend score'}),
                  color='#2a78d6', y_label='Trend score (−1 to +1)')


def trends(bundle, evidence, area, registration):
    st.header('Market Trends')
    st.caption('Is each segment rising, stable or declining? The labels describe the last year. '
               'They are not predictions of future prices.')
    frame = filter_rows(bundle['trends'], area, registration)
    if empty(frame): return
    quarter = st.selectbox('Quarter', sorted(frame.quarter.unique(), reverse=True), format_func=quarter_name)
    current = frame[frame.quarter.eq(quarter)]
    labelled = current[current.status.eq('ok')].sort_values('trend_score', ascending=False)
    cards = st.columns(4)
    for card, name in zip(cards, TREND):
        card.metric(name, int(labelled.trend_label.eq(name).sum()))
    cards[3].metric('Too few sales to label', len(current) - len(labelled))
    if current.provisional.any():
        st.caption(f'{quarter_name(quarter)} is the latest complete quarter. Its records can still be corrected by DLD, so its labels are provisional.')
    if labelled.empty:
        st.info('No segment here has enough sales, now and a year earlier, for a label.')
    else:
        table = labelled.assign(price=labelled.price_change_yoy * 100, volume=labelled.volume_change_yoy * 100)
        st.dataframe(table[['area', 'registration_type', 'trend_label', 'trend_score', 'price', 'volume',
                            'volatility', 'sales_count', 'baseline_label', 'kmeans_label']],
                     hide_index=True, width='stretch', column_config={
            'area': 'Area', 'registration_type': 'Type', 'trend_label': 'Trend',
            'trend_score': number('Score', '%+.2f', '−1 declining, +1 rising'),
            'price': percent('Price per m²', 'Change against the same quarter a year earlier, like for like.'),
            'volume': percent('Sales volume', 'Change against the same quarter a year earlier.'),
            'volatility': number('Volatility', '%.3f'), 'sales_count': number('Sales'),
            'baseline_label': st.column_config.TextColumn('Crisp rules say', help='Baseline: fixed price thresholds.'),
            'kmeans_label': st.column_config.TextColumn('k-means says', help='Baseline: three clusters.')})
        why_this_label(labelled, frame, evidence['trends']['scales'])
    download(current, 'Download trend selection', 'selected_trends.csv', 'trends-download')


def forecasts(bundle, area, registration):
    st.header('Forecasts')
    manifest = bundle['forecast_manifest']
    quarter, origin = manifest['forecast_quarter'], manifest['origin_quarter']
    target_name, origin_name = quarter_name(quarter), quarter_name(origin)
    cutoff = pd.Timestamp(bundle['quality']['date_max'])
    so_far, share = quarter_progress(bundle['monthly'], bundle['forecasts'], quarter, cutoff)
    st.caption(f'Forecast for {target_name}, made from data up to the end of {origin_name}, the last complete quarter. '
               'Units and villas. Sales are per quarter and price is AED per m².')
    if so_far is not None:
        st.info(f'{target_name} has already started: the data runs to {cutoff.day} {cutoff:%b %Y}, {share:.0%} of the quarter. '
                'Sales recorded so far are shown beside each forecast. They were not used to make it.')
    available = filter_rows(bundle['forecasts'], area, registration)
    if empty(available): return
    table = forecast_table(available, so_far, share).round(
        {'sales_forecast': 0, 'sales_last': 0, 'price_forecast': 0, 'price_last': 0, 'sales_pace': 0})
    level = manifest['forecast_ranges'][SALES]['ok']['level']
    likely = st.column_config.TextColumn('Likely range', help=f'Where about {level:.0%} of past forecasts of this kind landed, applied to this forecast.')
    progress = ['sales_so_far', 'sales_pace', 'pace_note'] if so_far is not None else []
    order = ['area', 'registration_type', 'sales_forecast', 'sales_range', *progress, 'sales_last', 'sales_change_pct',
             'price_forecast', 'price_range', 'price_last', 'price_change_pct', 'status']
    st.dataframe(table[order], hide_index=True, width='stretch', column_config={
        'area': 'Area', 'registration_type': 'Type', 'sales_range': likely, 'price_range': likely,
        'sales_forecast': number(f'Sales forecast, {target_name}'), 'sales_last': number(f'Sales, {origin_name}'),
        'sales_so_far': number(f'So far (to {cutoff.day} {cutoff:%b})', help='Sales already recorded in the forecast quarter.'),
        'sales_pace': number('At this pace', help='So far, scaled up to the whole quarter as if sales came evenly.'),
        'pace_note': st.column_config.TextColumn('Pace vs forecast', help='Is the pace inside the forecast\'s likely range?'),
        'sales_change_pct': percent('Change'),
        'price_forecast': number(f'AED/m² forecast, {target_name}'), 'price_last': number(f'AED/m², {origin_name}'),
        'price_change_pct': percent('Change'),
        'status': st.column_config.TextColumn('How it was made', help='Blank numbers mean no forecast could be made. They are never zero.')})
    st.caption(f'The likely range comes from past forecast errors, pooled over all areas: about {level:.0%} of past '
               'forecasts landed inside it. It is wider for forecasts made by repeating last quarter. '
               'The Evidence page shows how well it held.')
    if so_far is not None:
        paced = table.pace_note[table.pace_note.ne('')].value_counts()
        st.caption(f"Pace check: of {int(paced.sum())} forecasts with sales so far, {paced.get('Inside the range', 0)} are on pace "
                   f"inside their range, {paced.get('Below the range', 0)} below and {paced.get('Above the range', 0)} above. "
                   'Sales do not come evenly through a quarter and the latest weeks can still be added to, so treat the pace as a rough check.')

    st.subheader('One area in detail')
    areas = sorted(available.area.unique())
    selected_area = st.selectbox('Forecast area', areas, index=areas.index('Business Bay') if 'Business Bay' in areas else 0)
    current = available[available.area.eq(selected_area)]
    columns = st.columns(len(current))
    for column, row in zip(columns, current.itertuples()):
        name = 'sales' if row.target == SALES else 'AED/m²'
        value = f'{row.forecast_value:,.0f}' if pd.notna(row.forecast_value) else 'Unavailable'
        change = None
        if pd.notna(row.forecast_value) and pd.notna(row.last_actual) and row.last_actual > 0:
            change = f'{row.forecast_value / row.last_actual - 1:+.1%} vs {origin_name}'
        column.metric(f'{row.registration_type} · {name}', value, change)
        span = range_text(row.range_low, row.range_high)
        column.caption((f'Likely {span} · ' if span else '') + f'{STATUS[row.status]} · {method_name(row.model_id)}')
        if row.target == SALES and so_far is not None:
            seen = table[table.area.eq(row.area) & table.registration_type.eq(row.registration_type)].iloc[0]
            if pd.notna(seen.sales_so_far):
                column.caption(f'So far {seen.sales_so_far:,.0f} to {cutoff.day} {cutoff:%b}, about {seen.sales_pace:,.0f} at this pace. {seen.pace_note}.')
        if row.status != 'ok':
            column.info(row.reason)
    st.subheader('Past forecasts against what happened')
    predictions = pd.read_csv(ROOT / 'reports/part3/predictions.csv')
    a, b = st.columns(2)
    target = a.selectbox('Historical target', [SALES, PRICE],
                         format_func=lambda t: 'Sales activity' if t == SALES else 'Price (AED/m²)')
    reg = b.selectbox('Historical segment', sorted(current.registration_type.unique()))
    model = manifest['selected_methods'][target]
    history = predictions[predictions.area.eq(selected_area) & predictions.registration_type.eq(reg)
                          & predictions.target.eq(target) & predictions.model_id.eq(model)
                          & predictions.split.eq('test') & predictions.scored.eq(True)]
    if not empty(history):
        st.line_chart(history.set_index('forecast_quarter')[['actual', 'prediction']].sort_index().rename(
            columns={'actual': 'Actual', 'prediction': 'Forecast'}), color=['#898781', '#2a78d6'])
    periods = manifest['evaluation_periods']
    st.caption(f"Test quarters: {quarter_name(periods['test_start'])} to {quarter_name(periods['test_end'])}. Each forecast used only data available before its quarter.")
    download(current, 'Download area forecasts', 'selected_forecasts.csv', 'forecast-download')


def allocation(bundle, signature):
    st.header('Agent Allocation')
    st.write('Where should a sales team work next quarter? See the saved plan or generate one with your own assumptions.')
    st.warning('Deal rates, market share and commissions are assumptions. Estimated commission is a model output, not measured revenue or a guarantee.')
    with st.form('allocation-settings'):
        a, b, c = st.columns(3)
        agents = a.number_input('Team size', min_value=5, max_value=60, value=20, step=1)
        deals = b.number_input('Deals per agent per quarter', min_value=0.1, max_value=20.0, value=2.0, step=0.1)
        share = c.number_input('Maximum segment market share (%)', min_value=0.1, max_value=100.0, value=5.0, step=0.5)
        a, b, c = st.columns(3)
        ready = a.number_input('Ready commission (%)', min_value=0.1, max_value=100.0, value=2.0, step=0.1)
        offplan = b.number_input('Off-plan commission (%)', min_value=0.1, max_value=100.0, value=4.0, step=0.1)
        objective = c.selectbox('Planning objective', ['commission', 'deals'], format_func=str.title)
        st.markdown('**What if the market moves?** The forecast only knows past sales. Use these to test a shock '
                    'it cannot see, such as a conflict or a rate change.')
        a, b, c = st.columns(3)
        offplan_change = a.number_input('Off-plan sales change (%)', min_value=-90, max_value=100, value=0, step=5)
        ready_change = b.number_input('Ready sales change (%)', min_value=-90, max_value=100, value=0, step=5)
        st.caption('Existing model limits use whole-agent rounding. The generated plan shows its effective area and off-plan limits; small teams can exceed the nominal percentage caps.')
        submitted = st.form_submit_button('Generate custom plan', type='primary')
    if submitted:
        try:
            # Recheck the complete snapshot immediately before invoking the optimiser.
            load_bundle()
            with st.spinner('Generating your plan…'):
                table, manifest = generate_plan(agents, deals, share / 100, ready / 100, offplan / 100, objective,
                                                ready_change / 100, offplan_change / 100)
            st.session_state['custom_plan'] = (signature, table, manifest, dict(
                agents=agents, deals_per_agent=deals, market_share=share, ready=ready, offplan=offplan, objective=objective,
                ready_change=ready_change, offplan_change=offplan_change))
        except (ValueError, OSError, KeyError) as exc:
            st.error(f'Could not generate a plan: {exc}')
    saved = st.session_state.get('custom_plan')
    if saved and saved[0] != signature:
        st.warning('Source data changed. Generate a new custom plan; showing the saved default below.')
        saved = None
    table = saved[1] if saved else bundle['allocation']
    manifest = saved[2] if saved else bundle['allocation_manifest']
    st.subheader('Custom plan' if saved else 'Saved default plan')
    if saved:
        params = saved[3]
        st.caption(f"Generated for {params['agents']} agents · {params['deals_per_agent']} deals/agent · {params['market_share']}% market share · Ready {params['ready']}% / Off-Plan {params['offplan']}% commission · objective: {params['objective']} · what if: off-plan sales {params['offplan_change']:+d}%, ready {params['ready_change']:+d}%. Form edits apply only after Generate.")
    chosen = table[table.agents.gt(0)]
    a, b, c = st.columns(3)
    a.metric('Agents placed', int(chosen.agents.sum()))
    b.metric('Areas selected', chosen.area.nunique())
    default = bundle['allocation']
    versus = None
    if saved:
        versus = f"{chosen.expected_commission_aed.sum() / default.expected_commission_aed.sum() - 1:+.0%} vs the saved plan"
    c.metric('Estimated commission', f'AED {chosen.expected_commission_aed.sum():,.0f}', versus)
    if saved:
        keys = ['area', 'registration_type']
        both = chosen[keys + ['agents']].merge(default[keys + ['agents']], on=keys, how='left', suffixes=('', '_saved'))
        moved = int((both.agents - both.agents_saved.fillna(0)).clip(lower=0).sum())
        st.caption(f'{moved} of {int(chosen.agents.sum())} agents sit in a different segment than in the saved plan.')
    count = int(manifest['agents'])
    assumptions = manifest['assumptions_not_from_data']
    cap = max(math.ceil(assumptions['max_area_share'] * count), assumptions['min_team_per_area'] + 1)
    low, high = assumptions['offplan_share']
    st.caption(f"Effective limits: at most {cap} agents per area; {math.floor(low * count)}–{math.ceil(high * count)} off-plan agents; at most {assumptions['max_areas']} areas.")
    st.altair_chart(plan_bars(chosen), width='stretch')
    st.dataframe(chosen.assign(selection=chosen.selection_rate * 100, forecast_sales=chosen.forecast_sales.round())[[
        'area', 'registration_type', 'agents', 'forecast_sales', 'ticket_aed', 'expected_deals',
        'expected_commission_aed', 'next_agent_value_aed', 'selection', 'trend_label']],
        hide_index=True, width='stretch', column_config={
            'area': 'Area', 'registration_type': 'Type', 'agents': number('Agents'),
            'forecast_sales': number('Forecast sales', help='Part 3\'s forecast for the whole segment.'),
            'ticket_aed': number('Typical deal (AED)', help='Typical recent sale price in the segment.'),
            'expected_deals': number('Expected deals', '%.1f', 'Deals this team is expected to close, with diminishing returns as it grows.'),
            'expected_commission_aed': number('Expected commission (AED)'),
            'next_agent_value_aed': number('One more agent adds (AED)', help='Extra commission from adding one agent here. Zero means the area is at its limit.'),
            'selection': st.column_config.NumberColumn('Still chosen', format='%.0f%%', help='How often this segment is still picked when the forecast is shaken by its past errors.'),
            'trend_label': 'Trend'})
    st.caption('A segment is picked when its forecast sales, typical deal size and commission rate together beat the '
               'alternatives, within the limits above. Trend labels are shown for context and do not change the plan.')
    download(table, 'Download full allocation', 'allocation.csv', 'allocation-download')
    st.download_button('Download plan assumptions', json.dumps(manifest, indent=2), 'allocation_manifest.json', 'application/json')
    with st.expander('Why some areas receive no agents'):
        st.dataframe(table[table.agents.eq(0)][['area', 'registration_type', 'forecast_status', 'note']], hide_index=True,
                     column_config={'area': 'Area', 'registration_type': 'Type', 'forecast_status': 'Forecast', 'note': 'Reason'})
    if saved and st.button('Return to saved default'):
        del st.session_state['custom_plan']
        st.rerun()


def figure(path, caption):
    st.image(str(ROOT / 'reports' / path), caption=caption)


def evidence_page(evidence, manifest):
    st.header('Evidence')
    st.caption('How each AI part was tested, against simpler baselines. Every number is read from the evaluation '
               'files in reports/, which the pipeline writes.')
    fuzzy, forecast, plan = st.tabs(['Market trends · fuzzy logic', 'Forecasts · regression', 'Agent allocation · search'])
    with fuzzy:
        e = evidence['trends']
        boot = e['bootstrap']['agreement_with_full_fit']
        a, b, c, d = st.columns(4)
        a.metric('Agrees with crisp rules', f"{e['agreement']['fuzzy_vs_crisp']['agreement']:.0%}",
                 help=f"Cohen's kappa {e['agreement']['fuzzy_vs_crisp']['kappa']:.2f}. The fuzzy rules differ on borderline segments.")
        b.metric('Agrees with k-means', f"{e['agreement']['fuzzy_vs_kmeans']['agreement']:.0%}",
                 help='Clusters do not line up with rising, stable and declining.')
        c.metric('Labels unchanged when refitted', f"{boot['mean']:.1%}",
                 f"± {boot['std']:.1%} over {boot['runs']} resamples", delta_color='off', delta_arrow='off')
        d.metric('Predicts next year?', f"{e['score_correlation_next_year']['trend_score']:+.2f}",
                 help='Spearman correlation of the trend score with the following year\'s price change. Zero means no link.')
        st.write('High agreement with the crisp rules means the fuzzy labels mostly differ on borderline segments. '
                 'Low agreement with k-means means clusters are not a substitute for the rules. A link to next year '
                 'near zero means the labels describe the market as it is and should not be used as a forecast.')
        figure('part2/membership_functions.png', 'Membership functions over the real data')
        figure('part2/label_share_by_quarter.png', 'Share of segments per label, by quarter')
    with forecast:
        metrics = evidence['metrics']
        test = metrics[metrics.split.eq('test') & metrics.forecast_quarter.eq('all')]
        rows = [{'Target': 'Sales per quarter' if r.target == SALES else 'Price (AED/m²)',
                 'Method': method_name(r.model_id) + (' (chosen)' if r.model_id == manifest['selected_methods'][r.target] else ''),
                 'Mean error': r.mae, 'Error as share of sales': r.wape * 100, 'Forecasts scored': r.n}
                for r in test.itertuples()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch', column_config={
            'Mean error': number('Mean absolute error', '%.0f', 'In sales per quarter, or AED per m².'),
            'Error as share of sales': st.column_config.NumberColumn('Error as % of actual', format='%.1f%%', help='Sum of absolute errors over sum of actual sales. Not defined for price.'),
            'Forecasts scored': number('Forecasts scored')})
        for card, (target, name) in zip(st.columns(2), [(SALES, 'Sales'), (PRICE, 'Price')]):
            held = manifest['forecast_ranges'][target]['ok']
            if held['test_coverage'] is not None:
                card.metric(f'{name}: actuals inside the likely range', f"{held['test_coverage']:.0%}",
                            f"aimed for {held['level']:.0%} · range {math.expm1(held['low']):+.0%} to "
                            f"{math.expm1(held['high']):+.0%} around a forecast · {held['test_forecasts']} test forecasts",
                            delta_color='off', delta_arrow='off',
                            help='Each test quarter\'s range used only the errors of earlier quarters.')
        periods = manifest['evaluation_periods']
        st.write(f"The method for each target was chosen on {quarter_name(periods['validation_start'])} to {quarter_name(periods['validation_end'])} and then "
                 f"tested on {quarter_name(periods['test_start'])} to {quarter_name(periods['test_end'])}, forecasting each quarter with only the data before it. "
                 'A chosen method that does not beat "last quarter repeated" on the test is still kept, '
                 'because the choice was fixed before the test.')
        figure('part3/baseline_comparison.png', 'Test error by method')
        figure('part3/actual_vs_forecast.png', 'Forecast against actual on the test quarters')
    with plan:
        e, table = evidence['allocation'], evidence['backtest']
        score = table.set_index('method').share_of_oracle
        versus = next(t for t in e['paired_tests'] if t['against'] == 'share_of_forecast_value')
        a, b, c, d = st.columns(4)
        a.metric('Optimiser', f"{score['selected']:.0%}", help='Share of the best possible commission, knowing the real outcome, averaged over the test quarters.')
        b.metric('Best rule of thumb', f"{score['share_of_forecast_value']:.0%}")
        c.metric('Quarters the optimiser wins', f"{versus['wins']} of {versus['wins'] + versus['losses'] + versus['ties']}",
                 f"Wilcoxon p = {versus['wilcoxon_p']:.3f}", delta_color='off', delta_arrow='off')
        d.metric('Gap to the exact optimum', f"{e['solver_gap']['mean_gap']:.2%}",
                 f"worst {e['solver_gap']['max_gap']:.2%}", delta_color='off', delta_arrow='off',
                 help='How far simulated annealing lands from the exact solver on the same problem.')
        shown = table[table.method.isin(PLAN_METHODS)]
        st.dataframe(pd.DataFrame({'Method': shown.method.map(PLAN_METHODS), 'Average': shown.share_of_oracle * 100,
                                   'Worst quarter': shown.worst_quarter * 100,
                                   'Plans that keep every limit': shown.feasible_quarters.astype(str) + ' of ' + shown.quarters.astype(str)}),
                     hide_index=True, width='stretch', column_config={
            'Average': st.column_config.NumberColumn('Share of the best possible plan', format='%.0f%%'),
            'Worst quarter': st.column_config.NumberColumn('Worst quarter', format='%.0f%%')})
        st.write('Each past quarter was planned with what was known at the time and scored on what then happened. '
                 'A method showing 0 in the last column breaks the team limits every quarter, so its plans are not valid.')
        figure('part4/backtest.png', 'Backtest: optimiser against rules of thumb')
        figure('part4/convergence.png', 'Simulated annealing closing the gap to the exact optimum')


def main():
    try:
        signature = source_signature()
        bundle, evidence = cached_bundle(signature)
    except (OSError, ValueError, KeyError) as exc:
        st.error(f'Data is unavailable or inconsistent: {exc}')
        st.info('Prepare the official export, then rerun Parts 2, 3 and 4 together. See the README for commands.')
        st.stop()
    st.sidebar.title('DUBAI / INTELLIGENCE')
    st.sidebar.caption('Real estate market research')
    page = st.sidebar.radio('Explore', ['Overview', 'Data Explorer', 'Market Trends', 'Forecasts',
                                        'Agent Allocation', 'Evidence'])
    st.sidebar.divider()
    st.sidebar.caption(f"Data to {bundle['quality']['date_max']} · Forecast for {quarter_name(bundle['forecast_manifest']['forecast_quarter'])}")
    today = pd.Timestamp.now(tz='Asia/Dubai').tz_localize(None).normalize()
    st.sidebar.caption(f"The data is {(today - pd.Timestamp(bundle['quality']['date_max'])).days} days old.")
    if today > pd.Period(bundle['forecast_manifest']['forecast_quarter'], freq='Q').end_time:
        st.sidebar.warning('The forecast quarter is over. Download a new export and run the update command in the README.')
    area, registration = 'All areas', 'Both'
    if page in ('Data Explorer', 'Market Trends', 'Forecasts'):
        area = st.sidebar.selectbox('Area', ['All areas'] + sorted(bundle['monthly'].area.unique()))
        registration = st.sidebar.selectbox('Registration', ['Both', 'Ready', 'Off-Plan'])
    st.sidebar.caption('Official DLD data · University research project')
    if page == 'Overview': overview(bundle)
    elif page == 'Data Explorer': explorer(bundle, area, registration)
    elif page == 'Market Trends': trends(bundle, evidence, area, registration)
    elif page == 'Forecasts': forecasts(bundle, area, registration)
    elif page == 'Agent Allocation': allocation(bundle, signature)
    else: evidence_page(evidence, bundle['forecast_manifest'])


if __name__ == '__main__':
    main()
