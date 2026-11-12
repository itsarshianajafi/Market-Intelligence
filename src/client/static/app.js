// Client view. The server sends plain facts; this file only lays them out.
'use strict';

const $ = (id) => document.getElementById(id);
const whole = (n) => Math.round(n).toLocaleString('en-US');
const percent = (x) => `${Math.abs(Math.round(x * 100))}%`;
const money = (aed) => aed >= 1e6 ? `AED ${(aed / 1e6).toFixed(aed >= 1e7 ? 1 : 2).replace(/\.?0+$/, '')}M`
  : `AED ${Math.round(aed / 1e3)}K`;
const millions = (aed) => `AED ${(aed / 1e6).toFixed(1)}M`;
const shortQuarter = (name) => name.replace(/ 20(\d\d)$/, ' $1');

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
function stat(label, value, note, down) {
  return fill(el('div', 'stat'), [el('span', 'stat-label', label), el('span', 'stat-value', value),
    el('span', down ? 'stat-note down' : 'stat-note', note)]);
}
const moved = (x) => `${x < 0 ? 'Down' : 'Up'} ${percent(x)}`;

function showMarket(m) {
  $('cutoff').textContent = `Dubai home sales, from official DLD records up to ${m.cutoff}`;
  $('market-eyebrow').textContent = `${m.quarter}, the last full quarter`;
  const direction = m.total.change < 0 ? 'down' : 'up';
  fill($('market-headline'), [document.createTextNode(`Sales are ${direction} `),
    el('span', direction === 'down' ? 'down' : '', percent(m.total.change)), document.createTextNode(' on last year')]);
  $('market-lead').textContent = `${whole(m.total.sales)} homes were sold in ${m.quarter}, against ${whole(m.total.before)} a year earlier.`;
  fill($('market-stats'), [
    stat(`Homes sold, ${m.quarter}`, whole(m.total.sales), `${moved(m.total.change)} on a year earlier`, m.total.change < 0),
    stat('Off-plan homes', whole(m.offplan.sales), moved(m.offplan.change), m.offplan.change < 0),
    stat('Ready homes', whole(m.ready.sales), moved(m.ready.change), m.ready.change < 0)]);

  const tallest = Math.max(...m.history.map((q) => q.offplan + q.ready));
  const height = (n) => `${Math.round(220 * n / tallest)}px`;
  const peak = m.history.reduce((a, b) => (a.offplan + a.ready > b.offplan + b.ready ? a : b));
  $('market-bars').setAttribute('aria-label', `Homes sold per quarter from ${m.history[0].quarter} to ${m.quarter}. ` +
    `The highest was ${whole(peak.offplan + peak.ready)} in ${peak.quarter}; ${m.quarter} had ${whole(m.total.sales)}.`);
  fill($('market-bars'), m.history.map((q) => {
    const ready = el('div', 'bar-part ready'), offplan = el('div', 'bar-part offplan');
    ready.style.height = height(q.ready);
    offplan.style.height = height(q.offplan);
    return fill(el('div', 'bar'), [el('span', 'bar-total', whole(q.offplan + q.ready)), ready, offplan,
      el('span', 'bar-label', shortQuarter(q.quarter))]);
  }));

  const d = m.direction, judged = d.steady + d.rising + d.falling;
  const most = Object.entries(d).sort((a, b) => b[1] - a[1])[0][0];
  $('direction-title').textContent = { steady: 'Most areas are holding steady', rising: 'Most areas are rising', falling: 'Most areas are falling' }[most];
  $('direction-note').textContent = `Each area is checked on its prices and sales over the last year. ${judged} had enough sales to judge.`;
  fill($('direction-meters'), [['Steady', 'steady'], ['Rising', 'rising'], ['Falling', 'falling']].map(([label, key]) => {
    const bar = el('div', `meter-fill ${key}`);
    bar.style.width = `${100 * d[key] / Math.max(judged, 1)}%`;
    return fill(el('div', 'meter'), [el('span', 'meter-name', label), fill(el('div', 'meter-track'), [bar]),
      el('span', 'meter-value', String(d[key]))]);
  }));

  $('busiest-title').textContent = `Where sales are expected, ${m.forecast_quarter}`;
  const biggest = Math.max(...m.busiest.map((a) => a.forecast));
  fill($('busiest-rows'), m.busiest.map((a) => {
    const name = fill(el('div', 'area-name'), [el('strong', '', a.name)].concat(a.dld ? [el('span', '', `DLD: ${a.dld}`)] : []));
    const bar = el('div', 'area-fill');
    bar.style.width = `${100 * a.forecast / biggest}%`;
    const change = a.change === null ? '' : Math.abs(a.change) < 0.005 ? 'no change' : `${a.change < 0 ? '−' : '+'}${percent(a.change)}`;
    const value = fill(el('div', 'area-value'), [el('strong', '', whole(a.forecast)), document.createTextNode(' '),
      el('span', a.change !== null && a.change <= -0.1 ? 'down' : '', change)]);
    return fill(el('div', 'area-row'), [name, fill(el('div', 'area-track'), [bar]), value]);
  }));
  const check = m.forecast_check;
  $('forecast-note').textContent = check.inside === null ? 'These are rough sizes.'
    : `These are rough sizes. On past quarters, about ${percent(check.inside)} of the time real sales landed between ` +
      `${percent(Math.expm1(check.low))} below and ${percent(Math.expm1(check.high))} above the forecast.`;
}

function pickCard(card) {
  const single = card.teams.length === 1;
  const count = fill(el('div', single && card.teams[0].type === 'Ready' ? 'pick-count ready' : 'pick-count'),
    [el('strong', '', String(card.agents)), el('span', '', card.agents === 1 ? 'agent' : 'agents')]);
  const kind = single ? card.teams[0].type.replace('Off-Plan', 'Off-plan')
    : card.teams.map((t) => `${t.agents} on ${t.type === 'Ready' ? 'ready' : 'off-plan'}`).join(', ');
  const deal = single ? `A typical deal is ${millions(card.deal_low)}.`
    : `Deals here are around ${millions(card.deal_low)} to ${millions(card.deal_high)}.`;
  const sales = single ? `${whole(card.sales)} ${card.teams[0].type === 'Ready' ? 'ready' : 'off-plan'} sales` : `${whole(card.sales)} sales`;
  const body = fill(el('div', 'pick-body'), [
    el('h2', '', card.name), el('span', 'pick-sub', card.dld ? `${kind} · DLD: ${card.dld}` : kind),
    el('p', 'pick-why', `About ${sales} expected${card.rising ? ', and the area is rising' : ''}. ${deal}`),
    fill(el('div', 'pick-foot'), [el('span', '', `${money(card.commission)} commission`),
      el('span', card.firm ? 'tag firm' : 'tag close', card.firm ? 'Firm pick' : 'Close call')])]);
  return fill(el('article', 'card pick'), [count, body]);
}

function showPlan(plan, backtest, quarter) {
  $('plan-eyebrow').textContent = `Team plan for ${quarter}`;
  $('plan-headline').textContent = `Put ${plan.agents} agents in these ${plan.areas} areas`;
  fill($('plan-stats'), [
    stat('Expected commission', millions(plan.commission), 'for the quarter, an estimate'),
    stat('Expected deals', whole(plan.deals), `about ${(plan.deals / plan.agents).toFixed(1)} per agent`),
    stat('Off-plan and ready', `${plan.offplan_agents} and ${plan.ready_agents}`, 'agents on each')]);
  const key = fill(el('aside', 'card key'), [el('h2', '', 'How to read the tags'),
    el('p', '', 'Firm pick: still chosen when the forecast is shaken by its past mistakes.'),
    el('p', '', 'Close call: a good choice, but another area could take its place if sales come in differently.'),
    el('p', '', 'Blue squares are off-plan teams and green squares are ready teams.')]);
  fill($('plan-cards'), plan.cards.map(pickCard).concat([key]));
  const a = plan.assumptions;
  $('plan-assumptions').textContent = `${a.agents} agents · ${a.deals_per_agent} deals per agent each quarter · ` +
    `${+(a.ready_rate * 100).toFixed(1)}% commission on ready and ${+(a.offplan_rate * 100).toFixed(1)}% on off-plan · ` +
    `a team can win up to ${+(a.market_share * 100).toFixed(1)}% of an area's sales.`;
  $('plan-evidence').textContent = `Tested on the last ${backtest.quarters} quarters: plans made this way earned ${percent(backtest.optimiser)} ` +
    `of the best possible commission. Splitting agents in proportion to forecast value earned ${percent(backtest.rule)}.`;
}

// ---- What if ----
const marketWords = (v) => v === 0 ? 'as forecast' : `${Math.abs(v)}% ${v < 0 ? 'lower' : 'higher'}`;
function syncOutputs() {
  $('agents-out').textContent = $('agents').value;
  $('deals-out').textContent = $('deals').value;
  for (const id of ['offplan-change', 'ready-change']) {
    const value = Number($(id).value);
    $(`${id}-out`).textContent = marketWords(value);
    $(`${id}-out`).className = value < 0 ? 'down' : '';
  }
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
function showWhatIf(result, sent, saved) {
  const { plan, compare } = result, change = compare.commission_change;
  const money_line = Math.abs(change) < 0.005 ? 'Expected commission stays about the same.'
    : `Expected commission ${change < 0 ? 'drops' : 'rises'} by ${percent(change)}.`;
  let what, more;
  if (plan.agents !== saved.agents) {
    what = `A team of ${plan.agents} would work in ${plan.areas} areas.`;
    more = `${money_line} The comparison is with the saved plan for ${saved.agents} agents.`;
  } else if (compare.moved === 0) {
    what = 'The plan stays the same.';
    more = `No agent needs to move. ${money_line}`;
  } else if (compare.moved <= plan.agents / 5) {
    what = `The plan barely changes: ${compare.moved} of ${plan.agents} agents move.`;
    more = `The same areas stay the best ones. ${money_line}`;
  } else {
    what = `The plan changes: ${compare.moved} of ${plan.agents} agents move.`;
    more = money_line;
  }
  const verdict = fill(el('div', 'verdict'), [el('span', 'verdict-when', scenario(sent, saved)),
    el('p', 'verdict-what', what), el('p', 'verdict-more', more)]);
  const stats = fill(el('div', 'stats'), [
    stat('Expected commission', millions(plan.commission),
      Math.abs(change) < 0.005 ? `Same as the saved plan` : `${moved(change)} from ${millions(compare.commission_before)}`, change <= -0.005),
    stat('Agents in a new place', `${compare.moved} of ${plan.agents}`, `${plan.areas} areas in this plan`)]);
  const rows = compare.rows.map((r) => {
    const diff = r.after - r.before;
    const words = diff === 0 ? 'Same' : r.before === 0 ? `New: ${r.after} agents` : r.after === 0 ? 'No longer used'
      : `${Math.abs(diff)} ${Math.abs(diff) === 1 ? 'agent' : 'agents'} ${diff < 0 ? 'fewer' : 'more'}`;
    return fill(el('div', 'compare-row'), [el('strong', '', r.name), el('span', 'num', String(r.before)),
      el('span', 'num after', String(r.after)), el('span', diff === 0 ? 'change' : diff < 0 ? 'change less' : 'change more', words)]);
  });
  const table = fill(el('div', 'card compare'), [el('h2', '', 'Agents per area, saved plan and this one'),
    fill(el('div', 'compare-head'), [el('span', '', 'Area'), el('span', 'num', 'Saved'), el('span', 'num', 'Now'), el('span', '', 'Change')]),
    ...rows]);
  fill($('whatif-results'), [verdict, stats, table]);
}

async function start() {
  let data;
  try {
    const response = await fetch('/api/summary');
    data = await response.json();
    if (!response.ok) throw new Error(data.error);
  } catch (error) {
    $('status').textContent = `The results could not be loaded. ${error.message || ''}`;
    $('status').className = 'status error';
    return;
  }
  $('status').hidden = true;
  showMarket(data.market);
  showPlan(data.plan, data.backtest, data.market.forecast_quarter);
  $('market-next').textContent = `So where should your team work in ${data.market.forecast_quarter}? See the plan for ${data.plan.agents} agents.`;
  const saved = data.plan.assumptions;
  setForm(saved);

  for (const id of ['agents', 'deals', 'offplan-change', 'ready-change']) $(id).addEventListener('input', syncOutputs);
  const empty = $('whatif-empty');
  $('whatif-reset').addEventListener('click', () => { setForm(saved); fill($('whatif-results'), [empty]); });
  $('whatif-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const sent = { agents: Number($('agents').value), deals_per_agent: Number($('deals').value),
      ready_rate: Number($('ready-rate').value) / 100, offplan_rate: Number($('offplan-rate').value) / 100,
      ready_change: Number($('ready-change').value) / 100, offplan_change: Number($('offplan-change').value) / 100 };
    const button = $('whatif-submit');
    button.disabled = true;
    button.textContent = 'Working out the plan…';
    try {
      const response = await fetch('/api/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sent) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      showWhatIf(result, sent, saved);
    } catch (error) {
      fill($('whatif-results'), [fill(el('div', 'card'), [el('h2', '', 'That plan could not be worked out'),
        el('p', 'muted', error.message || 'Please try again.')])]);
    } finally {
      button.disabled = false;
      button.textContent = 'Update the plan';
    }
  });

  const show = () => {
    const tab = ['market', 'plan', 'whatif'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'market';
    for (const section of document.querySelectorAll('.screen')) section.hidden = section.id !== tab;
    for (const link of document.querySelectorAll('.tabs a')) {
      if (link.dataset.tab === tab) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    }
    window.scrollTo(0, 0);
  };
  window.addEventListener('hashchange', show);
  show();
}
start();
