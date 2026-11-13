// Client view. The server sends plain facts; this file lays them out and Charts draws them.
'use strict';

// Data colours come from the stylesheet's theme variables (app.css), read again whenever the theme changes.
// pick = the plan's own marks, other = everything it did not choose; RAMP is one hue for more expected sales.
let C = {}, RAMP = [];
function readTheme() {
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  C = Object.fromEntries(['offplan', 'ready', 'rising', 'steady', 'falling', 'pick', 'other', 'muted', 'surface'].map((k) => [k, css(k)]));
  RAMP = [1, 2, 3, 4, 5].map((step) => css(`ramp-${step}`));
}

// Five classes holding about the same number of areas, so the colours spread over the whole map.
function classes(values) {
  const sorted = values.slice().sort((a, b) => a - b);
  const cuts = [1, 2, 3, 4].map((k) => sorted[Math.floor(sorted.length * k / 5)]);
  const nice = (v) => { const p = 10 ** Math.max(0, Math.floor(Math.log10(v)) - 1); return Math.round(v / p) * p; };
  const edges = [...new Set(cuts.map(nice))];
  return { edges, of: (v) => edges.filter((e) => v >= e).length };
}
const $ = (id) => document.getElementById(id);
const whole = Charts.whole;
const percent = (x) => `${Math.abs(Math.round(x * 100))}%`;
const signed = (x) => Math.abs(x) < 0.005 ? 'no change' : `${x < 0 ? '−' : '+'}${percent(x)}`;
const millions = (aed) => `AED ${(aed / 1e6).toFixed(aed >= 1e7 ? 1 : 2)}M`;
const money = (aed) => aed >= 1e6 ? millions(aed) : `AED ${Math.round(aed / 1e3)}K`;
const shortQuarter = (name) => name.replace(/ 20(\d\d)$/, ' ’$1');

// Text always goes in through textContent, so names from the data files can never run as markup.
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function fill(parent, children) {
  parent.replaceChildren(...children);
  return parent;
}
// A stat tile: label, big value, a note, and optionally a change marker and something on the right.
function tile(label, value, note, { change, extra } = {}) {
  const noteLine = el('span', 'tile-note');
  if (change !== undefined && Math.abs(change) >= 0.005) noteLine.append(el('span', change < 0 ? 'delta down' : 'delta up', percent(change)));
  noteLine.append(document.createTextNode(note));
  const row = fill(el('div', 'tile-row'), [el('span', 'tile-value', value)].concat(extra ? [extra] : []));
  return fill(el('div', 'tile'), [el('span', 'tile-label', label), row, noteLine]);
}
const yearTicks = (labels, pick) => labels.map((label, i) => (pick(label) ? i : -1)).filter((i) => i >= 0);

let baseMap = { coast: [], roads: [], attribution: '' };
let redrawMarketMap = () => {};

function showMarket(m) {
  $('cutoff').textContent = `Official DLD records to ${m.cutoff}`;
  $('market-kicker').textContent = `${m.quarter} · the last full quarter`;
  $('market-headline').textContent = `Sales are ${m.total.change < 0 ? 'down' : 'up'} ${percent(m.total.change)} on a year earlier`;
  $('market-lead').textContent = `${whole(m.total.sales)} homes were sold in ${m.quarter}, against ${whole(m.total.before)} in ${m.year_ago}.`;

  const price = m.prices[m.prices.length - 1], priceBefore = m.prices[m.prices.length - 5];
  fill($('market-tiles'), [
    tile('Homes sold', whole(m.total.sales), ' on a year earlier',
      { change: m.total.change, extra: Charts.spark(m.history.map((q) => q.offplan + q.ready), C.pick) }),
    tile('Off-plan homes', whole(m.offplan.sales), ' on a year earlier', { change: m.offplan.change }),
    tile('Ready homes', whole(m.ready.sales), ' on a year earlier', { change: m.ready.change }),
    tile('Off-plan price per m²', `AED ${whole(price.offplan)}`, priceBefore ? ' on a year earlier' : 'typical, this quarter',
      priceBefore ? { change: price.offplan / priceBefore.offplan - 1 } : {}),
    tile('Ready price per m²', `AED ${whole(price.ready)}`, priceBefore ? ' on a year earlier' : 'typical, this quarter',
      priceBefore ? { change: price.ready / priceBefore.ready - 1 } : {})]);

  const months = m.monthly.map((row) => new Date(`${row.month}-01T00:00:00`).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' }));
  $('monthly-note').textContent = `${months[0]} to ${months[months.length - 1]}`;
  $('monthly-foot').textContent = `Units, villas and all other property types. A last month the records only partly cover is left out.`;
  Charts.line($('monthly-chart'), {
    labels: months, xTicks: yearTicks(m.monthly.map((r) => r.month), (month) => month.endsWith('-01')).filter((_, i) => i % 2 === 0),
    tickText: (i) => m.monthly[i].month.slice(0, 4),
    series: [{ name: 'Off-plan', color: C.offplan, values: m.monthly.map((r) => r.offplan) },
      { name: 'Ready', color: C.ready, values: m.monthly.map((r) => r.ready) }],
    zoom: true, height: 320, label: `Homes sold each month from ${months[0]} to ${months[months.length - 1]}, off-plan and ready.` });
  const quarters = m.prices.map((p) => p.quarter);
  Charts.line($('price-chart'), {
    labels: quarters, xTicks: yearTicks(quarters, (q) => q.startsWith('Jan')).filter((_, i) => i % 2 === 0),
    tickText: (i) => quarters[i].slice(-4),
    series: [{ name: 'Off-plan', color: C.offplan, values: m.prices.map((p) => p.offplan) },
      { name: 'Ready', color: C.ready, values: m.prices.map((p) => p.ready) }],
    tipFormat: (v) => `AED ${whole(v)}`, label: 'Typical price per square metre each quarter, off-plan and ready.' });

  // map, with a switch between two readings of the same areas
  $('map-title').textContent = `Where sales are expected, ${m.forecast_quarter}`;
  const detail = (a) => [['expected sales', whole(a.forecast)]]
    .concat(a.low !== null ? [['rough range', `${whole(a.low)} – ${whole(a.high)}`]] : [])
    .concat(a.change !== null ? [[`on ${m.quarter}`, signed(a.change)]] : [])
    .concat([['direction', a.direction || 'too few sales to say']]).concat(a.dld ? [['DLD name', a.dld]] : []);
  const scale = classes(m.areas.map((a) => a.forecast));
  const swatch = (colour, text, hollow) => {
    const box = el('i', 'swatch');
    box.style.background = hollow ? C.surface : colour;
    if (hollow) box.style.border = `1px solid ${C.muted}`;
    return fill(el('span'), [box, document.createTextNode(text)]);
  };
  const drawMap = (mode) => {
    const colour = (a) => mode === 'sales' ? RAMP[scale.of(a.forecast)] : a.direction ? C[a.direction] : C.steady;
    Charts.map($('market-map'), { base: baseMap, shapes: baseMap.communities.features,
      label: `Map of Dubai with ${m.areas.length} areas shaded by ${mode === 'sales' ? 'expected sales' : 'direction'}.`,
      points: m.areas.map((a, i) => ({ area: a.area, lat: a.lat, lon: a.lon, size: a.forecast, color: colour(a), ring: mode === 'direction' && !a.direction,
        name: a.name, detail: detail(a), label: i < 8 ? a.name : null })) });
    $('map-note').textContent = mode === 'sales' ? 'Each area is shaded by the number of homes expected to sell.'
      : 'Each area is shaded by how it moved over the last year.';
    const e = scale.edges;
    fill($('map-legend'), mode === 'sales'
      ? RAMP.slice(0, e.length + 1).map((colour, i) => swatch(colour, i === 0 ? `under ${whole(e[0])}` : i === e.length ? `${whole(e[i - 1])}+` : `${whole(e[i - 1])}–${whole(e[i])}`))
        .concat([swatch(null, 'no forecast', true)])
      : [['rising', 'Rising'], ['steady', 'Steady'], ['falling', 'Falling']].map(([key, text]) => swatch(C[key], text))
        .concat([swatch(null, 'too few sales to say', true)]));
  };
  redrawMarketMap = drawMap;      // the mode switch (wired once, in start) always calls the latest one
  drawMap(document.querySelector('.switch button[aria-pressed="true"]').dataset.mode);

  const top = m.areas.slice(0, 8), widest = Math.max(...top.map((a) => a.high ?? a.forecast));
  $('busiest-note').textContent = `Homes expected to sell in ${m.forecast_quarter}, with the change on ${m.quarter}`;
  fill($('busiest'), top.map((a, i) => {
    const name = fill(el('span', 'rank-name'), [document.createTextNode(a.name)].concat(a.dld ? [el('small', '', a.dld)] : []));
    const value = fill(el('span', 'rank-value'), [document.createTextNode(whole(a.forecast))].concat(a.change !== null ? [el('small', '', signed(a.change))] : []));
    const bar = el('div', 'rank-bar');
    bar.append(el('i', 'rank-track'));
    if (a.low !== null) {
      const range = el('i', 'rank-range');
      range.style.left = `${100 * a.low / widest}%`;
      range.style.width = `${100 * (a.high - a.low) / widest}%`;
      bar.append(range);
    }
    const dot = el('i', 'rank-dot');
    dot.style.left = `${100 * a.forecast / widest}%`;
    bar.append(dot);
    return fill(el('div', 'rank'), [el('span', 'rank-no', String(i + 1)), name, value, bar]);
  }));
  const check = m.forecast_check;
  $('forecast-note').textContent = check.inside === null ? 'The dot is the forecast. These are rough sizes.'
    : `The dot is the forecast and the band is its rough range. On past quarters about ${percent(check.inside)} of forecasts landed inside such a band.`;

  const history = m.direction_history, last = history[history.length - 1];
  $('direction-note').textContent = `Share of areas each quarter. In ${last.quarter}: ${last.steady} steady, ${last.rising} rising, ${last.falling} falling.`;
  Charts.shares($('direction-chart'), {
    labels: history.map((h) => h.quarter), xTicks: yearTicks(history.map((h) => h.quarter), (q) => q.startsWith('Jan')),
    parts: [{ name: 'Falling', color: C.falling, values: history.map((h) => h.falling) },
      { name: 'Steady', color: C.steady, values: history.map((h) => h.steady) },
      { name: 'Rising', color: C.rising, values: history.map((h) => h.rising) }],
    tickText: (i) => history[i].quarter.slice(-4), label: 'Share of areas rising, steady and falling each quarter since 2020.' });
}

function showPlan(plan, backtest, m) {
  $('plan-kicker').textContent = `Team plan · ${m.forecast_quarter}`;
  $('plan-headline').textContent = `${plan.agents} agents across ${plan.areas} areas`;
  const split = el('div', 'split-bar');
  for (const [count, colour] of [[plan.offplan_agents, C.offplan], [plan.ready_agents, C.ready]]) {
    const part = el('i');
    part.style.width = `${100 * count / plan.agents}%`;
    part.style.background = colour;
    split.append(part);
  }
  const splitTile = tile('Off-plan / ready agents', `${plan.offplan_agents} / ${plan.ready_agents}`, '');
  splitTile.append(split);
  fill($('plan-tiles'), [
    tile('Expected commission', millions(plan.commission), 'for the quarter, an estimate'),
    tile('Expected deals', whole(plan.deals), `about ${(plan.deals / plan.agents).toFixed(1)} per agent`),
    tile('Areas covered', String(plan.areas), `of ${new Set(plan.segments.map((s) => s.name)).size} considered`),
    splitTile]);

  Charts.map($('plan-map'), { base: baseMap, shapes: baseMap.communities.features, maxRadius: 20, height: 520,
    label: `Map of Dubai with the ${plan.areas} areas in the plan shaded.`,
    points: m.areas.map((a) => ({ area: a.area, lat: a.lat, lon: a.lon, size: a.agents, color: a.agents ? C.pick : C.other, ring: !a.agents,
      name: a.name, label: a.agents ? `${a.name} (${a.agents})` : null,
      detail: [['agents', String(a.agents)], ['expected sales', whole(a.forecast)]].concat(a.dld ? [['DLD name', a.dld]] : []) })) });

  fill($('plan-picks'), plan.cards.map((card) => {
    const single = card.teams.length === 1;
    const kind = single ? (card.teams[0].type === 'Ready' ? 'ready' : 'off-plan')
      : card.teams.map((t) => `${t.agents} ${t.type === 'Ready' ? 'ready' : 'off-plan'}`).join(' + ');
    const deal = single ? millions(card.deal_low) : `${millions(card.deal_low)}–${(card.deal_high / 1e6).toFixed(1)}M`;
    const count = el('span', 'pick-count', String(card.agents));
    count.title = `${card.agents} agents`;
    return fill(el('div', 'pick'), [count, el('span', 'pick-name', card.name), el('span', 'pick-money', money(card.commission)),
      el('span', 'pick-why', `${kind} · about ${whole(card.sales)} sales · typical deal ${deal}${card.rising ? ' · rising' : ''}`),
      el('span', card.firm ? 'tag firm' : 'tag close', card.firm ? 'Firm' : 'Close call')]);
  }));

  Charts.scatter($('plan-scatter'), {
    xTitle: `Homes expected to sell, ${m.forecast_quarter}`, yTitle: 'Typical deal, AED', yFormat: (v) => `${+(v / 1e6).toFixed(1)}M`,
    strongName: 'In the plan', weakName: 'Not chosen',
    label: `Scatter of ${plan.segments.length} area segments by expected sales and typical deal value; the ones in the plan are highlighted.`,
    points: plan.segments.map((s) => ({ x: s.sales, y: s.deal, strong: s.agents > 0, color: s.agents > 0 ? C.pick : C.other,
      name: `${s.name} · ${s.type === 'Ready' ? 'ready' : 'off-plan'}`, label: s.agents > 0 ? s.name : null,
      detail: [['expected sales', whole(s.sales)], ['typical deal', millions(s.deal)], ['agents', String(s.agents)]] })) });

  const curve = plan.team_curve;
  if (curve.length > 1) {
    Charts.line($('team-chart'), { labels: curve.map((c) => `${c.agents} agents`), xTicks: curve.map((_, i) => i), xValues: curve.map((c) => c.agents),
      series: [{ name: 'Expected commission', color: C.pick, values: curve.map((c) => c.commission) }],
      tickText: (i) => String(curve[i].agents), tipFormat: millions,
      label: 'Expected commission per quarter for team sizes from 5 to 50 agents.' });
    const first = curve[0], second = curve[1], lastTwo = curve.slice(-2);
    const early = (second.commission - first.commission) / (second.agents - first.agents);
    const late = (lastTwo[1].commission - lastTwo[0].commission) / (lastTwo[1].agents - lastTwo[0].agents);
    $('team-note').textContent = `Each extra agent adds less: about ${money(early)} a quarter going from ${first.agents} to ${second.agents} agents, ` +
      `and about ${money(late)} going from ${lastTwo[0].agents} to ${lastTwo[1].agents}.`;
  }

  $('backtest-note').textContent = `Share of the best possible commission, average of the last ${backtest.quarters} quarters`;
  Charts.bars($('backtest-chart'), { max: 1, label: 'Share of the best possible commission by planning method.',
    rows: backtest.methods.map((method, i) => ({ label: method.label, value: method.share, text: percent(method.share), color: i === 0 ? C.pick : C.other })) });

  const a = plan.assumptions, pct = (x) => `${+(x * 100).toFixed(1)}%`;
  fill($('plan-assumptions'), [['Agents', a.agents], ['Deals per agent each quarter', a.deals_per_agent], ['Commission on ready', pct(a.ready_rate)],
    ['Commission on off-plan', pct(a.offplan_rate)], ['Largest share of an area\'s sales a team can win', pct(a.market_share)]]
    .flatMap(([term, value]) => [el('dt', '', term), el('dd', '', String(value))]));
}

// ---- What if ----
const marketWords = (v) => v === 0 ? 'as forecast' : `${Math.abs(v)}% ${v < 0 ? 'lower' : 'higher'}`;
function syncOutputs() {
  $('agents-out').textContent = $('agents').value;
  $('deals-out').textContent = $('deals').value;
  for (const id of ['offplan-change', 'ready-change']) $(`${id}-out`).textContent = marketWords(Number($(id).value));
}
function setForm(a) {
  $('agents').value = a.agents;
  $('deals').value = a.deals_per_agent;
  $('ready-rate').value = +(a.ready_rate * 100).toFixed(1);
  $('offplan-rate').value = +(a.offplan_rate * 100).toFixed(1);
  $('offplan-change').value = 0;
  $('ready-change').value = 0;
  syncOutputs();
}
function scenario(sent, saved) {
  const parts = [];
  const market = (label, v) => { if (v) parts.push(`${label} sales ${v < 0 ? 'fall' : 'rise'} ${Math.abs(Math.round(v * 100))}%`); };
  market('off-plan', sent.offplan_change);
  market('ready', sent.ready_change);
  if (sent.agents !== saved.agents) parts.push(`you have ${sent.agents} agents`);
  if (sent.deals_per_agent !== saved.deals_per_agent) parts.push(`each agent closes ${sent.deals_per_agent} deals`);
  if (Math.abs(sent.ready_rate - saved.ready_rate) > 1e-9 || Math.abs(sent.offplan_rate - saved.offplan_rate) > 1e-9) parts.push('commission rates change');
  return parts.length ? `If ${parts.join(' and ')}` : 'With the saved numbers';
}
let lastWhatIf = null;
function showWhatIf(result, sent, saved) {
  lastWhatIf = [result, sent, saved];
  const { plan, compare } = result, change = compare.commission_change;
  const moneyLine = Math.abs(change) < 0.005 ? 'Expected commission stays about the same.'
    : `Expected commission ${change < 0 ? 'drops' : 'rises'} by ${percent(change)}.`;
  let what, more;
  if (plan.agents !== saved.agents) {
    what = `A team of ${plan.agents} would work in ${plan.areas} areas.`;
    more = `${moneyLine} The comparison is with the saved plan for ${saved.agents} agents.`;
  } else if (compare.moved === 0) {
    what = 'The plan stays the same.';
    more = `No agent needs to move. ${moneyLine}`;
  } else if (compare.moved <= plan.agents / 5) {
    what = `The plan barely changes: ${compare.moved} of ${plan.agents} agents move.`;
    more = `The same areas stay the best ones. ${moneyLine}`;
  } else {
    what = `The plan changes: ${compare.moved} of ${plan.agents} agents move.`;
    more = moneyLine;
  }
  const verdict = fill(el('article', 'panel verdict'), [el('span', 'verdict-when', scenario(sent, saved)),
    el('p', 'verdict-what', what), el('p', 'verdict-more', more)]);
  const tiles = fill(el('div', 'tiles pair-tiles'), [
    tile('Expected commission', millions(plan.commission), Math.abs(change) < 0.005 ? 'same as the saved plan' : ` from ${millions(compare.commission_before)}`, { change }),
    plan.agents === saved.agents ? tile('Agents in a new place', `${compare.moved} of ${plan.agents}`, `${plan.areas} areas in this plan`)
      : tile('Team', `${plan.agents} agents`, `${plan.areas} areas · the saved plan has ${saved.agents} agents`)]);
  const chart = el('div', 'chart');
  const panel = fill(el('article', 'panel'), [
    fill(el('header', 'panel-head'), [fill(el('div'), [el('h2', '', 'Agents per area'), el('p', 'note', 'Areas that change are in bold.')])]), chart]);
  fill($('whatif-results'), [verdict, tiles, panel]);
  Charts.dumbbell(chart, { rows: compare.rows.map((r) => ({ label: r.name, before: r.before, after: r.after })),
    colors: { before: C.other, after: C.pick }, label: 'Agents per area in the saved plan and in this plan.' });
}

async function getJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

// Small line icons for the theme button, drawn as SVG so they take the text colour.
function icon(name) {
  const NS = 'http://www.w3.org/2000/svg';
  const root = document.createElementNS(NS, 'svg');
  for (const [k, v] of Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 2,
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' })) root.setAttribute(k, v);
  const shapes = name === 'moon' ? [['path', { d: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z' }]]
    : [['circle', { cx: 12, cy: 12, r: 4 }], ['path', { d: 'M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4' }]];
  for (const [tag, attrs] of shapes) {
    const part = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) part.setAttribute(k, v);
    root.append(part);
  }
  return root;
}

async function start() {
  readTheme();
  let data;
  try {
    [data, baseMap] = await Promise.all([getJson('/api/summary'), getJson('/api/map')]);
  } catch (error) {
    $('status').textContent = `The results could not be loaded. ${error.message || ''}`;
    $('status').className = 'status error';
    return;
  }
  $('status').hidden = true;
  const saved = data.plan.assumptions;
  setForm(saved);
  for (const id of ['agents', 'deals', 'offplan-change', 'ready-change']) $(id).addEventListener('input', syncOutputs);
  const empty = $('whatif-empty');
  $('whatif-reset').addEventListener('click', () => { setForm(saved); lastWhatIf = null; fill($('whatif-results'), [empty]); });
  $('whatif-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const sent = { agents: Number($('agents').value), deals_per_agent: Number($('deals').value),
      ready_rate: Number($('ready-rate').value) / 100, offplan_rate: Number($('offplan-rate').value) / 100,
      ready_change: Number($('ready-change').value) / 100, offplan_change: Number($('offplan-change').value) / 100 };
    const button = $('whatif-submit');
    button.disabled = true;
    button.textContent = 'Working out the plan…';
    try {
      showWhatIf(await getJson('/api/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sent) }), sent, saved);
    } catch (error) {
      fill($('whatif-results'), [fill(el('article', 'panel'), [el('h2', '', 'That plan could not be worked out'),
        el('p', 'note', error.message || 'Please try again.')])]);
    } finally {
      button.disabled = false;
      button.textContent = 'Update the plan';
    }
  });

  // Charts measure their container, so a screen is drawn the first time it is shown.
  const drawn = new Set();
  const draw = { market: () => showMarket(data.market), plan: () => showPlan(data.plan, data.backtest, data.market), whatif: () => {} };
  const current = () => (['market', 'plan', 'whatif'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'market');
  const show = () => {
    const tab = current();
    for (const section of document.querySelectorAll('.screen')) section.hidden = section.id !== tab;
    for (const link of document.querySelectorAll('.tabs a')) {
      if (link.dataset.tab === tab) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    }
    if (!drawn.has(tab)) { drawn.add(tab); draw[tab](); }
    window.scrollTo(0, 0);
  };
  for (const button of document.querySelectorAll('.switch button')) {
    button.addEventListener('click', () => {
      for (const other of document.querySelectorAll('.switch button')) other.setAttribute('aria-pressed', String(other === button));
      redrawMarketMap(button.dataset.mode);
    });
  }

  // Light and dark: redraw what is on screen in the new colours; other screens redraw when next shown.
  const themeButton = $('theme');
  const labelTheme = () => {
    const isDark = document.documentElement.dataset.theme === 'dark';
    themeButton.setAttribute('aria-pressed', String(isDark));
    themeButton.setAttribute('aria-label', isDark ? 'Switch to light mode' : 'Switch to dark mode');
    themeButton.replaceChildren(icon(isDark ? 'sun' : 'moon'), document.createTextNode(isDark ? 'Light' : 'Dark'));
  };
  themeButton.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('theme', next); } catch (error) { /* private window: the choice lasts this visit only */ }
    labelTheme();
    readTheme();
    drawn.clear();
    drawn.add(current());
    draw[current()]();
    if (lastWhatIf) showWhatIf(...lastWhatIf);
  });
  labelTheme();

  $('cutoff').textContent = `Official DLD records to ${data.market.cutoff}`;
  window.addEventListener('hashchange', show);
  show();
}
start();
