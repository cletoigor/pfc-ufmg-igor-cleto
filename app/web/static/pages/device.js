// pages/device.js — "Device Details": one device, in depth.
//
// Mirrors figures 4.8 to 4.15: energy over the reference periods, power
// statistics and time series, daily energy, the device's average day, and
// collapsible voltage and current sections, each with a series over time.

import { renderLineChart } from "../charts.js";
import {
  activeDevices,
  formatDateTime,
  getJSON,
  periodLabel,
  state,
  windowParams,
} from "../state.js";
import {
  card,
  clear,
  el,
  emptyState,
  formatKwh,
  formatUnit,
  formatWatts,
  metricRow,
  select,
  spinnerRow,
} from "../ui.js";

const TOTAL_LABELS = {
  today: "Today",
  last_7_days: "Last 7 days",
  this_month: "Last 30 days",
};

let container = null;

export function mount(node) {
  container = node;
}

export async function render() {
  if (!container) return;

  const devices = activeDevices();
  if (!devices.length) {
    clear(container).appendChild(
      emptyState("No devices selected.", "Pick at least one device in the sidebar.")
    );
    return;
  }

  // Keep the previous choice when it is still selectable, so changing the
  // period does not silently jump to another device.
  if (!state.focusDevice || !devices.includes(state.focusDevice)) {
    state.focusDevice = devices[0];
  }

  clear(container);
  container.appendChild(buildPicker(devices));
  const content = el("div", "page-content");
  container.appendChild(content);
  content.appendChild(spinnerRow(`Loading ${state.focusDevice}…`));

  const url = `/api/device/${encodeURIComponent(state.focusDevice)}/summary?${windowParams().toString()}`;
  const { ok, data } = await getJSON(url);
  clear(content);

  if (!ok && !data) {
    content.appendChild(emptyState("Could not reach the API."));
    return;
  }
  if (!data || data.empty) {
    content.appendChild(
      emptyState(
        data?.empty_reason ?? "No readings for this device.",
        "This device may not have reported any electrical datapoints in the selected period."
      )
    );
    return;
  }

  // Cards attach before their charts draw: an SVG sizes itself from its
  // container's width, and a detached card measures zero.
  renderEnergy(content, data);
  renderPower(content, data);
  renderProfile(content, data);
  renderMeasurement(content, data.voltage, "Voltage", "V", 1);
  renderMeasurement(content, data.current, "Current", "mA", 0);
}

function buildPicker(devices) {
  const bar = el("div", "page-toolbar");
  bar.appendChild(
    select(
      devices,
      state.focusDevice,
      (value) => {
        state.focusDevice = value;
        render();
      },
      { label: "Device" }
    )
  );
  bar.appendChild(el("span", "toolbar-note", `Showing ${periodLabel()}.`));
  return bar;
}

function renderEnergy(parent, data) {
  const { wrapper, body } = card("Energy consumed", {
    subtitle: `${data.device}, over the monograph's three reference periods.`,
  });
  parent.appendChild(wrapper);
  body.appendChild(
    metricRow(
      (data.totals ?? []).map((total) => ({
        label: TOTAL_LABELS[total.key] ?? total.key,
        value: formatKwh(total.energy_kwh),
      }))
    )
  );
}

function renderPower(parent, data) {
  const { wrapper, body } = card("Power", { subtitle: `Over ${periodLabel()}.` });
  parent.appendChild(wrapper);

  body.appendChild(
    metricRow([
      { label: "Mean", value: formatWatts(data.power?.mean_w) },
      { label: "Maximum", value: formatWatts(data.power?.max_w) },
      { label: "Minimum", value: formatWatts(data.power?.min_w) },
      { label: "Energy", value: formatKwh(data.power?.energy_kwh) },
    ])
  );

  const series = data.power_series ?? [];
  const chart = el("div", "chart-holder");
  body.append(el("h3", "card-subtitle", "Power over time"), chart);
  renderTimeSeries(chart, series, "power_w", (entry) => formatWatts(entry.power_w), "Power (W)");

  const daily = data.daily_energy ?? [];
  if (daily.length > 1) {
    const dailyChart = el("div", "chart-holder");
    body.append(el("h3", "card-subtitle", "Energy per day"), dailyChart);
    const dayFormat = new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short" });
    renderLineChart(dailyChart, {
      height: 170,
      xDomain: [0, daily.length - 1],
      xTicks: daily.map((entry, index) => ({
        value: index,
        label: dayFormat.format(new Date(entry.day)),
      })),
      ariaLabel: `Daily energy for ${data.device}`,
      series: [{ points: daily.map((entry, index) => ({ x: index, y: entry.energy_kwh })), color: "var(--accent)" }],
      tooltip: (index) =>
        `<strong>${dayFormat.format(new Date(daily[index].day))}</strong><br>${formatKwh(daily[index].energy_kwh)}`,
    });
  }
}

function renderProfile(parent, data) {
  const { wrapper, body } = card("Average day", {
    subtitle: `The typical shape of ${data.device}'s day.`,
  });
  parent.appendChild(wrapper);
  const profile = data.hourly_profile ?? [];
  const chart = el("div", "chart-holder");
  body.appendChild(chart);

  renderLineChart(chart, {
    height: 190,
    xDomain: [0, 23],
    xTicks: Array.from({ length: 24 }, (_, hour) => ({ value: hour, label: `${hour}h` })),
    ariaLabel: `Average hourly power profile for ${data.device}`,
    series: [{ points: profile.map((entry) => ({ x: entry.hour, y: entry.power_w })), color: "var(--accent)" }],
    emptyMessage: "No readings in this period.",
    tooltip: (index) => {
      const entry = profile[index];
      return (
        `<strong>${String(entry.hour).padStart(2, "0")}:00</strong><br>` +
        `${formatWatts(entry.power_w)} average · ${formatKwh(entry.energy_kwh)} per hour`
      );
    },
  });
}

/**
 * Voltage and current, in a collapsed <details> as the monograph describes —
 * they matter when diagnosing, and would otherwise push the power charts
 * (which are what you look at first) off the screen.
 */
function renderMeasurement(parent, block, title, unit, digits) {
  const wrapper = el("details", "card card-collapsible");
  parent.appendChild(wrapper);
  const summary = el("summary", "card-head");
  const titles = el("div");
  titles.appendChild(el("h2", "card-title", title));
  titles.appendChild(
    el("p", "card-sub", block?.mean !== null && block?.mean !== undefined
      ? `mean ${formatUnit(block.mean, unit, digits)}`
      : "no readings")
  );
  summary.appendChild(titles);
  wrapper.appendChild(summary);

  const body = el("div", "card-body");
  wrapper.appendChild(body);

  if (!block || !(block.series ?? []).length) {
    body.appendChild(emptyState(`No ${title.toLowerCase()} readings in this period.`));
    return;
  }

  body.appendChild(
    metricRow([
      { label: "Mean", value: formatUnit(block.mean, unit, digits) },
      { label: "Maximum", value: formatUnit(block.max, unit, digits) },
      { label: "Minimum", value: formatUnit(block.min, unit, digits) },
    ])
  );

  const seriesChart = el("div", "chart-holder");
  body.append(el("h3", "card-subtitle", `${title} over time`), seriesChart);

  // Drawn on first expand, not now: a closed <details> has zero width, and a
  // chart sized against that would be laid out for a container it never had.
  let drawn = false;
  const draw = () => {
    if (drawn) return;
    drawn = true;
    renderTimeSeries(
      seriesChart,
      block.series,
      "value",
      (entry) => formatUnit(entry.value, unit, digits),
      `${title} (${unit})`,
      // Voltage sits in a narrow band around 127 V; a zero-based axis would
      // flatten every variation that matters into one line.
      { zeroBased: false }
    );
  };
  wrapper.addEventListener("toggle", () => {
    if (wrapper.open) draw();
  });
}


function renderTimeSeries(holder, series, valueKey, formatValue, label, extra = {}) {
  if (!series.length) {
    holder.innerHTML = '<p class="empty-note">No readings in this period.</p>';
    return;
  }

  const dayFormat = new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short" });
  const xTicks = [];
  let lastDay = null;
  series.forEach((entry, index) => {
    const date = new Date(entry.time);
    const day = date.toDateString();
    if (day !== lastDay) {
      xTicks.push({ value: index, label: dayFormat.format(date), grid: true });
      lastDay = day;
    }
  });

  renderLineChart(holder, {
    height: 210,
    xDomain: [0, series.length - 1 || 1],
    xTicks,
    ariaLabel: label,
    series: [{ points: series.map((entry, index) => ({ x: index, y: entry[valueKey] })), color: "var(--accent)" }],
    tooltip: (index) =>
      `<strong>${formatDateTime(series[index].time)}</strong><br>${formatValue(series[index])}`,
    ...extra,
  });
}
