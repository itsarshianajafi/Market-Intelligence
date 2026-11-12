// Small SVG charts for the client view. No library: each chart is a function that draws into a
// container at its current width and redraws when the width changes.
'use strict';

const Charts = (() => {
  const NS = 'http://www.w3.org/2000/svg';
  const INK = '#17202A', MUTED = '#66717F', GRID = '#E6E9EE', AXIS = '#C5CCD4', SURFACE = '#FFFFFF';

  function svg(tag, attrs = {}, text) {
    const node = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function html(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Redraw at the container's real width, so text keeps its size on a phone.
  function mount(container, draw) {
    let last = 0;
    const run = () => {
      const width = Math.floor(container.clientWidth);
      if (width > 0 && width !== last) { last = width; container.replaceChildren(draw(width)); }
    };
    new ResizeObserver(run).observe(container);
    run();
  }

  // ---- one shared tooltip ----
  const tip = html('div', 'tip');
  tip.hidden = true;
  document.addEventListener('DOMContentLoaded', () => document.body.append(tip));
  function showTip(event, title, rows) {
    tip.replaceChildren(html('div', 'tip-title', title), ...rows.map(([label, value, color]) => {
      const row = html('div', 'tip-row');
      if (color) { const key = html('i', 'tip-key'); key.style.background = color; row.append(key); }
      row.append(html('strong', '', value), html('span', '', label));
      return row;
    }));
    tip.hidden = false;
    const box = tip.getBoundingClientRect();
    const x = Math.min(event.clientX + 14, window.innerWidth - box.width - 8);
    const y = event.clientY - box.height - 12 < 8 ? event.clientY + 16 : event.clientY - box.height - 12;
    tip.style.left = `${Math.max(8, x)}px`;
    tip.style.top = `${y}px`;
  }
  const hideTip = () => { tip.hidden = true; };

  // ---- scales and ticks ----
  function niceTicks(max, count = 4) {
    const rough = max / count, power = 10 ** Math.floor(Math.log10(rough));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough);
    const ticks = [];
    for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(v);
    if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
    return ticks;
  }
  const compact = (n) => n >= 1e6 ? `${+(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}K` : Math.round(n).toLocaleString('en-US');
  const whole = (n) => Math.round(n).toLocaleString('en-US');

  function frame(width, height, margin) {
    const root = svg('svg', { width, height, viewBox: `0 0 ${width} ${height}`, role: 'img' });
    return { root, left: margin.left, top: margin.top, w: width - margin.left - margin.right, h: height - margin.top - margin.bottom };
  }
  function yAxis(f, ticks, y, format) {
    for (const t of ticks) {
      f.root.append(svg('line', { x1: f.left, x2: f.left + f.w, y1: y(t), y2: y(t), stroke: t === 0 ? AXIS : GRID, 'stroke-width': 1 }));
      f.root.append(svg('text', { x: f.left - 8, y: y(t) + 4, 'text-anchor': 'end', fill: MUTED, 'font-size': 12 }, format(t)));
    }
  }

  // ---- line chart: one or more series over ordered points, crosshair tooltip ----
  // series: [{name, color, values:[number]}], labels: [string] (same length), ticks: indexes to label on x
  function line(container, { series, labels, xTicks, xValues, tickText = (i) => labels[i], format = compact, tipFormat = whole, height = 260, label }) {
    mount(container, (width) => {
      const f = frame(width, height, { left: 48, right: 16, top: 12, bottom: 28 });
      f.root.setAttribute('aria-label', label);
      const ticks = niceTicks(Math.max(...series.flatMap((s) => s.values)));
      const top = ticks[ticks.length - 1], n = labels.length;
      // xValues places points by their real value (team sizes 30, 40, 50 are not equal steps); otherwise they are evenly spaced
      const at = xValues || labels.map((_, i) => i), span = at[n - 1] - at[0] || 1;
      const x = (i) => f.left + (n === 1 ? f.w / 2 : f.w * (at[i] - at[0]) / span);
      const y = (v) => f.top + f.h * (1 - v / top);
      yAxis(f, ticks, y, format);
      for (const i of xTicks) {
        f.root.append(svg('text', { x: x(i), y: f.top + f.h + 18, 'text-anchor': i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle',
          fill: MUTED, 'font-size': 12 }, tickText(i)));
      }
      for (const s of series) {
        f.root.append(svg('path', { d: s.values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(''),
          fill: 'none', stroke: s.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
        f.root.append(svg('circle', { cx: x(n - 1), cy: y(s.values[n - 1]), r: 4, fill: s.color, stroke: SURFACE, 'stroke-width': 2 }));
      }
      const cross = svg('line', { y1: f.top, y2: f.top + f.h, stroke: AXIS, 'stroke-width': 1, visibility: 'hidden' });
      const dots = series.map((s) => svg('circle', { r: 4, fill: s.color, stroke: SURFACE, 'stroke-width': 2, visibility: 'hidden' }));
      const hit = svg('rect', { x: f.left, y: f.top, width: f.w, height: f.h, fill: 'transparent' });
      hit.addEventListener('pointermove', (event) => {
        const box = f.root.getBoundingClientRect();
        const mx = event.clientX - box.left;
        const i = at.reduce((best, _, k) => (Math.abs(x(k) - mx) < Math.abs(x(best) - mx) ? k : best), 0);
        cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible');
        dots.forEach((dot, k) => { dot.setAttribute('cx', x(i)); dot.setAttribute('cy', y(series[k].values[i])); dot.setAttribute('visibility', 'visible'); });
        showTip(event, labels[i], series.map((s) => [s.name, tipFormat(s.values[i]), s.color]));
      });
      hit.addEventListener('pointerleave', () => { cross.setAttribute('visibility', 'hidden'); dots.forEach((d) => d.setAttribute('visibility', 'hidden')); hideTip(); });
      f.root.append(cross, ...dots, hit);
      return f.root;
    });
  }

  // ---- stacked columns, as shares of each column's total ----
  // parts: [{name, color, values:[number]}] bottom first
  function shares(container, { parts, labels, xTicks, tickText = (i) => labels[i], height = 220, label }) {
    mount(container, (width) => {
      const f = frame(width, height, { left: 40, right: 8, top: 8, bottom: 28 });
      f.root.setAttribute('aria-label', label);
      const n = labels.length, slot = f.w / n, bar = Math.min(24, slot - 2);
      const y = (v) => f.top + f.h * (1 - v);
      yAxis(f, [0, 0.5, 1], y, (t) => `${t * 100}%`);
      labels.forEach((name, i) => {
        const total = parts.reduce((sum, p) => sum + p.values[i], 0) || 1;
        let below = 0;
        const group = svg('g');
        for (const p of parts) {
          const share = p.values[i] / total;
          if (share > 0) {
            // 2px of surface between segments: shrink each one, never draw a border
            const top = y(below + share), heightPx = Math.max(0, y(below) - top - 2);
            group.append(svg('rect', { x: f.left + slot * i + (slot - bar) / 2, y: top + 1, width: bar, height: heightPx, fill: p.color }));
          }
          below += share;
        }
        const hit = svg('rect', { x: f.left + slot * i, y: f.top, width: slot, height: f.h, fill: 'transparent' });
        hit.addEventListener('pointermove', (event) => showTip(event, name,
          parts.slice().reverse().map((p) => [p.name, `${p.values[i]} (${Math.round(100 * p.values[i] / total)}%)`, p.color])));
        hit.addEventListener('pointerleave', hideTip);
        f.root.append(group, hit);
      });
      for (const i of xTicks) {
        f.root.append(svg('text', { x: f.left + slot * (i + 0.5), y: f.top + f.h + 18, 'text-anchor': 'middle', fill: MUTED, 'font-size': 12 }, tickText(i)));
      }
      return f.root;
    });
  }

  // ---- scatter on log axes; `strong` points are drawn last, larger and labelled ----
  // points: [{x, y, name, detail:[[label, value]], color, strong}]
  function scatter(container, { points, xTitle, yTitle, xFormat = compact, yFormat = compact, height = 320, label }) {
    mount(container, (width) => {
      const f = frame(width, height, { left: 60, right: 16, top: 12, bottom: 42 });
      f.root.setAttribute('aria-label', label);
      const range = (values) => [Math.log10(Math.min(...values) * 0.8), Math.log10(Math.max(...values) * 1.25)];
      const [x0, x1] = range(points.map((p) => p.x)), [y0, y1] = range(points.map((p) => p.y));
      const x = (v) => f.left + f.w * (Math.log10(v) - x0) / (x1 - x0);
      const y = (v) => f.top + f.h * (1 - (Math.log10(v) - y0) / (y1 - y0));
      const logTicks = (lo, hi) => [1, 2, 5].flatMap((m) => Array.from({ length: 9 }, (_, e) => m * 10 ** e))
        .filter((t) => Math.log10(t) >= lo && Math.log10(t) <= hi).sort((a, b) => a - b);
      for (const t of logTicks(y0, y1)) {
        f.root.append(svg('line', { x1: f.left, x2: f.left + f.w, y1: y(t), y2: y(t), stroke: GRID, 'stroke-width': 1 }));
        f.root.append(svg('text', { x: f.left - 8, y: y(t) + 4, 'text-anchor': 'end', fill: MUTED, 'font-size': 12 }, yFormat(t)));
      }
      const xt = logTicks(x0, x1);
      xt.forEach((t, i) => {
        if (width < 480 && i % 2) return;
        f.root.append(svg('line', { x1: x(t), x2: x(t), y1: f.top, y2: f.top + f.h, stroke: GRID, 'stroke-width': 1 }));
        f.root.append(svg('text', { x: x(t), y: f.top + f.h + 18, 'text-anchor': 'middle', fill: MUTED, 'font-size': 12 }, xFormat(t)));
      });
      f.root.append(svg('text', { x: f.left + f.w / 2, y: height - 4, 'text-anchor': 'middle', fill: MUTED, 'font-size': 12 }, xTitle));
      f.root.append(svg('text', { x: 12, y: f.top + f.h / 2, 'text-anchor': 'middle', fill: MUTED, 'font-size': 12,
        transform: `rotate(-90 12 ${f.top + f.h / 2})` }, yTitle));
      const ordered = points.slice().sort((a, b) => (a.strong ? 1 : 0) - (b.strong ? 1 : 0));
      const marks = ordered.map((p) => svg('circle', { cx: x(p.x), cy: y(p.y), r: p.strong ? 6 : 4, fill: p.color,
        'fill-opacity': p.strong ? 1 : 0.55, stroke: SURFACE, 'stroke-width': p.strong ? 2 : 1 }));
      f.root.append(...marks);
      const placed = [];
      for (const p of ordered.filter((q) => q.strong && q.label)) {       // label picks, skipping ones that would collide
        const px = x(p.x), py = y(p.y), right = px < f.left + f.w - 130;
        if (placed.some(([qx, qy]) => Math.abs(qx - px) < 110 && Math.abs(qy - py) < 14)) continue;
        placed.push([px, py]);
        f.root.append(svg('text', { x: right ? px + 10 : px - 10, y: py + 4, 'text-anchor': right ? 'start' : 'end', fill: INK,
          'font-size': 12, 'font-weight': 500, 'paint-order': 'stroke', stroke: SURFACE, 'stroke-width': 3 }, p.label));
      }
      const hit = svg('rect', { x: f.left, y: f.top, width: f.w, height: f.h, fill: 'transparent' });
      hit.addEventListener('pointermove', (event) => {        // nearest point wins: the pointer only has to be close
        const box = f.root.getBoundingClientRect(), mx = event.clientX - box.left, my = event.clientY - box.top;
        let best = null, distance = 28 ** 2;
        ordered.forEach((p, i) => { const d = (x(p.x) - mx) ** 2 + (y(p.y) - my) ** 2; if (d < distance) { distance = d; best = i; } });
        marks.forEach((m, i) => m.setAttribute('stroke', i === best ? INK : SURFACE));
        if (best === null) hideTip(); else showTip(event, ordered[best].name, ordered[best].detail);
      });
      hit.addEventListener('pointerleave', () => { marks.forEach((m) => m.setAttribute('stroke', SURFACE)); hideTip(); });
      f.root.append(hit);
      return f.root;
    });
  }

  // ---- map: coastline and roads as lines, one circle per area ----
  // points: [{lat, lon, size, color, name, detail, label, ring}]
  function map(container, { base, points, height = 440, label, maxRadius = 22 }) {
    mount(container, (width) => {
      const h = width < 520 ? 340 : height;
      const root = svg('svg', { width, height: h, viewBox: `0 0 ${width} ${h}`, role: 'img', 'aria-label': label });
      const lats = points.map((p) => p.lat), lons = points.map((p) => p.lon);
      const pad = 0.035, south = Math.min(...lats) - pad, north = Math.max(...lats) + pad;
      const west = Math.min(...lons) - pad, east = Math.max(...lons) + pad;
      const squeeze = Math.cos((south + north) / 2 * Math.PI / 180);      // a degree of longitude is shorter than one of latitude
      const scale = Math.min(width / ((east - west) * squeeze), h / (north - south));
      const ox = (width - (east - west) * squeeze * scale) / 2, oy = (h - (north - south) * scale) / 2;
      const X = (lon) => ox + (lon - west) * squeeze * scale, Y = (lat) => oy + (north - lat) * scale;
      const path = (ways) => ways.map((way) => way.map(([lon, lat], i) => `${i ? 'L' : 'M'}${X(lon).toFixed(1)},${Y(lat).toFixed(1)}`).join('')).join('');
      root.append(svg('rect', { width, height: h, fill: '#F7F9FB' }));
      root.append(svg('path', { d: path(base.roads), fill: 'none', stroke: '#DADFE6', 'stroke-width': 1.5, 'stroke-linejoin': 'round' }));
      root.append(svg('path', { d: path(base.coast), fill: 'none', stroke: '#9FB3C8', 'stroke-width': 1, 'stroke-linejoin': 'round' }));
      const biggest = Math.max(...points.map((p) => p.size), 1);
      const radius = (size) => Math.max(3.5, maxRadius * Math.sqrt(size / biggest));      // area, not radius, carries the value
      const ordered = points.slice().sort((a, b) => b.size - a.size);
      const marks = ordered.map((p) => svg('circle', { cx: X(p.lon), cy: Y(p.lat), r: radius(p.size), fill: p.color,
        'fill-opacity': p.ring ? 0 : 0.78, stroke: p.ring ? p.color : SURFACE, 'stroke-width': p.ring ? 1.5 : 1.5 }));
      root.append(...marks);
      const placed = [];
      for (const p of ordered.filter((q) => q.label)) {
        const px = X(p.lon), py = Y(p.lat), r = radius(p.size), right = px < width - 150;
        if (placed.some(([qx, qy]) => Math.abs(qx - px) < 110 && Math.abs(qy - py) < 13)) continue;
        placed.push([px, py]);
        root.append(svg('text', { x: right ? px + r + 5 : px - r - 5, y: py + 4, 'text-anchor': right ? 'start' : 'end', fill: INK,
          'font-size': 12, 'font-weight': 500, 'paint-order': 'stroke', stroke: '#F7F9FB', 'stroke-width': 3 }, p.label));
      }
      const hit = svg('rect', { width, height: h, fill: 'transparent' });
      hit.addEventListener('pointermove', (event) => {
        const box = root.getBoundingClientRect(), mx = event.clientX - box.left, my = event.clientY - box.top;
        let best = null, distance = Infinity;
        ordered.forEach((p, i) => {
          const d = Math.hypot(X(p.lon) - mx, Y(p.lat) - my) - radius(p.size);
          if (d < 14 && d < distance) { distance = d; best = i; }
        });
        marks.forEach((m, i) => m.setAttribute('stroke', i === best ? INK : ordered[i].ring ? ordered[i].color : SURFACE));
        if (best === null) hideTip(); else showTip(event, ordered[best].name, ordered[best].detail);
      });
      hit.addEventListener('pointerleave', () => { marks.forEach((m, i) => m.setAttribute('stroke', ordered[i].ring ? ordered[i].color : SURFACE)); hideTip(); });
      root.append(hit);
      return root;
    });
  }

  // ---- horizontal bars with the value at the tip ----
  // rows: [{label, value, color, text}]
  function bars(container, { rows, max, label }) {
    const list = html('div', 'hbars');
    list.setAttribute('role', 'img');
    list.setAttribute('aria-label', label);
    const top = max || Math.max(...rows.map((r) => r.value));
    for (const r of rows) {
      const fillBar = html('i', 'hbar-fill');
      fillBar.style.width = `${100 * r.value / top}%`;
      fillBar.style.background = r.color;
      const track = html('div', 'hbar-track');
      track.append(fillBar);
      const row = html('div', 'hbar');
      row.append(html('span', 'hbar-label', r.label), track, html('strong', 'hbar-value', r.text));
      list.append(row);
    }
    container.replaceChildren(list);
  }

  // ---- before and after on one line per row ----
  // rows: [{label, before, after}]
  function dumbbell(container, { rows, colors, label }) {
    mount(container, (width) => {
      const rowHeight = 34, left = Math.min(190, width * 0.42), right = 64;      // room for the '5 → 4' note after the last dot
      const height = rows.length * rowHeight + 30;
      const root = svg('svg', { width, height, viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': label });
      const top = Math.max(...rows.flatMap((r) => [r.before, r.after]), 1);
      const x = (v) => left + (width - left - right) * v / top;
      for (let v = 0; v <= top; v += top > 12 ? 5 : top > 6 ? 2 : 1) {
        root.append(svg('line', { x1: x(v), x2: x(v), y1: 22, y2: height - 4, stroke: v === 0 ? AXIS : GRID, 'stroke-width': 1 }));
        root.append(svg('text', { x: x(v), y: 14, 'text-anchor': 'middle', fill: MUTED, 'font-size': 12 }, String(v)));
      }
      rows.forEach((r, i) => {
        const y = 30 + rowHeight * i + rowHeight / 2;
        root.append(svg('text', { x: 0, y: y + 4, fill: INK, 'font-size': 13, 'font-weight': r.before !== r.after ? 600 : 400 },
          r.label.length > left / 7.2 ? `${r.label.slice(0, Math.floor(left / 7.2) - 1)}…` : r.label));
        if (r.before !== r.after) root.append(svg('line', { x1: x(r.before), x2: x(r.after), y1: y, y2: y, stroke: AXIS, 'stroke-width': 2 }));
        root.append(svg('circle', { cx: x(r.before), cy: y, r: 5, fill: SURFACE, stroke: colors.before, 'stroke-width': 2 }));
        root.append(svg('circle', { cx: x(r.after), cy: y, r: 5, fill: colors.after, stroke: SURFACE, 'stroke-width': 2 }));
        root.append(svg('text', { x: x(Math.max(r.before, r.after)) + 10, y: y + 4, fill: MUTED, 'font-size': 12 },
          r.before === r.after ? '' : `${r.before} → ${r.after}`));
        const hit = svg('rect', { x: 0, y: y - rowHeight / 2, width, height: rowHeight, fill: 'transparent' });
        hit.addEventListener('pointermove', (event) => showTip(event, r.label, [['saved plan', String(r.before)], ['this plan', String(r.after)]]));
        hit.addEventListener('pointerleave', hideTip);
        root.append(hit);
      });
      return root;
    });
  }

  // ---- tiny trend line for a stat tile (no axes, no tooltip: the tile's number is the value) ----
  function spark(values, color) {
    const w = 96, h = 28, max = Math.max(...values), min = Math.min(...values), span = max - min || 1;
    const root = svg('svg', { width: w, height: h, viewBox: `0 0 ${w} ${h}`, 'aria-hidden': 'true' });
    const x = (i) => 2 + (w - 8) * i / (values.length - 1), y = (v) => 3 + (h - 6) * (1 - (v - min) / span);
    root.append(svg('path', { d: values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(''), fill: 'none', stroke: color, 'stroke-width': 1.5 }));
    root.append(svg('circle', { cx: x(values.length - 1), cy: y(values[values.length - 1]), r: 3, fill: color }));
    return root;
  }

  return { line, shares, scatter, map, bars, dumbbell, spark, compact, whole };
})();
