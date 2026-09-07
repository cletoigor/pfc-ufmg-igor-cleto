// app.js — the shell: sidebar filters, system status, routing, and boot.
//
// The four views live in ./pages/, the chat panel in ./agent.js, the charts in
// ./charts.js and the shared filter state in ./state.js. This file owns only
// what surrounds them: the global period and device controls (which the
// monograph puts in the sidebar so one selection applies everywhere), the
// health block, and wiring the router.
//
// Still no build step, no npm and no CDN — native ES modules and relative
// imports, so nothing external can fail mid-demo.

import { updateAgentAvailability, wireAgentPanel } from "./agent.js";
import { debounce } from "./charts.js";
import { registerRoute, renderActiveRoute, startRouter } from "./router.js";
import { wireThemeToggle } from "./theme.js";
import {
  formatDay,
  getJSON,
  onFiltersChanged,
  state,
  toDateInput,
  windowParams,
} from "./state.js";
import * as actuationsPage from "./pages/actuations.js";
import * as analysisPage from "./pages/analysis.js";
import * as devicePage from "./pages/device.js";
import * as summaryPage from "./pages/summary.js";

const FIXTURE_URL = "./static/fixture.json";

const HEALTH_FALLBACK = {
  data_source: null,
  latest_event: null,
  freshness_label: "unavailable",
  provider: "gemini",
  provider_label: "Gemini",
  model: "gemini-3.8-flash",
  available: false,
  guidance:
    "Set GEMINI_API_KEY (free key from Google AI Studio: aistudio.google.com) to enable the agent.",
};

/* ----------------------------------------------------------------------
   Period presets.

   "Today" and "Yesterday" are absolute dates, not trailing windows, so they
   are resolved against the newest day in the dataset rather than against the
   wall clock — this is a fixed historical dataset, and anchoring to the real
   today would select a period containing nothing.
---------------------------------------------------------------------- */
const PRESETS = {
  today: { label: "Today", resolve: (latest) => ({ start: dayOffset(latest, 0), end: dayOffset(latest, 0) }) },
  yesterday: { label: "Yesterday", resolve: (latest) => ({ start: dayOffset(latest, -1), end: dayOffset(latest, -1) }) },
  "7d": { label: "7 days", resolve: () => ({ days: 7 }) },
  "30d": { label: "30 days", resolve: () => ({ days: 30 }) },
  all: { label: "All", resolve: () => ({ days: "all" }) },
  custom: { label: "Custom", resolve: null },
};

function dayOffset(latestIso, offset) {
  const base = latestIso ? new Date(latestIso) : new Date();
  base.setDate(base.getDate() + offset);
  return toDateInput(base);
}

function applyPreset(preset) {
  state.preset = preset;
  if (preset === "custom") return; // the date inputs drive it

  const resolved = PRESETS[preset].resolve(state.latestEvent);
  state.start = resolved.start ?? null;
  state.end = resolved.end ?? null;
  state.days = resolved.days ?? 7;
}

/* ----------------------------------------------------------------------
   Data fetching
---------------------------------------------------------------------- */
async function fetchOverview() {
  const { ok, data } = await getJSON(`/api/overview?${windowParams().toString()}`);
  if (ok && data) {
    state.usingFixture = false;
    return data;
  }
  // The API is unreachable — fall back to the bundled sample so the UI is
  // still developable and demonstrable standalone.
  state.usingFixture = true;
  const fixture = await getJSON(FIXTURE_URL);
  return fixture.data ? applyClientFilters(fixture.data) : null;
}

/** Approximates the server-side filters over the offline fixture. */
function applyClientFilters(data) {
  const devices = state.selectedDevices;
  const cutoff = state.days === "all" || state.start ? null : Date.now() - state.days * 86400000;

  const filterByDevice = (name) => !devices || devices.size === 0 || devices.has(name);
  const withinWindow = (isoString) => (cutoff ? new Date(isoString).getTime() >= cutoff : true);

  return {
    ...data,
    timeline: {
      lanes: data.timeline.lanes.filter(filterByDevice),
      intervals: data.timeline.intervals.filter(
        (iv) => filterByDevice(iv.device) && withinWindow(iv.end)
      ),
    },
    on_time: data.on_time.filter((d) => filterByDevice(d.device)),
  };
}

/* ----------------------------------------------------------------------
   Sidebar
---------------------------------------------------------------------- */
function renderDeviceFilter(overview) {
  const list = document.getElementById("device-filter");
  const allDevices = overview?.all_devices ?? [];
  const deviceByName = new Map((overview?.devices ?? []).map((d) => [d.name, d]));

  if (state.selectedDevices === null) {
    state.selectedDevices = new Set(allDevices);
  }

  list.innerHTML = "";
  allDevices.forEach((name) => {
    const info = deviceByName.get(name);
    const li = document.createElement("li");
    li.className = "device-filter-item";
    li.style.padding = "0";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selectedDevices.has(name);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selectedDevices.add(name);
      else state.selectedDevices.delete(name);
      refresh();
    });

    const stateClass =
      info?.state === "on" ? "is-on" : info?.state === "off" ? "is-off" : "is-unknown";
    const dot = document.createElement("span");
    dot.className = `state-dot ${stateClass}`;

    const nameEl = document.createElement("span");
    nameEl.className = "dfi-name";
    nameEl.textContent = name;
    nameEl.title = info?.detail ?? name;

    const seenEl = document.createElement("span");
    seenEl.className = "dfi-seen";
    seenEl.textContent = info?.last_seen_label ?? "";

    const label = document.createElement("label");
    label.className = "device-filter-item";
    label.style.padding = "0";
    label.style.width = "100%";
    label.append(checkbox, dot, nameEl, seenEl);

    li.appendChild(label);
    list.appendChild(li);
  });
}

function wireDeviceToggleAll() {
  const btn = document.getElementById("device-toggle-all");
  btn.addEventListener("click", () => {
    const allDevices = state.overview?.all_devices ?? [];
    const allSelected = state.selectedDevices?.size === allDevices.length;
    state.selectedDevices = allSelected ? new Set() : new Set(allDevices);
    btn.textContent = allSelected ? "Select all" : "Clear";
    renderDeviceFilter(state.overview);
    refresh();
  });
}

function renderSystemBlock(health) {
  document.getElementById("sys-source").textContent = health.data_source ?? "unavailable";
  document.getElementById("sys-freshness").textContent = health.freshness_label ?? "—";
  document.getElementById("sys-model").textContent = health.model
    ? `${health.provider_label ?? health.provider} · ${health.model}`
    : "—";

  const statusEl = document.getElementById("sys-agent-status");
  statusEl.textContent = health.available ? "Ready" : "Unavailable";
  statusEl.style.color = health.available ? "var(--good)" : "var(--critical)";

  const guidanceEl = document.getElementById("sys-guidance");
  if (!health.available && health.guidance) {
    guidanceEl.textContent = health.guidance;
    guidanceEl.hidden = false;
  } else {
    guidanceEl.hidden = true;
  }

  updateAgentAvailability(health.available);
}

/* ----------------------------------------------------------------------
   Topbar
---------------------------------------------------------------------- */
function relativeFromNow(isoString) {
  if (!isoString) return "";
  const mins = Math.round((Date.now() - new Date(isoString).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function renderTopbar(overview) {
  const sub = document.getElementById("topbar-updated");
  const sourceLabel = state.usingFixture ? "offline sample data" : overview?.source ?? "warehouse";
  sub.textContent = overview?.latest_event
    ? `Latest event ${relativeFromNow(overview.latest_event)} · source: ${sourceLabel}`
    : `Source: ${sourceLabel}`;
}

/* ----------------------------------------------------------------------
   Refresh cycle

   One overview fetch feeds the sidebar (device list and states), the topbar
   and the House Summary's activity charts; the active page then fetches
   whatever else it needs.
---------------------------------------------------------------------- */
async function refresh() {
  const refreshBtn = document.getElementById("refresh-btn");
  refreshBtn.classList.add("is-loading");

  try {
    const overview = await fetchOverview();
    state.overview = overview;
    state.latestEvent = overview?.latest_event ?? null;

    if (state.selectedDevices === null) {
      state.selectedDevices = new Set(overview?.all_devices ?? []);
    }

    renderDeviceFilter(overview);
    renderTopbar(overview);
    renderActiveRoute();
  } finally {
    refreshBtn.classList.remove("is-loading");
  }
}

async function refreshHealth() {
  const { ok, data } = await getJSON("/api/health");
  renderSystemBlock(ok && data ? data : HEALTH_FALLBACK);
}

/* ----------------------------------------------------------------------
   Filters — period
---------------------------------------------------------------------- */
function wireRangeControl() {
  const control = document.getElementById("range-control");
  const customRow = document.getElementById("custom-range");
  const startInput = document.getElementById("range-start");
  const endInput = document.getElementById("range-end");

  control.addEventListener("click", (evt) => {
    const btn = evt.target.closest(".segmented-btn");
    if (!btn) return;
    control.querySelectorAll(".segmented-btn").forEach((b) => b.classList.remove("is-active"));
    btn.classList.add("is-active");

    const preset = btn.dataset.preset;
    applyPreset(preset);

    customRow.hidden = preset !== "custom";
    if (preset === "custom") {
      // Seed the pickers with the current window so the first custom view is
      // not an empty range.
      startInput.value = state.start ?? dayOffset(state.latestEvent, -6);
      endInput.value = state.end ?? dayOffset(state.latestEvent, 0);
      state.start = startInput.value;
      state.end = endInput.value;
    }
    updatePeriodCaption();
    refresh();
  });

  [startInput, endInput].forEach((input) =>
    input.addEventListener("change", () => {
      if (!startInput.value || !endInput.value) return;
      // A backwards range would silently return nothing; swap instead.
      if (startInput.value > endInput.value) {
        const swap = startInput.value;
        startInput.value = endInput.value;
        endInput.value = swap;
      }
      state.preset = "custom";
      state.start = startInput.value;
      state.end = endInput.value;
      updatePeriodCaption();
      refresh();
    })
  );
}

function updatePeriodCaption() {
  const caption = document.getElementById("range-caption");
  if (!caption) return;
  if (state.start && state.end) {
    caption.textContent =
      state.start === state.end
        ? formatDay(state.start)
        : `${formatDay(state.start)} – ${formatDay(state.end)}`;
  } else if (state.days === "all") {
    caption.textContent = "All recorded history";
  } else {
    caption.textContent = `Trailing ${state.days} days`;
  }
}

function wireRefreshButton() {
  document.getElementById("refresh-btn").addEventListener("click", () => {
    refresh();
    refreshHealth();
  });
}

/* ----------------------------------------------------------------------
   Boot
---------------------------------------------------------------------- */
function registerRoutes() {
  summaryPage.mount(document.getElementById("view-summary-body"));
  devicePage.mount(document.getElementById("view-device-body"));
  analysisPage.mount(document.getElementById("view-analysis-body"));
  actuationsPage.mount(document.getElementById("view-actuations-body"));

  registerRoute("summary", {
    sectionId: "view-summary",
    navId: "nav-summary",
    title: "House summary",
    render: summaryPage.render,
  });
  registerRoute("device", {
    sectionId: "view-device",
    navId: "nav-device",
    title: "Device details",
    render: devicePage.render,
  });
  registerRoute("analysis", {
    sectionId: "view-analysis",
    navId: "nav-analysis",
    title: "Advanced analysis",
    render: analysisPage.render,
  });
  registerRoute("actuations", {
    sectionId: "view-actuations",
    navId: "nav-actuations",
    title: "Actuations",
    render: actuationsPage.render,
  });
}

// Charts are sized from their container's width, so a resize needs a redraw.
const rerenderOnResize = debounce(() => renderActiveRoute(), 180);
window.addEventListener("resize", rerenderOnResize);

function init() {
  registerRoutes();
  wireRangeControl();
  wireRefreshButton();
  wireDeviceToggleAll();
  wireAgentPanel();
  wireThemeToggle();
  onFiltersChanged(renderActiveRoute);
  updatePeriodCaption();

  startRouter();
  refresh();
  refreshHealth();
}

document.addEventListener("DOMContentLoaded", init);
