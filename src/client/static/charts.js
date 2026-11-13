// Charts for the client view: Apache ECharts for the charts and Leaflet for the maps, both kept in
// static/vendor so the app does not depend on a CDN. Each function draws into a container and keeps
// it sized to the container's width.
'use strict';

const Charts = (() => {
  const FONT = "'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif";
  // Colours come from the stylesheet's theme variables, read again before every drawing, so a chart
  // drawn after a theme switch picks up the new theme.
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  let INK, TEXT, MUTED, GRID, AXIS, SURFACE, TIP, TIP_TEXT, TIP_MUTED, TIP_BORDER, base, axisText;
  function refresh() {
    [INK, TEXT, MUTED, GRID, AXIS, SURFACE] = ['--ink', '--text', '--muted', '--hair', '--axis', '--surface'].map(css);
    [TIP, TIP_TEXT, TIP_MUTED, TIP_BORDER] = ['--tip', '--tip-text', '--tip-muted', '--tip-border'].map(css);
    axisText = { color: MUTED, fontSize: 12 };
    base = {
      textStyle: { fontFamily: FONT, color: TEXT },
      animationDuration: 400,
      tooltip: { backgroundColor: TIP, borderColor: TIP_BORDER, borderWidth: TIP_BORDER === 'transparent' ? 0 : 1, padding: [8, 10],
        textStyle: { color: TIP_TEXT, fontFamily: FONT, fontSize: 13 }, extraCssText: 'border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,.25);' },
      legend: { top: 0, left: 0, icon: 'roundRect', itemWidth: 14, itemHeight: 4, itemGap: 16, textStyle: { color: TEXT, fontSize: 13 } },
      toolbox: { right: 0, top: -4, itemSize: 14, iconStyle: { borderColor: MUTED },
        feature: { saveAsImage: { title: 'Save as image', pixelRatio: 2, backgroundColor: SURFACE } } },
    };
  }
  const dark = () => document.documentElement.dataset.theme === 'dark';
  const compact = (n) => n >= 1e6 ? `${+(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}K` : Math.round(n).toLocaleString('en-US');
  const whole = (n) => Math.round(n).toLocaleString('en-US');
  // Names come from the data files: anything put into an HTML tooltip is escaped first.
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function html(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // ---- ECharts plumbing ----
  const valueAxis = (format, extra = {}) => ({ type: 'value', axisLabel: { ...axisText, formatter: format },
    splitLine: { lineStyle: { color: GRID } }, axisLine: { show: false }, axisTick: { show: false }, ...extra });

  function chart(container, option, height) {
    container.style.height = `${height}px`;
    const old = echarts.getInstanceByDom(container);
    if (old) old.dispose();
    const instance = echarts.init(container, null, { renderer: 'svg' });
    instance.setOption({ ...base, ...option, tooltip: { ...base.tooltip, ...option.tooltip },
      legend: option.legend === false ? undefined : { ...base.legend, ...option.legend } });
    if (!container.dataset.watched) {     // one observer per container, however often it is redrawn
      container.dataset.watched = '1';
      new ResizeObserver(() => { const c = echarts.getInstanceByDom(container); if (c) c.resize(); }).observe(container);
    }
    container.setAttribute('role', 'img');
    return instance;
  }
  const row = (color, value, name) => `<div style="display:flex;align-items:baseline;gap:6px">`
    + (color ? `<i style="width:10px;height:3px;border-radius:2px;background:${color};align-self:center"></i>` : '')
    + `<strong>${esc(value)}</strong><span style="color:${TIP_MUTED}">${esc(name)}</span></div>`;
  const title = (text) => `<div style="font-weight:600;margin-bottom:2px">${esc(text)}</div>`;

  // ---- line chart: one or more series, crosshair tooltip ----
  // series: [{name, color, values}], labels: [string]; xValues places points by value (team sizes 5..50)
  function line(container, { series, labels, xTicks, xValues, tickText = (i) => labels[i], format = compact, tipFormat = whole,
    height = 280, label, zoom = false }) {
    refresh();
    container.setAttribute('aria-label', label);
    const n = labels.length, shown = new Set(xTicks);
    const lastDot = (value, params) => (params.dataIndex === n - 1 ? 8 : 0);
    const data = (s) => s.values.map((v, i) => (xValues ? [xValues[i], v] : v));
    chart(container, {
      grid: { left: 48, right: 16, top: series.length > 1 ? 36 : 16, bottom: zoom ? 56 : 28 },
      legend: series.length > 1 ? { data: series.map((s) => s.name) } : false,
      toolbox: base.toolbox,
      tooltip: { trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: AXIS, type: 'solid' } },
        formatter: (points) => title(labels[points[0].dataIndex]) + points.map((p) => row(p.color, tipFormat(xValues ? p.value[1] : p.value), p.seriesName)).join('') },
      xAxis: xValues
        ? { type: 'value', min: xValues[0], max: xValues[n - 1], interval: 5, axisLabel: axisText, splitLine: { show: false },
            axisLine: { lineStyle: { color: AXIS } }, axisTick: { show: false } }
        : { type: 'category', data: labels, boundaryGap: false, axisLine: { lineStyle: { color: AXIS } }, axisTick: { show: false },
            axisLabel: { ...axisText, interval: (i) => shown.has(i), formatter: (_, i) => tickText(i) } },
      yAxis: valueAxis(format),
      dataZoom: zoom ? [{ type: 'slider', height: 18, bottom: 6, borderColor: GRID, fillerColor: dark() ? 'rgba(63,134,214,0.18)' : 'rgba(31,90,153,0.08)',
        handleStyle: { color: SURFACE, borderColor: AXIS }, moveHandleSize: 0, showDetail: false, brushSelect: false,
        dataBackground: { lineStyle: { color: AXIS }, areaStyle: { color: GRID } } }] : [],
      series: series.map((s) => ({ name: s.name, type: 'line', data: data(s), color: s.color, symbol: 'circle', symbolSize: lastDot,
        showSymbol: true, showAllSymbol: true, lineStyle: { width: 2 }, itemStyle: { borderColor: SURFACE, borderWidth: 2 },
        emphasis: { disabled: true } })),
    }, height);
  }

  // ---- stacked columns as shares of each column's total ----
  function shares(container, { parts, labels, xTicks, tickText = (i) => labels[i], height = 240, label }) {
    refresh();
    container.setAttribute('aria-label', label);
    const totals = labels.map((_, i) => parts.reduce((sum, p) => sum + p.values[i], 0) || 1), shown = new Set(xTicks);
    chart(container, {
      grid: { left: 40, right: 8, top: 36, bottom: 28 },
      legend: { data: parts.slice().reverse().map((p) => p.name), icon: 'rect', itemWidth: 10, itemHeight: 10 },
      toolbox: base.toolbox,
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: dark() ? 'rgba(255,255,255,0.05)' : 'rgba(23,32,42,0.05)' } },
        formatter: (points) => title(labels[points[0].dataIndex]) + points.slice().reverse()
          .map((p) => row(p.color, `${parts[p.seriesIndex].values[p.dataIndex]} (${Math.round(p.value * 100)}%)`, p.seriesName)).join('') },
      xAxis: { type: 'category', data: labels, axisLine: { lineStyle: { color: AXIS } }, axisTick: { show: false },
        axisLabel: { ...axisText, interval: (i) => shown.has(i), formatter: (_, i) => tickText(i) } },
      yAxis: valueAxis((v) => `${Math.round(v * 100)}%`, { max: 1, interval: 0.5 }),
      series: parts.map((p) => ({ name: p.name, type: 'bar', stack: 'all', barMaxWidth: 24, color: p.color,
        data: p.values.map((v, i) => v / totals[i]), itemStyle: { borderColor: SURFACE, borderWidth: 1 }, emphasis: { focus: 'series' } })),
    }, height);
  }

  // ---- scatter on log axes; picks are larger, darker and labelled ----
  function scatter(container, { points, xTitle, yTitle, xFormat = compact, yFormat = compact, height = 340, label, strongName, weakName }) {
    refresh();
    container.setAttribute('aria-label', label);
    const pick = (strong) => points.filter((p) => !!p.strong === strong);
    const labelled = new Set();     // an area with two picked segments is named once, at its bigger one
    const item = (p) => {
      const named = p.label && !labelled.has(p.label);
      if (named) labelled.add(p.label);
      return { value: [p.x, p.y], name: p.name, detail: p.detail, label: named ? p.label : '' };
    };
    const strong = pick(true).sort((a, b) => b.x - a.x);
    const bounds = (values) => ({ min: Math.min(...values) * 0.7, max: Math.max(...values) * 1.4 });
    const tip = (p) => title(p.data.name) + p.data.detail.map(([name, value]) => row(null, value, name)).join('');
    chart(container, {
      grid: { left: 62, right: 20, top: 36, bottom: 46 },
      legend: { data: [strongName, weakName], icon: 'circle', itemWidth: 9, itemHeight: 9 },
      toolbox: base.toolbox,
      tooltip: { trigger: 'item', formatter: tip },
      xAxis: { type: 'log', ...bounds(points.map((p) => p.x)), name: xTitle, nameLocation: 'middle', nameGap: 28, nameTextStyle: axisText, axisLabel: { ...axisText, formatter: xFormat, showMinLabel: false, showMaxLabel: false },
        splitLine: { lineStyle: { color: GRID } }, axisLine: { lineStyle: { color: AXIS } }, axisTick: { show: false } },
      yAxis: { type: 'log', ...bounds(points.map((p) => p.y)), name: yTitle, nameLocation: 'middle', nameGap: 46, nameTextStyle: axisText, axisLabel: { ...axisText, formatter: yFormat, showMinLabel: false, showMaxLabel: false },
        splitLine: { lineStyle: { color: GRID } }, axisLine: { show: false }, axisTick: { show: false } },
      series: [
        { name: weakName, type: 'scatter', data: pick(false).map(item), symbolSize: 7, color: points.find((p) => !p.strong)?.color,
          itemStyle: { opacity: 0.6, borderColor: SURFACE, borderWidth: 1 }, emphasis: { scale: 1.6 } },
        { name: strongName, type: 'scatter', data: strong.map(item), symbolSize: 11, color: points.find((p) => p.strong)?.color,
          itemStyle: { borderColor: SURFACE, borderWidth: 2 }, emphasis: { scale: 1.4 }, labelLayout: { hideOverlap: true },
          label: { show: true, position: 'right', distance: 6, formatter: (p) => p.data.label || '', color: INK, fontSize: 12, fontWeight: 500,
            textBorderColor: SURFACE, textBorderWidth: 3 } },
      ],
    }, height);
  }

  // ---- before and after per row: a hollow dot for the saved plan, a filled one for the new plan ----
  function dumbbell(container, { rows, colors, label }) {
    refresh();
    container.setAttribute('aria-label', label);
    const ordered = rows.slice().reverse();      // category axes run bottom to top
    const names = ordered.map((r) => r.label);
    chart(container, {
      grid: { left: 8, right: 56, top: 32, bottom: 8, containLabel: true },
      legend: { data: ['Saved plan', 'This plan'], icon: 'circle', itemWidth: 9, itemHeight: 9 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: dark() ? 'rgba(255,255,255,0.05)' : 'rgba(23,32,42,0.05)' } },
        formatter: (points) => { const r = ordered[points[0].dataIndex]; return title(r.label) + row(null, String(r.before), 'saved plan') + row(null, String(r.after), 'this plan'); } },
      xAxis: valueAxis((v) => v, { minInterval: 1, position: 'top' }),
      yAxis: { type: 'category', data: names, axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: INK, fontSize: 13, formatter: (name, i) => (ordered[i].before !== ordered[i].after ? `{b|${name}}` : name),
          rich: { b: { fontWeight: 600, color: INK, fontSize: 13 } } } },
      series: [
        { type: 'bar', stack: 'link', silent: true, data: ordered.map((r) => Math.min(r.before, r.after)), itemStyle: { color: 'transparent' }, barWidth: 2, tooltip: { show: false } },
        { type: 'bar', stack: 'link', silent: true, data: ordered.map((r) => Math.abs(r.after - r.before)), itemStyle: { color: AXIS }, barWidth: 2, tooltip: { show: false },
          label: { show: true, position: 'right', distance: 10, color: MUTED, fontSize: 12,
            formatter: (p) => { const r = ordered[p.dataIndex]; return r.before === r.after ? '' : `${r.before} → ${r.after}`; } } },
        { name: 'Saved plan', type: 'scatter', data: ordered.map((r) => r.before), symbolSize: 10, color: colors.before,
          itemStyle: { color: SURFACE, borderColor: colors.before, borderWidth: 2 } },
        { name: 'This plan', type: 'scatter', data: ordered.map((r) => r.after), symbolSize: 10, color: colors.after,
          itemStyle: { borderColor: SURFACE, borderWidth: 2 } },
      ],
    }, Math.max(160, rows.length * 34 + 48));
  }

  // ---- map: a Leaflet map of Dubai, each area shaded inside its official boundary ----
  // points: [{area, lat, lon, size, color, ring, name, detail:[[label, value]], label}]
  // shapes: GeoJSON features with properties.area; an area without one is drawn as a circle sized by `size`
  // Basemaps in order of preference. Stadia needs no key on localhost; a hosted copy needs a free Stadia
  // account. Esri's light grey canvas is the backup, and the saved OpenStreetMap lines the last resort.
  const OSM = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas';
  const basemaps = (night) => [
    { layers: [`https://tiles.stadiamaps.com/tiles/${night ? 'alidade_smooth_dark' : 'alidade_smooth'}/{z}/{x}/{y}{r}.png`],
      credit: `&copy; <a href="https://stadiamaps.com/">Stadia Maps</a> &copy; <a href="https://openmaptiles.org/">OpenMapTiles</a> ${OSM}` },
    { layers: [`${ESRI}/${night ? 'World_Dark_Gray_Base' : 'World_Light_Gray_Base'}/MapServer/tile/{z}/{y}/{x}`,
      `${ESRI}/${night ? 'World_Dark_Gray_Reference' : 'World_Light_Gray_Reference'}/MapServer/tile/{z}/{y}/{x}`],
      credit: 'Tiles &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors', maxZoom: 16 },
  ];

  function tooltipNode(name, detail) {
    const box = html('div', 'map-tip');
    box.append(html('div', 'tip-title', name));
    for (const [labelText, value] of detail) {
      const line = html('div', 'tip-row');
      line.append(html('strong', '', value), html('span', '', labelText));
      box.append(line);
    }
    return box;
  }

  function map(container, { base: lines, points, shapes = [], height = 460, label, maxRadius = 22 }) {
    refresh();
    const BASEMAPS = basemaps(dark());
    const h = container.clientWidth < 520 ? 360 : height;
    if (!window.L) return SvgMap.map(container, { base: lines, points, height: h, label, maxRadius });     // Leaflet failed to load
    if (container._leaflet) { container._leaflet.off(); container._leaflet.remove(); container._leaflet = null; }
    container.replaceChildren();
    container.style.height = `${h}px`;
    container.setAttribute('aria-label', label);
    const view = L.map(container, { scrollWheelZoom: false, attributionControl: true });      // whole zoom levels: no seams between tiles
    container._leaflet = view;
    view.attributionControl.setPrefix(false);
    view.createPane('labels').style.zIndex = 650;

    // Basemap: try each provider; when one fails to load any tile, move to the next. With no internet at
    // all, draw the saved coastline and motorways instead.
    const offline = () => {
      const toLatLng = (way) => way.map(([lon, lat]) => [lat, lon]);
      L.layerGroup([
        L.polyline(lines.roads.map(toLatLng), { color: css('--map-road'), weight: 1.5, interactive: false }),
        L.polyline(lines.coast.map(toLatLng), { color: css('--map-coast'), weight: 1, interactive: false }),
      ]).addTo(view);
      view.attributionControl.addAttribution(`Offline map lines ${OSM}`);
    };
    const useBasemap = (index) => {
      if (index >= BASEMAPS.length) return offline();
      const choice = BASEMAPS[index];
      let loaded = 0, failed = 0, done = false;
      const layers = choice.layers.map((url, i) => L.tileLayer(url, { maxZoom: choice.maxZoom || 18,
        attribution: i === 0 ? choice.credit : undefined }).addTo(view));
      layers[0].on('tileload', () => { loaded += 1; });
      layers[0].on('tileerror', () => {
        failed += 1;
        if (!done && loaded === 0 && failed >= 4) {
          done = true;
          layers.forEach((layer) => view.removeLayer(layer));
          useBasemap(index + 1);
        }
      });
    };
    useBasemap(0);

    const biggest = Math.max(...points.map((p) => p.size), 1);
    const radius = (size) => Math.max(4, maxRadius * Math.sqrt(size / biggest));      // circle area, not radius, carries the value
    const ordered = points.slice().sort((a, b) => b.size - a.size);
    const outline = new Map(shapes.map((feature) => [feature.properties.area, feature]));
    const look = (p) => (p.ring ? { color: MUTED, weight: 1, fillColor: SURFACE, fillOpacity: 0.35 }
      : { color: SURFACE, weight: 1, fillColor: p.color, fillOpacity: 0.78 });
    const layers = ordered.slice().reverse().map((p) => {
      const shape = outline.get(p.area);
      const layer = shape ? L.geoJSON(shape, { style: () => look(p) })
        : L.circleMarker([p.lat, p.lon], { ...look(p), weight: 1.5, radius: radius(p.size) });
      return layer.bindTooltip(tooltipNode(p.name, p.detail), { sticky: true, direction: 'top', offset: [0, -8], className: 'map-tooltip', opacity: 1 })
        .on('mouseover', (event) => { const target = event.layer || event.target; target.setStyle({ color: INK, weight: 2 }); target.bringToFront(); })
        .on('mouseout', (event) => { (event.layer || event.target).setStyle(look(p)); });
    });
    L.featureGroup(layers).addTo(view);

    // Names on the biggest circles, skipping any that would overlap at the current zoom.
    const names = L.layerGroup().addTo(view);
    const placeNames = () => {
      names.clearLayers();
      const placed = [];
      for (const p of ordered.filter((q) => q.label)) {
        const at = view.latLngToContainerPoint([p.lat, p.lon]);
        const inside = outline.has(p.area), offset = inside ? 0 : radius(p.size) + 5;
        if (placed.some((q) => Math.abs(q.x - at.x) < 120 && Math.abs(q.y - at.y) < 16)) continue;
        placed.push(at);
        names.addLayer(L.marker([p.lat, p.lon], { pane: 'labels', interactive: false, keyboard: false,
          icon: L.divIcon({ className: inside ? 'map-name centred' : 'map-name', html: `<span>${esc(p.label)}</span>`, iconSize: [0, 0],
            iconAnchor: [-offset, 8] }) }));
      }
    };
    view.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lon])), { padding: [16, 16] });
    view.on('zoomend', placeNames);
    placeNames();
    if (!container._watcher) {      // one watcher per container, always pointing at the current map
      container._watcher = new ResizeObserver(() => { if (container._leaflet) container._leaflet.invalidateSize(); });
      container._watcher.observe(container);
    }
    return view;
  }

  // ---- horizontal bars with the value at the tip (plain HTML: four rows need no chart engine) ----
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
      const item = html('div', 'hbar');
      item.append(html('span', 'hbar-label', r.label), track, html('strong', 'hbar-value', r.text));
      list.append(item);
    }
    container.replaceChildren(list);
  }

  // ---- tiny trend line for a stat tile: no axes or tooltip, the tile's number is the value ----
  function spark(values, color) {
    const NS = 'http://www.w3.org/2000/svg', w = 96, h = 28, max = Math.max(...values), min = Math.min(...values), span = max - min || 1;
    const node = (tag, attrs) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
    const x = (i) => 2 + (w - 8) * i / (values.length - 1), y = (v) => 3 + (h - 6) * (1 - (v - min) / span);
    const root = node('svg', { width: w, height: h, viewBox: `0 0 ${w} ${h}`, 'aria-hidden': 'true' });
    root.append(node('path', { d: values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(''), fill: 'none', stroke: color, 'stroke-width': 1.5 }));
    root.append(node('circle', { cx: x(values.length - 1), cy: y(values[values.length - 1]), r: 3, fill: color }));
    return root;
  }

  return { line, shares, scatter, map, bars, dumbbell, spark, compact, whole };
})();
