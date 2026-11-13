// Offline fallback for the map: if Leaflet or the map tiles cannot load, the same circles are drawn
// as plain SVG over Dubai's coastline and motorways (OpenStreetMap lines saved in the repo).
'use strict';

const SvgMap = (() => {
  const NS = 'http://www.w3.org/2000/svg';
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  let INK = '#17202A', SURFACE = '#FFFFFF';
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
      [INK, SURFACE] = [css('--ink'), css('--surface')];
      const ground = css('--map-ground');
      root.append(svg('rect', { width, height: h, fill: ground }));
      root.append(svg('path', { d: path(base.roads), fill: 'none', stroke: css('--map-road'), 'stroke-width': 1.5, 'stroke-linejoin': 'round' }));
      root.append(svg('path', { d: path(base.coast), fill: 'none', stroke: css('--map-coast'), 'stroke-width': 1, 'stroke-linejoin': 'round' }));
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
          'font-size': 12, 'font-weight': 500, 'paint-order': 'stroke', stroke: ground, 'stroke-width': 3 }, p.label));
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

  return { map };
})();
