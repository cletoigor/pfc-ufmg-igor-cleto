// ui.js — small DOM builders shared by the page modules.
//
// Deliberately plain: element creation and text, no templating language and no
// innerHTML for anything derived from API data. Values that reach the DOM go in
// through textContent, so a device name or an error message can never become
// markup.

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

export function clear(node) {
  node.innerHTML = "";
  return node;
}

/** A titled card, returning the body element for the caller to fill. */
export function card(title, { subtitle, actions, className = "" } = {}) {
  const wrapper = el("section", `card ${className}`.trim());
  if (title) {
    const head = el("div", "card-head");
    const titles = el("div");
    titles.appendChild(el("h2", "card-title", title));
    if (subtitle) titles.appendChild(el("p", "card-sub", subtitle));
    head.appendChild(titles);
    if (actions) head.appendChild(actions);
    wrapper.appendChild(head);
  }
  const body = el("div", "card-body");
  wrapper.appendChild(body);
  return { wrapper, body };
}

/** One metric tile: a big number with a label and an optional caption. */
export function metric(label, value, sub) {
  const tile = el("div", "metric");
  tile.appendChild(el("span", "metric-label", label));
  tile.appendChild(el("span", "metric-value", value));
  if (sub) tile.appendChild(el("span", "metric-sub", sub));
  return tile;
}

export function metricRow(metrics) {
  const row = el("div", "metric-row");
  metrics.forEach((m) => row.appendChild(metric(m.label, m.value, m.sub)));
  return row;
}

export function emptyState(message, hint) {
  const box = el("div", "empty-state");
  box.appendChild(el("p", "empty-note", message));
  if (hint) box.appendChild(el("p", "empty-hint", hint));
  return box;
}

export function spinnerRow(message = "Loading…") {
  const row = el("div", "loading-row");
  row.appendChild(el("span", "loading-dot"));
  row.appendChild(el("span", null, message));
  return row;
}

/** A simple table from headers and rows of already-formatted strings. */
export function table(headers, rows, { className = "", rowClass } = {}) {
  const wrapper = el("div", "table-wrap");
  const tableEl = el("table", `data-table ${className}`.trim());

  const thead = el("thead");
  const headRow = el("tr");
  headers.forEach((header) => headRow.appendChild(el("th", null, header)));
  thead.appendChild(headRow);

  const tbody = el("tbody");
  rows.forEach((row, index) => {
    const tr = el("tr", rowClass ? rowClass(row, index) : null);
    row.forEach((cell) => tr.appendChild(el("td", null, cell)));
    tbody.appendChild(tr);
  });

  tableEl.append(thead, tbody);
  wrapper.appendChild(tableEl);
  return wrapper;
}

export function formatKwh(value) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  if (Number.isNaN(number)) return "—";
  if (number >= 100) return `${number.toFixed(0)} kWh`;
  if (number >= 1) return `${number.toFixed(2)} kWh`;
  return `${number.toFixed(3)} kWh`;
}

export function formatWatts(value) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  if (Number.isNaN(number)) return "—";
  return `${number.toFixed(number >= 100 ? 0 : 1)} W`;
}

export function formatUnit(value, unit, digits = 1) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  if (Number.isNaN(number)) return "—";
  return `${number.toFixed(digits)} ${unit}`;
}

/** A labelled <select>, wired to a change handler. */
export function select(options, current, onChange, { label, id } = {}) {
  const wrapper = el("label", "field");
  if (label) wrapper.appendChild(el("span", "field-label", label));
  const control = el("select", "field-control");
  if (id) control.id = id;
  options.forEach((option) => {
    const value = typeof option === "string" ? option : option.value;
    const text = typeof option === "string" ? option : option.label;
    const opt = el("option", null, text);
    opt.value = value;
    if (value === current) opt.selected = true;
    control.appendChild(opt);
  });
  control.addEventListener("change", () => onChange(control.value));
  wrapper.appendChild(control);
  return wrapper;
}

/** A slider with a live numeric readout, for the CUSUM k and h parameters. */
export function slider({ label, min, max, step, value, format, onInput, onChange }) {
  const wrapper = el("label", "field field-slider");
  const head = el("span", "field-label");
  head.appendChild(el("span", null, label));
  const readout = el("span", "field-readout", format ? format(value) : String(value));
  head.appendChild(readout);
  wrapper.appendChild(head);

  const input = el("input", "field-range");
  input.type = "range";
  input.min = String(min);
  input.max = String(max);
  input.step = String(step);
  input.value = String(value);
  input.addEventListener("input", () => {
    const next = Number(input.value);
    readout.textContent = format ? format(next) : String(next);
    if (onInput) onInput(next);
  });
  // Refetching on every pixel of a drag would hammer the API; the request goes
  // out when the drag ends.
  input.addEventListener("change", () => onChange(Number(input.value)));
  wrapper.appendChild(input);
  return wrapper;
}
