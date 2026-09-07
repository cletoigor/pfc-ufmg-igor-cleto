// pages/summary.js — "House Summary": the consolidated view of the whole home.
//
// Mirrors section 4.3.2's "Resumo da Casa": total energy over three reference
// periods, the top five consumers, the house's average shape of a day, plus the
// on/off timeline and on-time ranking the original dashboard already had.

import { renderLineChart, renderRankedBars, renderTimeline, renderOnTimeBars } from "../charts.js";
import { getJSON, periodLabel, state, windowParams } from "../state.js";
import { card, clear, el, emptyState, formatKwh, formatWatts, metricRow, spinnerRow } from "../ui.js";

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
  clear(container).appendChild(spinnerRow("Loading house summary…"));

  const { ok, data } = await getJSON(`/api/house/summary?${windowParams().toString()}`);
  clear(container);

  if (!ok || !data) {
    container.appendChild(
      emptyState("Could not reach the API.", "Is `python -m app.api.server` still running?")
    );
    renderActivitySection();
    return;
  }

  if (data.empty) {
    container.appendChild(
      emptyState(
        data.empty_reason ?? "No energy data yet.",
        "Run `python scripts/seed_synthetic_data.py`, then materialize " +
          "`staging_tuya_logs` and `gold_energy_metrics`."
      )
    );
    renderActivitySection();
    return;
  }

  // Each section attaches its card to the page *before* drawing into it: a
  // chart measures its container's width to size the SVG, and a card that is
  // not in the document yet measures zero.
  renderTotals(data);
  renderConsumers(data);
  renderHouseProfile(data);
  renderActivitySection();
}

function renderTotals(data) {
  const { wrapper, body } = card("Energy consumed", {
    subtitle: "Whole house, over the monograph's three reference periods.",
  });
  container.appendChild(wrapper);
  const metrics = (data.totals ?? []).map((total) => ({
    label: TOTAL_LABELS[total.key] ?? total.key,
    value: formatKwh(total.energy_kwh),
    sub: total.key === "today" ? "most recent day in the data" : null,
  }));
  metrics.push({
    label: "Selected period",
    value: formatKwh(data.total_kwh),
    sub: periodLabel(),
  });
  body.appendChild(metricRow(metrics));
}

function renderConsumers(data) {
  const { wrapper, body } = card("Top consumers", {
    subtitle: `The five hungriest devices over ${periodLabel()}.`,
  });
  container.appendChild(wrapper);

  const rows = (data.top_consumers ?? []).map((entry) => ({
    label: entry.device,
    value: entry.energy_kwh ?? 0,
    share: entry.share ?? 0,
  }));

  if (!rows.length) {
    body.appendChild(emptyState("No consumption recorded in this period."));
    return;
  }

  const chart = el("div", "chart-holder");
  body.appendChild(chart);
  renderRankedBars(chart, rows, {
    format: (value) => formatKwh(value),
    ariaLabel: "Energy consumed per device",
    tooltip: (row) =>
      `<strong>${row.label}</strong><br>${formatKwh(row.value)} · ` +
      `${Math.round((row.share ?? 0) * 100)}% of the period`,
  });
}

function renderHouseProfile(data) {
  const { wrapper, body } = card("Average day", {
    subtitle: "Mean power drawn by the whole house, by hour of the day.",
  });
  container.appendChild(wrapper);

  const points = (data.hourly_profile ?? []).map((entry) => ({
    x: entry.hour,
    y: entry.power_w,
  }));

  const chart = el("div", "chart-holder");
  body.appendChild(chart);
  renderLineChart(chart, {
    height: 200,
    xDomain: [0, 23],
    xTicks: Array.from({ length: 24 }, (_, hour) => ({ value: hour, label: `${hour}h` })),
    ariaLabel: "Average hourly power profile for the house",
    series: [{ points, color: "var(--accent)" }],
    emptyMessage: "No readings in this period.",
    tooltip: (index) => {
      const entry = data.hourly_profile[index];
      return (
        `<strong>${String(entry.hour).padStart(2, "0")}:00</strong><br>` +
        `${formatWatts(entry.power_w)} average · ${formatKwh(entry.energy_kwh)} per hour`
      );
    },
  });

  // Daily totals sit under the profile: same page, different question ("which
  // days were heavy" rather than "which hours").
  if ((data.daily_energy ?? []).length > 1) {
    const dailyTitle = el("h3", "card-subtitle", "Energy per day");
    const dailyChart = el("div", "chart-holder");
    body.append(dailyTitle, dailyChart);
    const dayFormat = new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short" });
    renderLineChart(dailyChart, {
      height: 160,
      xDomain: [0, data.daily_energy.length - 1],
      xTicks: data.daily_energy.map((entry, index) => ({
        value: index,
        label: dayFormat.format(new Date(entry.day)),
      })),
      ariaLabel: "Energy consumed per day",
      series: [
        {
          points: data.daily_energy.map((entry, index) => ({ x: index, y: entry.energy_kwh })),
          color: "var(--accent)",
        },
      ],
      tooltip: (index) => {
        const entry = data.daily_energy[index];
        return `<strong>${dayFormat.format(new Date(entry.day))}</strong><br>${formatKwh(entry.energy_kwh)}`;
      },
    });
  }
}

/**
 * The on/off view. Its data comes from `state.overview`, which the shell
 * already fetches for the sidebar, so this section costs no extra request.
 */
function renderActivitySection() {
  const overview = state.overview;
  const { wrapper, body } = card("When devices were on", {
    subtitle: "Contiguous on-intervals, and total on-time per device.",
  });
  container.appendChild(wrapper);

  if (!overview || overview.empty) {
    body.appendChild(emptyState(overview?.empty_reason ?? "No activity data yet."));
    return;
  }

  const timelineHolder = el("div", "chart-holder");
  const onTimeHolder = el("div", "chart-holder");
  body.append(timelineHolder, el("h3", "card-subtitle", "Total time on"), onTimeHolder);

  renderTimeline(timelineHolder, overview.timeline, {
    latestEvent: overview.latest_event,
    windowStart: overview.window?.start,
    windowEnd: overview.window?.end,
  });
  renderOnTimeBars(onTimeHolder, overview.on_time);
}
