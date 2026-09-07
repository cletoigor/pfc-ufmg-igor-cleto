// pages/analysis.js — "Advanced Analysis": statistical process control.
//
// Mirrors figures 4.16 to 4.18: the multichannel CUSUM chart with adjustable
// k and h and its fault log, average profiles per day of the week, recent weeks
// against the historical mean, and the power peaks table.
//
// One deliberate deviation from the monograph: figure 4.18 is a 3D surface.
// This frontend has no charting library and loads nothing from a CDN, and a
// hand-projected 3D plot the reader cannot rotate would carry less information
// than the 2D overlay used here — recent weeks drawn over a bold historical
// mean. The substitution is stated on the page itself, not just in the code.

import { renderCusumChart, renderLineChart, renderSmallMultiples } from "../charts.js";
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
  formatWatts,
  metricRow,
  select,
  slider,
  spinnerRow,
  table,
} from "../ui.js";

const WEEK_COLORS = ["var(--accent)", "var(--accent-4)", "var(--accent-2)", "var(--accent-3)"];

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
  if (!state.focusDevice || !devices.includes(state.focusDevice)) {
    state.focusDevice = devices[0];
  }

  clear(container);
  const cusumHolder = el("div");
  const profilesHolder = el("div");
  const weeklyHolder = el("div");
  const peaksHolder = el("div");
  container.append(cusumHolder, profilesHolder, weeklyHolder, peaksHolder);

  // Four independent requests; render each as it lands rather than waiting for
  // the slowest.
  renderCusumSection(cusumHolder, devices);
  renderProfileSections(profilesHolder, weeklyHolder);
  renderPeaks(peaksHolder);
}

/* ------------------------------------------------------------------ CUSUM */

async function renderCusumSection(holder, devices) {
  clear(holder);
  const { wrapper, body } = card("Statistical process control — CUSUM", {
    subtitle:
      "Each hour of the day is its own channel: a reading is judged against the " +
      "same hour on other days, never against the daily average.",
  });
  holder.appendChild(wrapper);

  body.appendChild(buildCusumControls(devices));
  const chartHolder = el("div");
  body.appendChild(chartHolder);
  chartHolder.appendChild(spinnerRow("Running the control chart…"));

  const params = windowParams({
    device: state.focusDevice,
    k: state.cusum.k,
    h: state.cusum.h,
  });
  // The baseline needs the full history to be meaningful, so the chart is not
  // narrowed by the sidebar's device filter — only by the chosen device.
  params.delete("devices");

  const { ok, data } = await getJSON(`/api/analysis/cusum?${params.toString()}`);
  clear(chartHolder);

  if (!ok && !data) {
    chartHolder.appendChild(emptyState("Could not reach the API."));
    return;
  }
  if (!data || data.empty) {
    chartHolder.appendChild(
      emptyState(
        data?.empty_reason ?? "No baseline available.",
        "Materialize `gold_energy_metrics` to build the Phase I baseline."
      )
    );
    return;
  }

  chartHolder.appendChild(
    metricRow([
      { label: "Observations", value: String(data.monitored_count), sub: "monitored" },
      { label: "Unmonitored", value: String(data.skipped_count), sub: "no usable baseline" },
      {
        label: "Signals",
        value: String((data.faults ?? []).length),
        sub: (data.faults ?? []).length ? "out of control" : "in control",
      },
      { label: "Allowance / limit", value: `k=${data.k} · h=${data.h}` },
    ])
  );

  const chart = el("div", "chart-holder");
  chartHolder.appendChild(chart);
  renderCusumChart(chart, data.points, {});

  chartHolder.appendChild(el("h3", "card-subtitle", "Fault log"));
  const faults = data.faults ?? [];
  if (!faults.length) {
    chartHolder.appendChild(
      emptyState(
        "No out-of-control signals in this period.",
        `Both cumulative sums stayed below H = ${data.h}·σ₀ for every channel.`
      )
    );
  } else {
    chartHolder.appendChild(
      table(
        ["When", "Hour", "Direction", "Observed", "Expected", "Sum", "Limit"],
        faults.map((fault) => [
          formatDateTime(fault.time),
          `${String(fault.hour).padStart(2, "0")}:00`,
          fault.direction === "high" ? "above baseline" : "below baseline",
          formatKwh(fault.value),
          formatKwh(fault.expected),
          String(fault.cusum),
          String(fault.limit),
        ]),
        { rowClass: (row) => (row[2].startsWith("above") ? "row-high" : "row-low") }
      )
    );
  }
}

function buildCusumControls(devices) {
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

  bar.appendChild(
    slider({
      label: "Allowance k",
      min: 0,
      max: 2,
      step: 0.05,
      value: state.cusum.k,
      format: (value) => `${value.toFixed(2)}·σ₀`,
      onChange: (value) => {
        state.cusum.k = value;
        render();
      },
    })
  );

  bar.appendChild(
    slider({
      label: "Decision limit h",
      min: 1,
      max: 10,
      step: 0.5,
      value: state.cusum.h,
      format: (value) => `${value.toFixed(1)}·σ₀`,
      onChange: (value) => {
        state.cusum.h = value;
        render();
      },
    })
  );

  return bar;
}

/* --------------------------------------------------------------- profiles */

async function renderProfileSections(dailyHolder, weeklyHolder) {
  clear(dailyHolder);
  clear(weeklyHolder);

  const daily = card("Average profile by day of week", {
    subtitle: `Mean power for the selected devices, ${periodLabel()}. All seven panels share one scale.`,
  });
  const weekly = card("Recent weeks against the historical mean", {
    subtitle:
      "The monograph shows this as a 3D surface (figure 4.18). It is drawn here " +
      "as a 2D overlay — the same comparison, without a projection you cannot rotate.",
  });
  dailyHolder.appendChild(daily.wrapper);
  weeklyHolder.appendChild(weekly.wrapper);
  daily.body.appendChild(spinnerRow("Building profiles…"));
  weekly.body.appendChild(spinnerRow("Building weekly comparison…"));

  const { ok, data } = await getJSON(`/api/analysis/profiles?${windowParams().toString()}`);
  clear(daily.body);
  clear(weekly.body);

  if (!ok || !data || data.empty) {
    const message = data?.empty_reason ?? "Could not load the profiles.";
    daily.body.appendChild(emptyState(message));
    weekly.body.appendChild(emptyState(message));
    return;
  }

  const panels = (data.daily_profiles ?? []).map((profile) => ({
    label: profile.label,
    points: profile.points.map((point) => ({ x: point.hour, y: point.power_w })),
  }));
  renderSmallMultiples(daily.body, panels, {});

  const weeks = data.weekly?.weeks ?? [];
  const dayFormat = new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short" });
  const series = [
    ...weeks.map((week, index) => ({
      name: `week of ${dayFormat.format(new Date(week.week_start))}`,
      color: WEEK_COLORS[index % WEEK_COLORS.length],
      width: 1.1,
      opacity: 0.75,
      points: week.points.map((point) => ({ x: point.hour_of_week, y: point.power_w })),
    })),
    {
      name: "historical mean",
      color: "var(--ink-1)",
      width: 2.2,
      points: (data.weekly?.historical_mean ?? []).map((point) => ({
        x: point.hour_of_week,
        y: point.power_w,
      })),
    },
  ];

  const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const chart = el("div", "chart-holder");
  weekly.body.appendChild(chart);
  renderLineChart(chart, {
    height: 250,
    xDomain: [0, 167],
    xTicks: dayNames.map((name, index) => ({ value: index * 24 + 12, label: name, grid: index > 0 })),
    ariaLabel: "Weekly power profiles compared with the historical mean",
    series,
  });
}

/* ------------------------------------------------------------------ peaks */

async function renderPeaks(holder) {
  clear(holder);
  const { wrapper, body } = card("Power peaks", {
    subtitle: `The heaviest hours across the selected devices, ${periodLabel()}.`,
  });
  holder.appendChild(wrapper);
  body.appendChild(spinnerRow("Finding peaks…"));

  const { ok, data } = await getJSON(
    `/api/analysis/peaks?${windowParams({ limit: 12 }).toString()}`
  );
  clear(body);

  if (!ok || !data || data.empty || !(data.peaks ?? []).length) {
    body.appendChild(emptyState(data?.empty_reason ?? "No peaks recorded in this period."));
    return;
  }

  body.appendChild(
    table(
      ["Device", "When", "Peak power", "Mean that hour", "Energy"],
      data.peaks.map((peak) => [
        peak.device,
        formatDateTime(peak.time),
        formatWatts(peak.peak_w),
        formatWatts(peak.mean_w),
        formatKwh(peak.energy_kwh),
      ])
    )
  );
}
