// charts.js — hand-drawn inline SVG charts. No dependencies.
// Palette / rules: one accent color for all data marks (#3987e5), hairline
// recessive grid (#2c2c2a), axis (#383835), muted tick labels (#898781).

const NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== null && v !== undefined) el.setAttribute(k, v);
  }
  return el;
}

function textEl(x, y, content, cls, attrs = {}) {
  const t = svgEl("text", { x, y, class: cls, ...attrs });
  t.textContent = content;
  return t;
}

/** Shared measuring canvas for label widths (device names / value labels). */
let _measureCtx = null;
function measureTextWidth(str, font = "600 12px system-ui, -apple-system, sans-serif") {
  if (!_measureCtx) {
    const canvas = document.createElement("canvas");
    _measureCtx = canvas.getContext("2d");
  }
  _measureCtx.font = font;
  return _measureCtx.measureText(str).width;
}

/** Lazily creates (or reuses) the single floating tooltip element. */
function getTooltip() {
  let tip = document.getElementById("chart-tooltip");
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "chart-tooltip";
    tip.className = "chart-tooltip";
    document.body.appendChild(tip);
  }
  return tip;
}

function showTooltip(evt, html) {
  const tip = getTooltip();
  tip.innerHTML = html;
  tip.classList.add("is-visible");
  positionTooltip(evt);
}

function positionTooltip(evt) {
  const tip = getTooltip();
  const pad = 14;
  let x = evt.clientX + pad;
  let y = evt.clientY + pad;
  const rect = tip.getBoundingClientRect();
  if (x + rect.width > window.innerWidth - 8) x = evt.clientX - rect.width - pad;
  if (y + rect.height > window.innerHeight - 8) y = evt.clientY - rect.height - pad;
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}

function hideTooltip() {
  getTooltip().classList.remove("is-visible");
}

/* ----------------------------------------------------------------------
   Sparkline — tiny polyline for KPI cards.
---------------------------------------------------------------------- */
export function renderSparkline(container, data, { width = 84, height = 28 } = {}) {
  container.innerHTML = "";
  if (!data || data.length < 2) return;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const padY = 3;
  const stepX = width / (data.length - 1);

  const points = data
    .map((v, i) => {
      const x = i * stepX;
      const y = height - padY - ((v - min) / span) * (height - padY * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const svg = svgEl("svg", {
    width,
    height,
    viewBox: `0 0 ${width} ${height}`,
    class: "chart-svg",
    role: "img",
    "aria-label": "Trend sparkline",
  });
  svg.appendChild(svgEl("polyline", {
    points,
    fill: "none",
    stroke: "#3987e5",
    "stroke-width": "1.6",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  }));
  // Emphasize the last point.
  const lastX = (data.length - 1) * stepX;
  const lastY = height - padY - ((data[data.length - 1] - min) / span) * (height - padY * 2);
  svg.appendChild(svgEl("circle", { cx: lastX, cy: lastY, r: 2, fill: "#3987e5" }));

  container.appendChild(svg);
}

/* ----------------------------------------------------------------------
   Device timeline — one lane per device, rounded rect per ON interval.
---------------------------------------------------------------------- */
export function renderTimeline(container, timeline, { latestEvent, windowStart, windowEnd } = {}) {
  container.innerHTML = "";
  const lanes = timeline?.lanes ?? [];
  const intervals = timeline?.intervals ?? [];

  if (lanes.length === 0) {
    container.innerHTML = '<p class="empty-note">No devices to show yet.</p>';
    return;
  }

  const laneLabelWidth = 132;
  const rightPad = 16;
  const topPad = 22;
  const laneHeight = 30;
  const laneGap = 4;
  const bottomPad = 20;

  const containerWidth = container.clientWidth || 900;
  const width = Math.max(containerWidth, 480);
  const plotWidth = width - laneLabelWidth - rightPad;
  const height = topPad + lanes.length * (laneHeight + laneGap) + bottomPad;

  // Time domain.
  let minTime = windowStart ? new Date(windowStart).getTime() : null;
  let maxTime = windowEnd ? new Date(windowEnd).getTime() : null;
  if (intervals.length) {
    const starts = intervals.map((iv) => new Date(iv.start).getTime());
    const ends = intervals.map((iv) => new Date(iv.end).getTime());
    if (minTime === null) minTime = Math.min(...starts);
    if (maxTime === null) maxTime = Math.max(...ends);
  }
  if (minTime === null || maxTime === null || minTime === maxTime) {
    minTime = Date.now() - 7 * 86400000;
    maxTime = Date.now();
  }
  const span = maxTime - minTime;

  const xScale = (t) => laneLabelWidth + ((t - minTime) / span) * plotWidth;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    class: "chart-svg",
    role: "img",
    "aria-label": "Device on/off timeline",
  });
  svg.style.width = "100%";
  svg.style.height = `${height}px`;

  // Day boundary gridlines + labels.
  const dayMs = 86400000;
  const firstDay = new Date(minTime);
  firstDay.setHours(0, 0, 0, 0);
  let cursor = firstDay.getTime();
  if (cursor < minTime) cursor += dayMs;
  const dayFmt = new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short" });
  while (cursor <= maxTime) {
    const x = xScale(cursor);
    svg.appendChild(svgEl("line", {
      x1: x, x2: x, y1: topPad - 6, y2: height - bottomPad,
      class: "chart-grid",
    }));
    svg.appendChild(textEl(x, height - bottomPad + 14, dayFmt.format(new Date(cursor)), "chart-tick-label", { "text-anchor": "middle" }));
    cursor += dayMs;
  }

  // Baseline axis under the lanes.
  svg.appendChild(svgEl("line", {
    x1: laneLabelWidth, x2: width - rightPad,
    y1: height - bottomPad, y2: height - bottomPad,
    class: "chart-axis",
  }));

  // Lanes.
  lanes.forEach((lane, i) => {
    const y = topPad + i * (laneHeight + laneGap);
    svg.appendChild(textEl(0, y + laneHeight / 2 + 4, lane, "chart-lane-label"));
    svg.appendChild(svgEl("line", {
      x1: laneLabelWidth, x2: width - rightPad, y1: y + laneHeight, y2: y + laneHeight,
      class: "chart-grid",
    }));
  });

  // Interval marks.
  intervals.forEach((iv) => {
    const laneIdx = lanes.indexOf(iv.device);
    if (laneIdx === -1) return;
    const y = topPad + laneIdx * (laneHeight + laneGap);
    const start = new Date(iv.start).getTime();
    const end = new Date(iv.end).getTime();
    const x1 = xScale(Math.max(start, minTime));
    const x2 = xScale(Math.min(end, maxTime));
    const rectWidth = Math.max(x2 - x1, 2);
    const barHeight = laneHeight - 10;

    const rect = svgEl("rect", {
      x: x1, y: y + 5, width: rectWidth, height: barHeight,
      rx: 4, ry: 4, class: "chart-mark",
    });
    rect.style.cursor = "pointer";

    const fmt = new Intl.DateTimeFormat(undefined, {
      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
    });
    const tooltipHtml = `<strong>${iv.device}</strong><br>${fmt.format(new Date(iv.start))} &rarr; ${fmt.format(new Date(iv.end))}<br>${iv.duration_label}`;

    rect.addEventListener("mousemove", (evt) => showTooltip(evt, tooltipHtml));
    rect.addEventListener("mouseleave", hideTooltip);

    svg.appendChild(rect);
  });

  // "Now" marker.
  if (latestEvent) {
    const now = new Date(latestEvent).getTime();
    if (now >= minTime && now <= maxTime) {
      const x = xScale(now);
      svg.appendChild(svgEl("line", {
        x1: x, x2: x, y1: topPad - 10, y2: height - bottomPad,
        class: "chart-now-line",
      }));
      svg.appendChild(textEl(x, topPad - 12, "now", "chart-now-label", { "text-anchor": "middle" }));
    }
  }

  container.appendChild(svg);
}

/* ----------------------------------------------------------------------
   On-time horizontal bars — sorted descending (server does the sort).
   Value labels must never clip: reserve a fixed gutter measured from the
   longest label, or draw the label inside the bar when it fits.
---------------------------------------------------------------------- */
export function renderOnTimeBars(container, onTime) {
  container.innerHTML = "";
  if (!onTime || onTime.length === 0) {
    container.innerHTML = '<p class="empty-note">No on-time data for this window.</p>';
    return;
  }

  const barFont = "600 12px system-ui, -apple-system, sans-serif";
  const namePad = 14;
  const longestName = Math.max(...onTime.map((d) => measureTextWidth(d.device, barFont)));
  const nameGutter = Math.ceil(longestName) + namePad;

  const longestLabel = Math.max(...onTime.map((d) => measureTextWidth(d.label, barFont)));
  const labelGutter = Math.ceil(longestLabel) + namePad; // reserved so an outside label can never clip

  const rowHeight = 30;
  const rowGap = 8;
  const topPad = 8;
  const bottomPad = 4;
  const rightPad = 8;

  const containerWidth = container.clientWidth || 480;
  const width = Math.max(containerWidth, 320);
  const plotWidth = width - nameGutter - labelGutter - rightPad;
  const height = topPad + onTime.length * (rowHeight + rowGap) - rowGap + bottomPad;

  const maxMinutes = Math.max(...onTime.map((d) => d.minutes));

  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    class: "chart-svg",
    role: "img",
    "aria-label": "Total on-time by device, descending",
  });
  svg.style.width = "100%";
  svg.style.height = `${height}px`;

  onTime.forEach((d, i) => {
    const y = topPad + i * (rowHeight + rowGap);
    const barWidth = Math.max((d.minutes / maxMinutes) * plotWidth, 3);
    const barX = nameGutter;
    const barHeight = rowHeight - 10;
    const barY = y + 5;

    svg.appendChild(textEl(nameGutter - namePad, y + rowHeight / 2 + 4, d.device, "chart-bar-name", { "text-anchor": "end" }));

    const rect = svgEl("rect", {
      x: barX, y: barY, width: barWidth, height: barHeight,
      rx: 4, ry: 4, class: "chart-mark",
    });
    svg.appendChild(rect);

    // Decide inside vs. outside placement so the label is never clipped.
    const labelWidth = measureTextWidth(d.label, barFont);
    const fitsInside = barWidth - 16 >= labelWidth;
    if (fitsInside) {
      svg.appendChild(textEl(barX + barWidth - 8, y + rowHeight / 2 + 4, d.label, "chart-bar-label-inside", { "text-anchor": "end" }));
    } else {
      svg.appendChild(textEl(barX + barWidth + 8, y + rowHeight / 2 + 4, d.label, "chart-bar-label-outside", { "text-anchor": "start" }));
    }
  });

  container.appendChild(svg);
}

/** Re-render helper: call on resize / filter change with the last-known data. */
export function debounce(fn, wait = 120) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}
