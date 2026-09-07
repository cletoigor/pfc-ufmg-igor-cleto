// agent.js — the AI chat panel: the SSE stream, the tool-step timeline and
// the Markdown rendering of the model's reply.
//
// Split out of app.js when the dashboard grew from one page to four. The panel
// is a persistent dock available from every view, so it is wired once at boot
// and never re-rendered by the router — collapsing it only hides it, so a
// stream in flight survives both navigation and closing the panel.

import { state } from "./state.js";

/** Enables or disables the composer according to provider availability. */
export function updateAgentAvailability(available) {
  const input = document.getElementById("agent-input");
  const sendBtn = document.getElementById("agent-send");
  if (!input || !sendBtn) return;
  input.disabled = !available;
  sendBtn.disabled = !available;
  input.placeholder = available ? "Ask the agent\u2026" : "Agent unavailable \u2014 see System panel";
}

export function wireAgentPanel() {
  wireAgentDock();
  wireChips();
  wireAgentForm();
}

/** Opens the dock and puts the caret in the composer. */
export function openAgentDock() {
  setDockOpen(true);
}

function setDockOpen(open) {
  const dock = document.getElementById("agent-dock");
  const panel = document.getElementById("agent");
  const fab = document.getElementById("agent-fab");
  if (!dock || !panel || !fab) return;

  dock.classList.toggle("is-open", open);
  panel.hidden = !open;
  fab.setAttribute("aria-expanded", String(open));
  fab.setAttribute("aria-label", open ? "Hide agent" : "Ask the agent");

  if (open) {
    const input = document.getElementById("agent-input");
    if (input && !input.disabled) input.focus();
    scrollMessagesToEnd();
  }
}

function wireAgentDock() {
  const fab = document.getElementById("agent-fab");
  const closeBtn = document.getElementById("agent-close");
  const dock = document.getElementById("agent-dock");

  fab.addEventListener("click", () => setDockOpen(!dock.classList.contains("is-open")));
  closeBtn.addEventListener("click", () => setDockOpen(false));

  // Escape closes it, the way every other transient overlay behaves.
  document.addEventListener("keydown", (evt) => {
    if (evt.key === "Escape" && dock.classList.contains("is-open")) setDockOpen(false);
  });
}

function scrollMessagesToEnd() {
  const list = document.getElementById("agent-messages");
  if (list) list.scrollTop = list.scrollHeight;
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

  // The provider can take half a minute before its first token, and without
  // this the panel shows an empty bubble the whole time and looks broken.
  // `model_call` fires as soon as the request goes out, so it is the earliest
  // honest signal that something is happening.
  const thinking = document.createElement("div");
  thinking.className = "agent-step is-pending agent-thinking";
  const thinkingIcon = document.createElement("span");
  thinkingIcon.className = "agent-step-icon";
  const thinkingSpinner = document.createElement("span");
  thinkingSpinner.className = "spinner";
  thinkingIcon.appendChild(thinkingSpinner);
  const thinkingLabel = document.createElement("span");
  thinkingLabel.className = "agent-step-label";
  thinkingLabel.textContent = "Thinking\u2026";
  thinking.append(thinkingIcon, thinkingLabel);

  const showThinking = () => {
    // Always last in the list: the model thinks again after each tool returns.
    stepsWrap.appendChild(thinking);
    scrollAgentMessagesToBottom();
  };
  const hideThinking = () => thinking.remove();

  es.addEventListener("model_call", (evt) => {
    const payload = JSON.parse(evt.data);
    thinkingLabel.textContent =
      payload.iteration > 1 ? `Thinking\u2026 (step ${payload.iteration})` : "Thinking\u2026";
    showThinking();
  });

  es.addEventListener("tool_call_start", (evt) => {
    hideThinking();
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
    hideThinking();
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
    hideThinking();
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
