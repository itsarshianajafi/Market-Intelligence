"""Run with: streamlit run app.py"""
import json
import math

import altair as alt
import pandas as pd
import streamlit as st

from src.dashboard.data import (PRICE, ROOT, SALES, STATUS, explain_trend, filter_rows, forecast_table,
                                load_bundle, load_evidence, method_name, monthly_summary, source_signature)
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
    st.write('Official sales records, the direction each area is moving in, a forecast for next quarter '
             'and a plan for where a sales team should work.')
    q, monthly, trends = bundle['quality'], bundle['monthly'], bundle['trends']
    latest = trends.quarter.max()
    by_quarter = monthly.groupby(pd.PeriodIndex(monthly.month, freq='Q').astype(str)).transaction_count.sum()
    year_ago = str(pd.Period(latest, freq='Q') - 4)
    labelled = trends[trends.quarter.eq(latest) & trends.status.eq('ok')]
    a, b, c, d = st.columns(4)
    a.metric(f'Sales in {latest}', f'{by_quarter[latest]:,}',
             f'{by_quarter[latest] / by_quarter[year_ago] - 1:+.1%} vs {year_ago}')
    b.metric('Areas in the data', monthly.area.nunique())
    c.metric('Segments with a trend label', len(labelled),
             help='A segment is one area, off-plan or ready. Segments with too few sales get no label.')
    d.metric('Forecast quarter', bundle['forecast_manifest']['forecast_quarter'])

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
        st.subheader(f'Market direction, {latest}')
        st.altair_chart(label_bars(labelled.trend_label), width='stretch')
        missing = int(trends.quarter.eq(latest).sum() - len(labelled))
        st.caption(f'Labels describe the last year, they do not predict the next. '
                   f'{missing} more segments had too few sales to label.')
    with right:
        st.subheader('Saved agent plan')
        plan = bundle['allocation']
        st.altair_chart(plan_bars(plan[plan.agents.gt(0)]), width='stretch')
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
    quarter = st.selectbox('Quarter', sorted(frame.quarter.unique(), reverse=True))
    current = frame[frame.quarter.eq(quarter)]
    labelled = current[current.status.eq('ok')].sort_values('trend_score', ascending=False)
    cards = st.columns(4)
    for card, name in zip(cards, TREND):
        card.metric(name, int(labelled.trend_label.eq(name).sum()))
    cards[3].metric('Too few sales to label', len(current) - len(labelled))
    if current.provisional.any():
        st.caption(f'{quarter} is the latest quarter. Its records can still be corrected by DLD, so its labels are provisional.')
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
    st.caption(f'{quarter}, one quarter ahead of {origin}. Units and villas. Sales are per quarter and price is AED per m².')
    available = filter_rows(bundle['forecasts'], area, registration)
    if empty(available): return
    table = forecast_table(available).round({'sales_forecast': 0, 'sales_last': 0, 'price_forecast': 0, 'price_last': 0})
    st.dataframe(table, hide_index=True, width='stretch', column_config={
        'area': 'Area', 'registration_type': 'Type',
        'sales_forecast': number(f'Sales, {quarter}'), 'sales_last': number(f'Sales, {origin}'),
        'sales_change_pct': percent('Change'),
        'price_forecast': number(f'AED/m², {quarter}'), 'price_last': number(f'AED/m², {origin}'),
        'price_change_pct': percent('Change'),
        'status': st.column_config.TextColumn('How it was made', help='Blank numbers mean no forecast could be made. They are never zero.')})
    st.caption('Forecasts are single numbers with no range, so read them as rough sizes. '
               'The Evidence page shows how far off they were on past quarters.')

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
            change = f'{row.forecast_value / row.last_actual - 1:+.1%} vs {origin}'
        column.metric(f'{row.registration_type} · {name}', value, change)
        column.caption(f'{STATUS[row.status]} · {method_name(row.model_id)}')
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
    st.caption(f"Test periods: {periods['test_start']}–{periods['test_end']}. Each forecast used only data available before its quarter.")
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
        st.caption('Existing model limits use whole-agent rounding. The generated plan shows its effective area and off-plan limits; small teams can exceed the nominal percentage caps.')
        submitted = st.form_submit_button('Generate custom plan', type='primary')
    if submitted:
        try:
            # Recheck the complete snapshot immediately before invoking the optimiser.
            load_bundle()
            with st.spinner('Generating your plan…'):
                table, manifest = generate_plan(agents, deals, share / 100, ready / 100, offplan / 100, objective)
            st.session_state['custom_plan'] = (signature, table, manifest, dict(
                agents=agents, deals_per_agent=deals, market_share=share, ready=ready, offplan=offplan, objective=objective))
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
        st.caption(f"Generated for {params['agents']} agents · {params['deals_per_agent']} deals/agent · {params['market_share']}% market share · Ready {params['ready']}% / Off-Plan {params['offplan']}% commission · objective: {params['objective']}. Form edits apply only after Generate.")
    chosen = table[table.agents.gt(0)]
    a, b, c = st.columns(3)
    a.metric('Agents placed', int(chosen.agents.sum()))
    b.metric('Areas selected', chosen.area.nunique())
    c.metric('Estimated commission', f'AED {chosen.expected_commission_aed.sum():,.0f}')
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
        periods = manifest['evaluation_periods']
        st.write(f"The method for each target was chosen on {periods['validation_start']}–{periods['validation_end']} and then "
                 f"tested on {periods['test_start']}–{periods['test_end']}, forecasting each quarter with only the data before it. "
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
    st.sidebar.caption(f"Data through {bundle['quality']['date_max']} · Forecast {bundle['forecast_manifest']['forecast_quarter']}")
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
