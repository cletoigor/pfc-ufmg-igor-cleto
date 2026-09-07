// charts.js — hand-drawn inline SVG charts. No dependencies.
// Palette / rules: one accent color for all data marks (var(--accent)), hairline
// recessive grid (var(--grid-line)), axis (var(--axis-line)), muted tick labels
// (var(--tick-label)) — themeable, so the same marks read on light and dark.

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
    stroke: "var(--accent)",
    "stroke-width": "1.6",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  }));
  // Emphasize the last point.
  const lastX = (data.length - 1) * stepX;
  const lastY = height - padY - ((data[data.length - 1] - min) / span) * (height - padY * 2);
  svg.appendChild(svgEl("circle", { cx: lastX, cy: lastY, r: 2, fill: "var(--accent)" }));

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

/* ======================================================================
   Shared plotting scaffold for the energy charts.

   The three original charts each drew their own axes because each has an
   unusual shape (swim lanes, ranked bars, a 28px sparkline). The charts
   added for the monograph's four pages are all conventional x/y plots, so
   they share one scaffold: same margins, same hairline grid, same tick
   typography, and one place to fix a rendering bug.
====================================================================== */

const PLOT_DEFAULTS = {
  height: 220,
  padTop: 14,
  padRight: 14,
  padBottom: 26,
  padLeft: 46,
  minWidth: 320,
};

/** Picks ~5 round numbers spanning [0, max] for a y axis. */
function niceTicks(max, count = 4) {
  if (!isFinite(max) || max <= 0) return [0, 1];
  const rough = max / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? magnitude * 10;
  const ticks = [];
  for (let value = 0; value <= max + step * 0.001; value += step) ticks.push(value);
  return ticks;
}

/** Formats a number for a tick label without trailing noise. */
function formatTick(value) {
  const abs = Math.abs(value);
  if (abs === 0) return "0";
  if (abs >= 1000) return `${Math.round(value / 100) / 10}k`;
  if (abs >= 10) return String(Math.round(value));
  if (abs >= 1) return String(Math.round(value * 10) / 10);
  return String(Math.round(value * 10000) / 10000);
}

function createPlot(container, options = {}) {
  const opts = { ...PLOT_DEFAULTS, ...options };
  container.innerHTML = "";

  const width = Math.max(container.clientWidth || 640, opts.minWidth);
  const height = opts.height;
  const plotLeft = opts.padLeft;
  const plotRight = width - opts.padRight;
  const plotTop = opts.padTop;
  const plotBottom = height - opts.padBottom;
  const plotWidth = plotRight - plotLeft;
  const plotHeight = plotBottom - plotTop;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    class: "chart-svg",
    role: "img",
    "aria-label": opts.ariaLabel ?? "chart",
  });
  svg.style.width = "100%";
  svg.style.height = `${height}px`;

  const [xMin, xMax] = opts.xDomain ?? [0, 1];
  const yMax = opts.yMax && opts.yMax > 0 ? opts.yMax : 1;
  const yMin = opts.yMin ?? 0;

  const xSpan = xMax - xMin || 1;
  const ySpan = yMax - yMin || 1;
  const xScale = (value) => plotLeft + ((value - xMin) / xSpan) * plotWidth;
  const yScale = (value) => plotBottom - ((value - yMin) / ySpan) * plotHeight;

  // Horizontal gridlines + y tick labels.
  (opts.yTicks ?? niceTicks(yMax)).forEach((tick) => {
    if (tick < yMin || tick > yMax) return;
    const y = yScale(tick);
    svg.appendChild(svgEl("line", { x1: plotLeft, x2: plotRight, y1: y, y2: y, class: "chart-grid" }));
    svg.appendChild(
      textEl(plotLeft - 7, y + 3.5, formatTick(tick), "chart-tick-label", { "text-anchor": "end" })
    );
  });

  // Baseline.
  svg.appendChild(
    svgEl("line", { x1: plotLeft, x2: plotRight, y1: plotBottom, y2: plotBottom, class: "chart-axis" })
  );

  // X tick labels, thinned so they never overlap.
  const xTicks = opts.xTicks ?? [];
  const maxTicks = Math.max(2, Math.floor(plotWidth / 64));
  const stride = Math.ceil(xTicks.length / maxTicks) || 1;
  xTicks.forEach((tick, index) => {
    if (index % stride !== 0) return;
    const x = xScale(tick.value);
    if (x < plotLeft - 1 || x > plotRight + 1) return;
    if (tick.grid) {
      svg.appendChild(svgEl("line", { x1: x, x2: x, y1: plotTop, y2: plotBottom, class: "chart-grid" }));
    }
    svg.appendChild(
      textEl(x, plotBottom + 15, tick.label, "chart-tick-label", { "text-anchor": "middle" })
    );
  });

  if (opts.yLabel) {
    svg.appendChild(textEl(plotLeft, plotTop - 4, opts.yLabel, "chart-axis-label"));
  }

  container.appendChild(svg);
  return { svg, xScale, yScale, plotLeft, plotRight, plotTop, plotBottom, plotWidth, plotHeight, width, height };
}

function emptyNote(container, message) {
  container.innerHTML = `<p class="empty-note">${message}</p>`;
}

/** Splits a series at nulls so a gap is a gap, not a straight line across it. */
function segmentize(points) {
  const segments = [];
  let current = [];
  points.forEach((point) => {
    if (point.y === null || point.y === undefined || Number.isNaN(point.y)) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push(point);
    }
  });
  if (current.length) segments.push(current);
  return segments;
}

function drawSeries(plot, points, { color, width = 1.6, dashed = false, opacity = 1, step = false }) {
  segmentize(points).forEach((segment) => {
    if (segment.length === 1) {
      plot.svg.appendChild(
        svgEl("circle", {
          cx: plot.xScale(segment[0].x), cy: plot.yScale(segment[0].y), r: 1.8, fill: color, opacity,
        })
      );
      return;
    }
    let d = "";
    segment.forEach((point, index) => {
      const x = plot.xScale(point.x);
      const y = plot.yScale(point.y);
      if (index === 0) {
        d += `M${x} ${y}`;
      } else if (step) {
        d += `H${x}V${y}`;
      } else {
        d += `L${x} ${y}`;
      }
    });
    plot.svg.appendChild(
      svgEl("path", {
        d,
        fill: "none",
        stroke: color,
        "stroke-width": width,
        "stroke-linejoin": "round",
        "stroke-linecap": "round",
        "stroke-dasharray": dashed ? "4 3" : null,
        opacity,
      })
    );
  });
}

/* ----------------------------------------------------------------------
   Line chart — power/voltage/current over time, and hourly profiles.
---------------------------------------------------------------------- */
export function renderLineChart(container, config = {}) {
  const series = (config.series ?? []).filter((s) => (s.points ?? []).length);
  if (!series.length) {
    emptyNote(container, config.emptyMessage ?? "Nothing to plot for this selection.");
    return;
  }

  const allPoints = series.flatMap((s) => s.points);
  const values = allPoints.map((p) => p.y).filter((v) => v !== null && v !== undefined && !Number.isNaN(v));
  if (!values.length) {
    emptyNote(container, config.emptyMessage ?? "No readings in this period.");
    return;
  }

  const xs = allPoints.map((p) => p.x);
  const xDomain = config.xDomain ?? [Math.min(...xs), Math.max(...xs)];
  // Headroom so the topmost point is not welded to the frame.
  const yMax = config.yMax ?? Math.max(...values) * 1.08;
  const yMin = config.yMin ?? (config.zeroBased === false ? Math.min(...values) * 0.98 : 0);

  const plot = createPlot(container, {
    ...config,
    xDomain,
    yMin,
    yMax,
    yTicks: config.yTicks ?? niceTicks(yMax).filter((t) => t >= yMin),
    ariaLabel: config.ariaLabel ?? "line chart",
  });

  series.forEach((s) => {
    drawSeries(plot, s.points, {
      color: s.color ?? "var(--accent)",
      width: s.width ?? 1.6,
      dashed: s.dashed ?? false,
      opacity: s.opacity ?? 1,
      step: s.step ?? false,
    });
  });

  if (config.markers) {
    config.markers.forEach((marker) => {
      plot.svg.appendChild(
        svgEl("circle", {
          cx: plot.xScale(marker.x),
          cy: plot.yScale(marker.y),
          r: 3.4,
          fill: marker.color ?? "var(--critical)",
          stroke: "var(--surface)",
          "stroke-width": 1.2,
        })
      );
    });
  }

  // One hover target per x position, spanning the full plot height, so the
  // tooltip is reachable without having to hit a 1.6px line exactly.
  if (config.tooltip) {
    const first = series[0].points;
    const bandWidth = plot.plotWidth / Math.max(1, first.length);
    first.forEach((point, index) => {
      const rect = svgEl("rect", {
        x: plot.xScale(point.x) - bandWidth / 2,
        y: plot.plotTop,
        width: bandWidth,
        height: plot.plotHeight,
        fill: "transparent",
      });
      rect.addEventListener("mousemove", (evt) => showTooltip(evt, config.tooltip(index)));
      rect.addEventListener("mouseleave", hideTooltip);
      plot.svg.appendChild(rect);
    });
  }

  if (config.legend !== false && series.length > 1) {
    container.appendChild(buildLegend(series));
  }
}

function buildLegend(series) {
  const legend = document.createElement("div");
  legend.className = "chart-legend";
  series
    .filter((s) => s.name)
    .forEach((s) => {
      const item = document.createElement("span");
      item.className = "chart-legend-item";
      const swatch = document.createElement("span");
      swatch.className = "chart-legend-swatch";
      swatch.style.background = s.color ?? "var(--accent)";
      if (s.dashed) swatch.style.opacity = "0.6";
      item.append(swatch, document.createTextNode(s.name));
      legend.appendChild(item);
    });
  return legend;
}

/* ----------------------------------------------------------------------
   Vertical bars — daily energy, hourly profiles.
---------------------------------------------------------------------- */
export function renderBarChart(container, data, config = {}) {
  const rows = (data ?? []).filter((row) => row.value !== null && row.value !== undefined);
  if (!rows.length) {
    emptyNote(container, config.emptyMessage ?? "No data for this period.");
    return;
  }

  const max = Math.max(...rows.map((row) => row.value));
  const plot = createPlot(container, {
    ...config,
    xDomain: [0, rows.length],
    yMax: max * 1.1 || 1,
    xTicks: rows.map((row, index) => ({ value: index + 0.5, label: row.label })),
    ariaLabel: config.ariaLabel ?? "bar chart",
  });

  const slot = plot.plotWidth / rows.length;
  const barWidth = Math.max(2, Math.min(slot * 0.68, 42));

  rows.forEach((row, index) => {
    const x = plot.xScale(index + 0.5) - barWidth / 2;
    const y = plot.yScale(row.value);
    const rect = svgEl("rect", {
      x,
      y,
      width: barWidth,
      height: Math.max(1, plot.plotBottom - y),
      rx: 2,
      class: "chart-mark",
      fill: row.color ?? null,
    });
    if (config.tooltip) {
      rect.addEventListener("mousemove", (evt) => showTooltip(evt, config.tooltip(row, index)));
      rect.addEventListener("mouseleave", hideTooltip);
    }
    plot.svg.appendChild(rect);
  });
}

/* ----------------------------------------------------------------------
   Ranked horizontal bars — "top consumers".

   Distinct from renderOnTimeBars: this one carries a share-of-total label
   as well as the value, which is what makes a ranking legible.
---------------------------------------------------------------------- */
export function renderRankedBars(container, rows, config = {}) {
  container.innerHTML = "";
  if (!rows || !rows.length) {
    emptyNote(container, config.emptyMessage ?? "No consumption recorded yet.");
    return;
  }

  const format = config.format ?? ((value) => String(value));
  const labelFont = "600 12px system-ui, -apple-system, sans-serif";
  const nameWidth = Math.min(
    160,
    Math.max(...rows.map((row) => measureTextWidth(row.label, labelFont))) + 12
  );
  const valueWidth = Math.max(...rows.map((row) => measureTextWidth(format(row.value), labelFont))) + 14;

  const barHeight = 22;
  const gap = 10;
  const width = Math.max(container.clientWidth || 520, 300);
  const height = rows.length * (barHeight + gap) + 6;
  const trackLeft = nameWidth;
  const trackWidth = Math.max(40, width - nameWidth - valueWidth);
  const max = Math.max(...rows.map((row) => row.value)) || 1;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    class: "chart-svg",
    role: "img",
    "aria-label": config.ariaLabel ?? "ranked bars",
  });
  svg.style.width = "100%";
  svg.style.height = `${height}px`;

  rows.forEach((row, index) => {
    const y = index * (barHeight + gap) + 3;
    svg.appendChild(
      textEl(nameWidth - 10, y + barHeight / 2 + 4, row.label, "chart-bar-name", { "text-anchor": "end" })
    );
    const barWidth = Math.max(2, (row.value / max) * trackWidth);
    const rect = svgEl("rect", {
      x: trackLeft, y, width: barWidth, height: barHeight, rx: 3, class: "chart-mark",
    });
    if (config.tooltip) {
      rect.addEventListener("mousemove", (evt) => showTooltip(evt, config.tooltip(row)));
      rect.addEventListener("mouseleave", hideTooltip);
    }
    svg.appendChild(rect);
    svg.appendChild(
      textEl(trackLeft + barWidth + 8, y + barHeight / 2 + 4, format(row.value), "chart-bar-label-outside")
    );
  });

  container.appendChild(svg);
}

/* ----------------------------------------------------------------------
   Boxplot — the voltage/current distributions of figures 4.12 and 4.14.
   Takes the five-number summary the API already computed.
---------------------------------------------------------------------- */
export function renderBoxplot(container, stats, config = {}) {
  container.innerHTML = "";
  if (!stats) {
    emptyNote(container, config.emptyMessage ?? "Not enough readings to summarise.");
    return;
  }

  const values = [stats.whisker_low, stats.q1, stats.median, stats.q3, stats.whisker_high, ...(stats.outliers ?? [])];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.08 || 1;

  const plot = createPlot(container, {
    height: config.height ?? 128,
    padLeft: 46,
    padBottom: 30,
    xDomain: [min - pad, max + pad],
    yMin: 0,
    yMax: 1,
    yTicks: [],
    xTicks: niceTicksBetween(min - pad, max + pad).map((value) => ({
      value,
      label: formatTick(value),
    })),
    ariaLabel: config.ariaLabel ?? "distribution boxplot",
  });

  const midY = (plot.plotTop + plot.plotBottom) / 2;
  const boxHeight = Math.min(34, plot.plotHeight * 0.6);
  const top = midY - boxHeight / 2;

  // Whiskers.
  plot.svg.appendChild(
    svgEl("line", {
      x1: plot.xScale(stats.whisker_low), x2: plot.xScale(stats.whisker_high),
      y1: midY, y2: midY, class: "chart-axis",
    })
  );
  [stats.whisker_low, stats.whisker_high].forEach((value) => {
    plot.svg.appendChild(
      svgEl("line", {
        x1: plot.xScale(value), x2: plot.xScale(value),
        y1: midY - boxHeight / 3, y2: midY + boxHeight / 3, class: "chart-axis",
      })
    );
  });

  // Interquartile box.
  plot.svg.appendChild(
    svgEl("rect", {
      x: plot.xScale(stats.q1),
      y: top,
      width: Math.max(1, plot.xScale(stats.q3) - plot.xScale(stats.q1)),
      height: boxHeight,
      rx: 2,
      fill: "var(--accent-dim)",
      stroke: "var(--accent)",
      "stroke-width": 1.2,
    })
  );

  // Median.
  plot.svg.appendChild(
    svgEl("line", {
      x1: plot.xScale(stats.median), x2: plot.xScale(stats.median),
      y1: top, y2: top + boxHeight,
      stroke: "var(--accent)", "stroke-width": 2,
    })
  );

  (stats.outliers ?? []).forEach((value) => {
    plot.svg.appendChild(
      svgEl("circle", { cx: plot.xScale(value), cy: midY, r: 2.4, fill: "var(--ink-3)" })
    );
  });

  const tip = `<strong>median ${formatTick(stats.median)}</strong><br>` +
    `q1 ${formatTick(stats.q1)} · q3 ${formatTick(stats.q3)}<br>` +
    `range ${formatTick(stats.min)} – ${formatTick(stats.max)} · n=${stats.count}`;
  const hover = svgEl("rect", {
    x: plot.plotLeft, y: plot.plotTop, width: plot.plotWidth, height: plot.plotHeight, fill: "transparent",
  });
  hover.addEventListener("mousemove", (evt) => showTooltip(evt, tip));
  hover.addEventListener("mouseleave", hideTooltip);
  plot.svg.appendChild(hover);
}

function niceTicksBetween(min, max, count = 5) {
  const step = (max - min) / count;
  if (!isFinite(step) || step <= 0) return [min];
  const magnitude = Math.pow(10, Math.floor(Math.log10(step)));
  const nice = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= step) ?? magnitude * 10;
  const start = Math.ceil(min / nice) * nice;
  const ticks = [];
  for (let value = start; value <= max; value += nice) ticks.push(value);
  return ticks;
}

/* ----------------------------------------------------------------------
   CUSUM chart — both cumulative sums against a per-channel decision limit.

   The limit is drawn as a step line, not a straight one: H = h * sigma0 and
   sigma0 differs per hour-of-day channel, so a single horizontal rule would
   misrepresent where the threshold actually sat when a point crossed it.
---------------------------------------------------------------------- */
export function renderCusumChart(container, points, config = {}) {
  const usable = (points ?? []).filter((p) => p.monitored);
  if (!usable.length) {
    emptyNote(container, config.emptyMessage ?? "No monitored observations in this period.");
    return;
  }

  const indexed = usable.map((point, index) => ({ ...point, index }));
  const maxSum = Math.max(
    ...indexed.map((p) => Math.max(p.s_hi ?? 0, p.s_lo ?? 0, p.limit ?? 0))
  );

  const times = indexed.map((p) => new Date(p.time));
  const dayFormat = new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short" });
  const xTicks = [];
  let lastDay = null;
  indexed.forEach((point, index) => {
    const day = times[index].toDateString();
    if (day !== lastDay) {
      xTicks.push({ value: index, label: dayFormat.format(times[index]), grid: true });
      lastDay = day;
    }
  });

  renderLineChart(container, {
    height: config.height ?? 260,
    ariaLabel: "CUSUM control chart",
    xDomain: [0, indexed.length - 1 || 1],
    yMax: maxSum * 1.12 || 1,
    xTicks,
    legend: true,
    series: [
      {
        name: "Upper sum (S⁺)",
        color: "var(--accent)",
        points: indexed.map((p) => ({ x: p.index, y: p.s_hi })),
      },
      {
        name: "Lower sum (S⁻)",
        color: "var(--accent-3)",
        points: indexed.map((p) => ({ x: p.index, y: p.s_lo })),
      },
      {
        name: "Decision limit H",
        color: "var(--critical)",
        dashed: true,
        width: 1.3,
        step: true,
        points: indexed.map((p) => ({ x: p.index, y: p.limit })),
      },
    ],
    markers: indexed
      .filter((p) => p.signal)
      .map((p) => ({ x: p.index, y: Math.max(p.s_hi ?? 0, p.s_lo ?? 0) })),
    tooltip: (index) => {
      const point = indexed[index];
      const when = new Date(point.time).toLocaleString(undefined, {
        day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
      });
      return (
        `<strong>${when}</strong><br>` +
        `observed ${formatTick(point.value)} kWh · expected ${formatTick(point.mu0)}<br>` +
        `S⁺ ${formatTick(point.s_hi)} · S⁻ ${formatTick(point.s_lo)} · H ${formatTick(point.limit)}` +
        (point.signal ? '<br><strong style="color:var(--critical)">out of control</strong>' : "")
      );
    },
  });
}

/* ----------------------------------------------------------------------
   Small multiples — one panel per day of the week (figure 4.17).
---------------------------------------------------------------------- */
export function renderSmallMultiples(container, panels, config = {}) {
  container.innerHTML = "";
  if (!panels || !panels.length) {
    emptyNote(container, config.emptyMessage ?? "No profiles to compare yet.");
    return;
  }

  // A shared y scale across panels — otherwise each panel silently
  // renormalises and Saturday looks as busy as Wednesday.
  const sharedMax = Math.max(
    ...panels.flatMap((panel) => panel.points.map((p) => p.y ?? 0)),
    0.0001
  );

  const grid = document.createElement("div");
  grid.className = "small-multiples";
  container.appendChild(grid);

  // Two passes on purpose. Each plot sizes itself from its container's
  // clientWidth, and a CSS grid only settles its column widths once every cell
  // is in it — rendering as the cells were appended measured the first panel
  // against a one-column grid and produced a viewBox four times too wide,
  // shrinking its axis labels to nothing.
  const holders = panels.map((panel) => {
    const cell = document.createElement("div");
    cell.className = "small-multiple";
    const title = document.createElement("div");
    title.className = "small-multiple-title";
    title.textContent = panel.label;
    const plotHolder = document.createElement("div");
    cell.append(title, plotHolder);
    grid.appendChild(cell);
    return plotHolder;
  });

  panels.forEach((panel, index) => {
    renderLineChart(holders[index], {
      height: 118,
      padLeft: 32,
      padBottom: 20,
      padTop: 8,
      minWidth: 140,
      yMax: sharedMax * 1.08,
      xDomain: [0, 23],
      xTicks: [0, 6, 12, 18].map((hour) => ({ value: hour, label: `${hour}h` })),
      legend: false,
      ariaLabel: `${panel.label} average power profile`,
      series: [{ color: panel.color ?? "var(--accent)", points: panel.points }],
      emptyMessage: "no data",
    });
  });
}
