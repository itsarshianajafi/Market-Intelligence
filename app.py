"""Run with: streamlit run app.py"""
import json
import math

import pandas as pd
import streamlit as st

from src.dashboard.data import ROOT, filter_rows, load_bundle, monthly_summary, source_signature
from src.dashboard.planning import generate_plan

st.set_page_config(page_title='Dubai Market Intelligence', page_icon='🏙️', layout='wide')
st.markdown('''<style>
.block-container {padding-top:2rem; max-width:1400px;}
[data-testid="stMetric"] {background:rgba(128,128,128,.07);padding:18px;border-radius:12px;}
</style>''', unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def cached_bundle(signature):
    return load_bundle()


def download(frame, label, filename, key):
    st.download_button(label, frame.to_csv(index=False).encode('utf-8'), filename,
                       'text/csv', key=key)


def empty(frame):
    if frame.empty:
        st.info('No records match these filters. Try another area or segment.')
        return True
    return False


def overview(bundle):
    st.header('Dubai’s property market, in context')
    st.write('Explore official sales, understand market direction, and plan where your team works next.')
    q = bundle['quality']
    a, b, c, d = st.columns(4)
    a.metric('Prepared sales', f"{q['sales_transactions']:,}")
    b.metric('Monthly data rows', f"{q['monthly_sales_rows']:,}")
    c.metric('Areas in the data', bundle['monthly'].area.nunique())
    d.metric('Forecast quarter', bundle['forecast_manifest']['forecast_quarter'])
    st.subheader('Sales activity over time')
    st.line_chart(monthly_summary(bundle['monthly'])[['Sales']], color='#14b8a6')
    st.caption('All supplied property types and transaction periods. Recent incomplete months are included; historical coverage varies.')
    left, right = st.columns(2)
    with left:
        st.subheader('Latest market direction')
        latest = bundle['trends'].quarter.max()
        labels = bundle['trends'].loc[bundle['trends'].quarter.eq(latest)].trend_label.value_counts()
        st.bar_chart(labels.rename('Segments'), color='#3b82f6')
        st.caption(f'{latest} · area and registration segments · trend labels describe the current market.')
    with right:
        st.subheader('Default agent plan')
        plan = bundle['allocation']; plan = plan[plan.agents.gt(0)]
        st.bar_chart(plan.groupby('area').agents.sum().rename('Agents'), horizontal=True, color='#14b8a6')
        st.caption('Saved plan uses placeholder business assumptions. Generate a custom plan in Agent Allocation.')
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
    start, end = st.select_slider('Month range', options=months, value=(months[0], months[-1]))
    frame = frame[frame.month.between(start, end)]
    a, b = st.columns(2)
    a.metric('Recorded sales', f'{frame.transaction_count.sum():,}')
    b.metric('Transaction value', f'AED {frame.total_price_aed.sum():,.0f}')
    st.line_chart(monthly_summary(frame)[['Sales']], color='#14b8a6')
    st.caption('Counts sum the selected monthly cells. Missing months are not inferred to be zero.')
    st.dataframe(frame.drop(columns='date'), hide_index=True, width='stretch')
    download(frame.drop(columns='date'), 'Download selected data', 'selected_monthly_sales.csv', 'explorer-download')


def trends(bundle, area, registration):
    st.header('Market Trends')
    st.caption('Descriptive fuzzy labels, not predictions of future price growth.')
    frame = filter_rows(bundle['trends'], area, registration)
    if empty(frame): return
    quarter = st.selectbox('Quarter', sorted(frame.quarter.unique(), reverse=True))
    current = frame[frame.quarter.eq(quarter)]
    st.bar_chart(current.trend_label.value_counts().rename('Segments'), color='#3b82f6')
    if area != 'All areas':
        history = frame.pivot(index='quarter', columns='registration_type', values='trend_score')
        st.line_chart(history)
    st.dataframe(current, hide_index=True, width='stretch')
    st.caption('Insufficient data means the support rules failed. It is not a Stable label. Latest-quarter inputs are provisional.')
    download(current, 'Download trend selection', 'selected_trends.csv', 'trends-download')


def forecasts(bundle, area, registration):
    st.header('Forecasts')
    st.caption('One quarter ahead · units and villas · activity in sales/quarter and price proxy in AED/m².')
    available = filter_rows(bundle['forecasts'], area, registration)
    if empty(available): return
    areas = sorted(available.area.unique())
    selected_area = st.selectbox('Forecast area', areas, index=areas.index('Business Bay') if 'Business Bay' in areas else 0)
    current = available[available.area.eq(selected_area)]
    for row in current.itertuples():
        name = 'Sales activity' if row.target == 'sales_count' else 'Price proxy (AED/m²)'
        value = f'{row.forecast_value:,.1f}' if pd.notna(row.forecast_value) else 'Unavailable'
        with st.container(border=True):
            st.subheader(f'{row.registration_type} · {name}')
            st.metric(f'{row.forecast_quarter} projection', value)
            st.caption(f'Status: {row.status} · model: {row.model_id}')
            if row.status in ('missing_input', 'insufficient_data', 'fallback'):
                st.info(row.reason)
    st.subheader('Historical forecasts against observed results')
    predictions = pd.read_csv(ROOT / 'reports/part3/predictions.csv')
    target = st.selectbox('Historical target', ['sales_count', 'weighted_geomean_monthly_median_aed_m2'],
                          format_func=lambda t: 'Sales activity' if t == 'sales_count' else 'Price proxy (AED/m²)')
    regs = sorted(current.registration_type.unique())
    reg = st.selectbox('Historical segment', regs)
    model = bundle['forecast_manifest']['selected_methods'][target]
    history = predictions[predictions.area.eq(selected_area) & predictions.registration_type.eq(reg)
                          & predictions.target.eq(target) & predictions.model_id.eq(model)
                          & predictions.split.eq('test') & predictions.scored.eq(True)]
    if not empty(history):
        st.line_chart(history.set_index('forecast_quarter')[['actual', 'prediction']].sort_index())
    periods = bundle['forecast_manifest']['evaluation_periods']
    st.caption(f"Test periods: {periods['test_start']}–{periods['test_end']}. Compare models in the evaluation report; performance can vary by segment. No prediction intervals are estimated.")
    download(current, 'Download area forecasts', 'selected_forecasts.csv', 'forecast-download')


def allocation(bundle, signature):
    st.header('Agent Allocation')
    st.write('Explore the saved recommendation or generate a plan using your team’s assumptions.')
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
    st.bar_chart(chosen.pivot_table(index='area', columns='registration_type', values='agents', aggfunc='sum').fillna(0), horizontal=True)
    st.dataframe(chosen, hide_index=True, width='stretch')
    download(table, 'Download full allocation', 'allocation.csv', 'allocation-download')
    st.download_button('Download plan assumptions', json.dumps(manifest, indent=2), 'allocation_manifest.json', 'application/json')
    with st.expander('Why some areas receive no agents'):
        st.dataframe(table[table.agents.eq(0)][['area', 'registration_type', 'forecast_status', 'note']], hide_index=True)
    if saved and st.button('Return to saved default'):
        del st.session_state['custom_plan']
        st.rerun()


def main():
    try:
        signature = source_signature()
        bundle = cached_bundle(signature)
    except (OSError, ValueError, KeyError) as exc:
        st.error(f'Data is unavailable or inconsistent: {exc}')
        st.info('Prepare the official export, then rerun Parts 2, 3 and 4 together. See the README for commands.')
        st.stop()
    st.sidebar.title('DUBAI / INTELLIGENCE')
    st.sidebar.caption('Real estate market research')
    page = st.sidebar.radio('Explore', ['Overview', 'Data Explorer', 'Market Trends', 'Forecasts', 'Agent Allocation'])
    st.sidebar.divider()
    st.sidebar.caption(f"Data through {bundle['quality']['date_max']} · Forecast {bundle['forecast_manifest']['forecast_quarter']}")
    area, registration = 'All areas', 'Both'
    if page in ('Data Explorer', 'Market Trends', 'Forecasts'):
        area = st.sidebar.selectbox('Area', ['All areas'] + sorted(bundle['monthly'].area.unique()))
        registration = st.sidebar.selectbox('Registration', ['Both', 'Ready', 'Off-Plan'])
    st.sidebar.caption('Official DLD data · University research project')
    if page == 'Overview': overview(bundle)
    elif page == 'Data Explorer': explorer(bundle, area, registration)
    elif page == 'Market Trends': trends(bundle, area, registration)
    elif page == 'Forecasts': forecasts(bundle, area, registration)
    else: allocation(bundle, signature)


if __name__ == '__main__':
    main()
