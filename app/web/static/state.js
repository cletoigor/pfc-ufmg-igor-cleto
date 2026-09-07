// state.js — the filters every page reads, and the fetch helpers they share.
//
// The sidebar's period and device controls are global by design (the monograph
// puts them there so one selection applies across all pages), so they live in
// one object rather than being duplicated per page. Pages never mutate the
// filters; they read them, and re-render when notified.

export const state = {
  // Period. `preset` drives the UI; the request is described either by a
  // trailing `days` count or by an absolute `start`/`end` pair — "Yesterday"
  // and a custom range cannot be expressed as a trailing window.
  preset: "7d",
  days: 7,
  start: null, // "YYYY-MM-DD"
  end: null,

  selectedDevices: null, // null == all devices (before the first load)
  overview: null,
  latestEvent: null,
  usingFixture: false,

  // The interactive safety gate, shared by the agent panel, the device toggles
  // and "run scene now" so the UI can never be SAFE in one place and ARMED in
  // another. The unattended Dagster scheduler has its own separate gate.
  dryRun: true,
  eventSource: null,

  // Device chosen on the Device Details and Advanced Analysis pages.
  focusDevice: null,
  cusum: { k: 0.5, h: 5 },
};

const listeners = new Set();

/** Registers a callback for "the filters changed, re-render". */
export function onFiltersChanged(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function notifyFiltersChanged() {
  listeners.forEach((fn) => fn());
}

/** Query parameters describing the current period + device selection. */
export function windowParams(extra = {}) {
  const params = new URLSearchParams();
  if (state.start || state.end) {
    if (state.start) params.set("start", state.start);
    if (state.end) params.set("end", state.end);
  } else {
    params.set("days", state.days === "all" ? "all" : String(state.days));
  }

  const devices = state.selectedDevices;
  if (devices && devices.size > 0 && devices.size !== (state.overview?.all_devices ?? []).length) {
    params.set("devices", Array.from(devices).join(","));
  }

  Object.entries(extra).forEach(([key, value]) => {
    if (value !== null && value !== undefined) params.set(key, String(value));
  });
  return params;
}

/** A short human label for the active period, for page subtitles. */
export function periodLabel() {
  if (state.start && state.end && state.start === state.end) return formatDay(state.start);
  if (state.start || state.end) {
    return `${state.start ? formatDay(state.start) : "start"} – ${state.end ? formatDay(state.end) : "latest"}`;
  }
  if (state.days === "all") return "all history";
  if (state.days === 1) return "the latest day";
  return `the last ${state.days} days`;
}

/**
 * Parses a value that may be a bare `YYYY-MM-DD`.
 *
 * `new Date("2026-09-07")` is defined to parse as UTC midnight, which then
 * renders as the *previous* day in any negative-offset timezone — the house is
 * at UTC-3, so every date label came out a day early. A date-only string here
 * means a local calendar day, so it is constructed as one.
 */
function parseLocalDate(value) {
  if (value instanceof Date) return value;
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value));
  if (dateOnly) {
    return new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]));
  }
  return new Date(value);
}

export function formatDay(value) {
  if (!value) return "—";
  const date = parseLocalDate(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short" }).format(date);
}

export function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

/** `YYYY-MM-DD` for a Date, in local time (not UTC — toISOString would shift). */
export function toDateInput(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * GETs JSON, returning `{ ok, data }` instead of throwing.
 *
 * Every page renders an explanation rather than a blank card when a request
 * fails, so a rejected promise would just be converted back into this shape at
 * each call site.
 */
export async function getJSON(url) {
  try {
    const res = await fetch(url);
    const data = await res.json().catch(() => null);
    if (!res.ok && !data) return { ok: false, data: null, status: res.status };
    return { ok: res.ok, data, status: res.status };
  } catch (err) {
    return { ok: false, data: null, status: 0, error: String(err) };
  }
}

export async function postJSON(url, body) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
    const data = await res.json().catch(() => null);
    return { ok: res.ok, data, status: res.status };
  } catch (err) {
    return { ok: false, data: null, status: 0, error: String(err) };
  }
}

export async function deleteJSON(url) {
  try {
    const res = await fetch(url, { method: "DELETE" });
    const data = await res.json().catch(() => null);
    return { ok: res.ok, data, status: res.status };
  } catch (err) {
    return { ok: false, data: null, status: 0, error: String(err) };
  }
}

/** The devices currently selected, or every known device when none are. */
export function activeDevices() {
  const all = state.overview?.all_devices ?? [];
  if (!state.selectedDevices || state.selectedDevices.size === 0) return all;
  return all.filter((name) => state.selectedDevices.has(name));
}
