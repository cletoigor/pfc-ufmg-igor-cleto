// app.js — wiring for the Home IoT Copilot dashboard.
// Talks to /api/overview, /api/health and /api/agent/stream per
// docs/api_contract.md. Falls back to static/fixture.json for overview
// when the API isn't reachable yet, so the UI is developable standalone.

import { renderSparkline, renderTimeline, renderOnTimeBars, debounce } from "./charts.js";

const FIXTURE_URL = "./static/fixture.json";

const HEALTH_FALLBACK = {
  data_source: null,
  latest_event: null,
  freshness_label: "unavailable",
  provider: "gemini",
  provider_label: "Gemini",
  model: "gemini-2.5-flash",
  available: false,
  guidance: "Set GEMINI_API_KEY (free key from Google AI Studio: aistudio.google.com) to enable the agent.",
};

const state = {
  days: 7,
  selectedDevices: null, // null == all devices
  overview: null,
  usingFixture: false,
  dryRun: true,
  eventSource: null,
};

/* ----------------------------------------------------------------------
   Data fetching
---------------------------------------------------------------------- */
async function fetchOverview() {
  const params = new URLSearchParams();
  params.set("days", String(state.days));
  if (state.selectedDevices && state.selectedDevices.size > 0) {
    params.set("devices", Array.from(state.selectedDevices).join(","));
  }

  try {
    const res = await fetch(`/api/overview?${params.toString()}`);
    if (!res.ok) throw new Error(`status ${res.status}`);
    const data = await res.json();
    state.usingFixture = false;
    return data;
  } catch (err) {
    state.usingFixture = true;
    const res = await fetch(FIXTURE_URL);
    const fixture = await res.json();
    return applyClientFilters(fixture);
  }
}

/** Fixture doesn't know about filters server-side, so approximate them here
 *  to keep the offline demo interactive. Real API responses are already
 *  filtered and skip this entirely. */
function applyClientFilters(data) {
  const devices = state.selectedDevices;
  const cutoff = state.days === "all" ? null : Date.now() - state.days * 86400000;

  const filterByDevice = (name) => !devices || devices.size === 0 || devices.has(name);
  const withinWindow = (isoString) => {
    if (!cutoff) return true;
    return new Date(isoString).getTime() >= cutoff;
  };

  const timeline = {
    lanes: data.timeline.lanes.filter(filterByDevice),
    intervals: data.timeline.intervals.filter(
      (iv) => filterByDevice(iv.device) && withinWindow(iv.end)
    ),
  };

  const onTime = data.on_time.filter((d) => filterByDevice(d.device));

  return {
    ...data,
    timeline,
    on_time: onTime,
    window: {
      days: state.days,
      start: cutoff ? new Date(cutoff).toISOString() : data.window.start,
      end: data.window.end,
    },
  };
}

async function fetchHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error(`status ${res.status}`);
    return await res.json();
  } catch (err) {
    return HEALTH_FALLBACK;
  }
}

/* ----------------------------------------------------------------------
   Rendering — sidebar
---------------------------------------------------------------------- */
function renderDeviceFilter(overview) {
  const list = document.getElementById("device-filter");
  const allDevices = overview.all_devices ?? [];
  const deviceByName = new Map((overview.devices ?? []).map((d) => [d.name, d]));

  if (state.selectedDevices === null) {
    state.selectedDevices = new Set(allDevices);
  }

  list.innerHTML = "";
  allDevices.forEach((name) => {
    const info = deviceByName.get(name);
    const li = document.createElement("li");
    li.className = "device-filter-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selectedDevices.has(name);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selectedDevices.add(name);
      else state.selectedDevices.delete(name);
      refresh();
    });

    const dot = document.createElement("span");
    const stateClass = info?.state === "on" ? "is-on" : info?.state === "off" ? "is-off" : "is-unknown";
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

    li.style.padding = "0";
    li.appendChild(label);
    list.appendChild(li);
  });
}

function wireDeviceToggleAll(overview) {
  const btn = document.getElementById("device-toggle-all");
  btn.addEventListener("click", () => {
    const allDevices = overview.all_devices ?? [];
    const allSelected = state.selectedDevices.size === allDevices.length;
    state.selectedDevices = allSelected ? new Set() : new Set(allDevices);
    renderDeviceFilter(state.overview);
    btn.textContent = allSelected ? "Select all" : "Clear";
    refresh();
  });
}

function renderSystemBlock(health) {
  document.getElementById("sys-source").textContent = health.data_source ?? "unavailable";
  document.getElementById("sys-freshness").textContent = health.freshness_label ?? "—";
  document.getElementById("sys-model").textContent = health.model ? `${health.provider_label ?? health.provider} · ${health.model}` : "—";

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

function updateAgentAvailability(available) {
  const input = document.getElementById("agent-input");
  const sendBtn = document.getElementById("agent-send");
  input.disabled = !available;
  sendBtn.disabled = !available;
  input.placeholder = available ? "Ask the agent…" : "Agent unavailable — see System panel";
}

/* ----------------------------------------------------------------------
   Rendering — topbar / KPIs
---------------------------------------------------------------------- */
function relativeFromNow(isoString) {
  if (!isoString) return "";
  const diffMs = Date.now() - new Date(isoString).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function renderTopbar(overview) {
  const sub = document.getElementById("topbar-updated");
  const sourceLabel = state.usingFixture ? "offline sample data" : (overview.source ?? "warehouse");
  sub.textContent = overview.latest_event
    ? `Latest event ${relativeFromNow(overview.latest_event)} · source: ${sourceLabel}`
    : `Source: ${sourceLabel}`;
}

function renderKPIs(overview) {
  const row = document.getElementById("kpi-row");
  row.innerHTML = "";

  (overview.kpis ?? []).forEach((kpi) => {
    const card = document.createElement("div");
    card.className = "kpi-card";

    const top = document.createElement("div");
    top.className = "kpi-top";

    const label = document.createElement("span");
    label.className = "kpi-label";
    label.textContent = kpi.label;
    top.appendChild(label);

    if (kpi.spark && kpi.spark.length > 1) {
      const sparkHolder = document.createElement("div");
      sparkHolder.className = "kpi-spark";
      top.appendChild(sparkHolder);
      requestAnimationFrame(() => renderSparkline(sparkHolder, kpi.spark));
    }

    const value = document.createElement("div");
    value.className = "kpi-value";
    value.textContent = kpi.value;

    const sub = document.createElement("div");
    sub.className = "kpi-sub";
    sub.textContent = kpi.sub ?? "";

    card.append(top, value, sub);
    row.appendChild(card);
  });
}

/* ----------------------------------------------------------------------
   Rendering — charts
---------------------------------------------------------------------- */
function renderCharts(overview) {
  const timelineEl = document.getElementById("timeline-chart");
  const onTimeEl = document.getElementById("on-time-chart");

  if (overview.empty) {
    timelineEl.innerHTML = `<p class="empty-note">${overview.empty_reason ?? "No data yet."}</p>`;
    onTimeEl.innerHTML = `<p class="empty-note">${overview.empty_reason ?? "No data yet."}</p>`;
    return;
  }

  renderTimeline(timelineEl, overview.timeline, {
    latestEvent: overview.latest_event,
    windowStart: overview.window?.start,
    windowEnd: overview.window?.end,
  });
  renderOnTimeBars(onTimeEl, overview.on_time);
}

const rerenderChartsOnResize = debounce(() => {
  if (state.overview) renderCharts(state.overview);
}, 150);
window.addEventListener("resize", rerenderChartsOnResize);

/* ----------------------------------------------------------------------
   Refresh cycle
---------------------------------------------------------------------- */
async function refresh() {
  const refreshBtn = document.getElementById("refresh-btn");
  refreshBtn.classList.add("is-loading");

  try {
    const overview = await fetchOverview();
    state.overview = overview;

    if (state.selectedDevices === null || state.selectedDevices.size === 0) {
      state.selectedDevices = new Set(overview.all_devices ?? []);
    }

    renderDeviceFilter(overview);
    renderTopbar(overview);
    renderKPIs(overview);
    renderCharts(overview);
  } finally {
    refreshBtn.classList.remove("is-loading");
  }
}

async function refreshHealth() {
  const health = await fetchHealth();
  renderSystemBlock(health);
}

/* ----------------------------------------------------------------------
   Filters — time range
---------------------------------------------------------------------- */
function wireRangeControl() {
  const control = document.getElementById("range-control");
  control.addEventListener("click", (evt) => {
    const btn = evt.target.closest(".segmented-btn");
    if (!btn) return;
    control.querySelectorAll(".segmented-btn").forEach((b) => b.classList.remove("is-active"));
    btn.classList.add("is-active");
    const raw = btn.dataset.days;
    state.days = raw === "all" ? "all" : Number(raw);
    refresh();
  });
}

function wireRefreshButton() {
  document.getElementById("refresh-btn").addEventListener("click", () => {
    refresh();
    refreshHealth();
  });
}

/* ----------------------------------------------------------------------
   Minimal Markdown renderer for assistant replies.

   Security: HTML entities are escaped FIRST, over the raw source string,
   before any Markdown transform runs. Every transform below then only ever
   *wraps* already-escaped text in known-safe tags (<strong>, <code>, etc.)
   — it never re-parses or unescapes the content. That ordering means a
   model/tool output containing literal "<script>" or "<img onerror=...>"
   can never become live markup: by the time any regex sees it, "<" and ">"
   have already become "&lt;"/"&gt;" and cannot form a tag. Escaping AFTER
   the transforms (or interleaving it) would risk a transform re-injecting
   raw "<"/">" from the input, which is exactly what must never happen here.
---------------------------------------------------------------------- */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderInlineMarkdown(escapedText) {
  // Operates on already-escaped text; only wraps it in safe inline tags.
  let html = escapedText;
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>");
  html = html.replace(/(^|[^_\w])_([^_\s][^_]*?)_(?!_)/g, "$1<em>$2</em>");
  return html;
}

/** Renders a small subset of Markdown (bold/italic/code/headings/lists) to
 *  a sanitized HTML string. See escapeHtml()/renderInlineMarkdown() above
 *  for why escaping must happen before any transform. */
function renderMarkdown(source) {
  const escaped = escapeHtml(source ?? "");
  const lines = escaped.split(/\r?\n/);

  const htmlParts = [];
  let listItems = null; // in-progress <ul>/<ol> items
  let listTag = null;
  let paragraphLines = [];

  const flushParagraph = () => {
    if (paragraphLines.length) {
      htmlParts.push(`<p>${renderInlineMarkdown(paragraphLines.join(" "))}</p>`);
      paragraphLines = [];
    }
  };
  const flushList = () => {
    if (listItems && listItems.length) {
      htmlParts.push(`<${listTag}>${listItems.join("")}</${listTag}>`);
    }
    listItems = null;
    listTag = null;
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    const ulItem = line.match(/^[-*]\s+(.*)$/);
    const olItem = line.match(/^\d+\.\s+(.*)$/);

    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length;
      htmlParts.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    if (ulItem) {
      flushParagraph();
      if (listTag !== "ul") { flushList(); listTag = "ul"; listItems = []; }
      listItems.push(`<li>${renderInlineMarkdown(ulItem[1])}</li>`);
      continue;
    }
    if (olItem) {
      flushParagraph();
      if (listTag !== "ol") { flushList(); listTag = "ol"; listItems = []; }
      listItems.push(`<li>${renderInlineMarkdown(olItem[1])}</li>`);
      continue;
    }
    flushList();
    paragraphLines.push(line);
  }
  flushParagraph();
  flushList();

  return htmlParts.join("");
}

/* ----------------------------------------------------------------------
   Agent panel
---------------------------------------------------------------------- */
function wireDryRunSwitch() {
  const btn = document.getElementById("dryrun-switch");
  const stateLabel = document.getElementById("dryrun-state");
  const consequence = document.getElementById("dryrun-consequence");

  btn.addEventListener("click", () => {
    state.dryRun = !state.dryRun;
    const armed = !state.dryRun;
    btn.classList.toggle("is-armed", armed);
    btn.setAttribute("aria-pressed", String(!armed));
    if (armed) {
      stateLabel.textContent = "ARMED — commands will be sent";
      consequence.textContent = "Real commands will be sent to your devices. Tap to make safe.";
    } else {
      stateLabel.textContent = "SAFE — commands are simulated";
      consequence.textContent = "Nothing will be sent to your devices. Tap to arm.";
    }
  });
}

function wireChips() {
  document.getElementById("chip-row").addEventListener("click", (evt) => {
    const chip = evt.target.closest(".chip");
    if (!chip || chip.disabled) return;
    const input = document.getElementById("agent-input");
    input.value = "";
    submitAgentQuery(chip.dataset.prompt);
  });
}

function wireAgentForm() {
  const form = document.getElementById("agent-form");
  form.addEventListener("submit", (evt) => {
    evt.preventDefault();
    const input = document.getElementById("agent-input");
    const q = input.value.trim();
    if (!q) return;
    input.value = "";
    submitAgentQuery(q);
  });
}

/** Disables/enables Send + chips while a turn is streaming, so a second
 *  turn can't be started mid-stream. Does not touch the input's own
 *  enabled state, which reflects agent *availability* (see
 *  updateAgentAvailability). */
function setAgentBusy(busy) {
  const sendBtn = document.getElementById("agent-send");
  sendBtn.disabled = busy;
  document.querySelectorAll("#chip-row .chip").forEach((chip) => {
    chip.disabled = busy;
  });
}

function appendMessage(className, innerNode) {
  const list = document.getElementById("agent-messages");
  const wrap = document.createElement("div");
  wrap.className = `agent-msg ${className}`;
  if (typeof innerNode === "string") {
    const p = document.createElement("p");
    p.textContent = innerNode;
    wrap.appendChild(p);
  } else {
    wrap.appendChild(innerNode);
  }
  list.appendChild(wrap);
  scrollAgentMessagesToBottom();
  return wrap;
}

/** Keeps the agent transcript pinned to the newest content as steps stream
 *  in and the final answer arrives (composer stays fixed via flex layout
 *  in styles.css; only this scroll region moves). */
function scrollAgentMessagesToBottom() {
  const list = document.getElementById("agent-messages");
  list.scrollTop = list.scrollHeight;
}

const TOOL_LABELS = {
  query_iot_data: "Querying the warehouse",
  get_device_state: "Reading device state",
  control_device: "Preparing a device command",
};

function toolLabel(tool) {
  return TOOL_LABELS[tool] ?? tool;
}

function submitAgentQuery(question) {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }

  setAgentBusy(true);
  appendMessage("agent-msg--user", question);

  const stepsWrap = document.createElement("div");
  stepsWrap.className = "agent-steps";
  const assistantBubble = appendMessage("agent-msg--assistant", stepsWrap);
  const pendingSteps = new Map(); // tool name -> step DOM node (single in-flight assumption per contract)

  const params = new URLSearchParams();
  params.set("q", question);
  params.set("dry_run", state.dryRun ? "1" : "0");

  let es;
  try {
    es = new EventSource(`/api/agent/stream?${params.toString()}`);
  } catch (err) {
    renderAgentError(assistantBubble, "Could not reach the agent stream.");
    setAgentBusy(false);
    return;
  }
  state.eventSource = es;

  es.addEventListener("tool_call_start", (evt) => {
    const payload = JSON.parse(evt.data);
    const step = document.createElement("div");
    step.className = "agent-step is-pending";

    const icon = document.createElement("span");
    icon.className = "agent-step-icon";
    const spinner = document.createElement("span");
    spinner.className = "spinner";
    icon.appendChild(spinner);

    const label = document.createElement("span");
    label.className = "agent-step-label";
    label.textContent = toolLabel(payload.tool);

    step.append(icon, label);

    if (payload.input?.sql) {
      const detail = document.createElement("div");
      detail.className = "agent-step-detail";
      const code = document.createElement("code");
      code.className = "sql-block";
      code.textContent = payload.input.sql;
      detail.appendChild(code);
      step.appendChild(detail);
    }

    stepsWrap.appendChild(step);
    pendingSteps.set(payload.tool, step);
    scrollAgentMessagesToBottom();
  });

  es.addEventListener("tool_call_end", (evt) => {
    const payload = JSON.parse(evt.data);
    const step = pendingSteps.get(payload.tool) ?? stepsWrap.lastElementChild;
    if (!step) return;

    step.classList.remove("is-pending");
    step.classList.add(payload.is_error ? "is-error" : "is-done");

    const icon = step.querySelector(".agent-step-icon");
    icon.innerHTML = payload.is_error
      ? '<svg viewBox="0 0 16 16" width="12" height="12"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'
      : '<svg viewBox="0 0 16 16" width="12" height="12"><path d="M3 8.5l3.2 3.2L13 4.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

    const duration = document.createElement("span");
    duration.className = "agent-step-duration";
    duration.textContent = `${payload.duration_ms} ms`;
    step.appendChild(duration);

    renderToolOutput(step, payload);
    scrollAgentMessagesToBottom();
  });

  es.addEventListener("result", (evt) => {
    const payload = JSON.parse(evt.data);
    const replyEl = document.createElement("div");
    replyEl.className = "agent-msg-markdown";
    replyEl.innerHTML = renderMarkdown(payload.reply ?? "(no reply)");
    appendMessage("agent-msg--assistant", replyEl);
    setAgentBusy(false);
    es.close();
    state.eventSource = null;
  });

  es.addEventListener("error", (evt) => {
    // Named SSE "error" events carry a JSON payload per contract; a raw
    // connection failure (no backend yet) fires this with no evt.data.
    let message = "The agent is unavailable right now.";
    if (evt.data) {
      try {
        message = JSON.parse(evt.data).message ?? message;
      } catch (_) {
        /* fall through to default message */
      }
    }
    renderAgentError(assistantBubble, message);
    setAgentBusy(false);
    es.close();
    state.eventSource = null;
  });
}

function renderAgentError(bubble, message) {
  bubble.classList.remove("agent-msg--assistant");
  bubble.classList.add("agent-msg--error");
  const p = document.createElement("p");
  p.textContent = message;
  bubble.appendChild(p);
}

function renderToolOutput(step, payload) {
  let parsed = null;
  if (typeof payload.output === "string") {
    try { parsed = JSON.parse(payload.output); } catch (_) { parsed = null; }
  } else if (payload.output && typeof payload.output === "object") {
    parsed = payload.output;
  }
  if (!parsed) return;

  if (payload.tool === "control_device" && parsed.payload) {
    const wrap = document.createElement("div");
    wrap.className = "control-payload";

    const sent = parsed.dry_run === false;
    const badge = document.createElement("span");
    badge.className = `control-payload-status ${sent ? "sent" : "not-sent"}`;
    badge.textContent = sent ? "SENT to device" : "NOT sent (dry run)";
    wrap.appendChild(badge);

    const code = document.createElement("code");
    code.className = "sql-block";
    code.textContent = JSON.stringify(parsed.payload, null, 2);
    wrap.appendChild(code);

    step.appendChild(wrap);
    return;
  }

  if (Array.isArray(parsed.columns) && Array.isArray(parsed.rows)) {
    const wrap = document.createElement("div");
    wrap.className = "result-table-wrap";
    const table = document.createElement("table");
    table.className = "result-table";

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    parsed.columns.forEach((c) => {
      const th = document.createElement("th");
      th.textContent = c;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    parsed.rows.slice(0, 25).forEach((row) => {
      const tr = document.createElement("tr");
      row.forEach((cell) => {
        const td = document.createElement("td");
        td.textContent = cell === null || cell === undefined ? "—" : String(cell);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    wrap.appendChild(table);
    step.appendChild(wrap);
  }
}

/* ----------------------------------------------------------------------
   Boot
---------------------------------------------------------------------- */
function init() {
  wireRangeControl();
  wireRefreshButton();
  wireDryRunSwitch();
  wireChips();
  wireAgentForm();

  refresh().then(() => wireDeviceToggleAll(state.overview));
  refreshHealth();
}

document.addEventListener("DOMContentLoaded", init);
