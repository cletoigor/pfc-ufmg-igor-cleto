# API contract (frozen)

The JSON shapes below are the integration boundary between `app/api/` and
`app/web/`. Both sides are built against this document; neither side may change
a field name without changing it here first.

All timestamps are **local wall-clock ISO-8601 strings without a timezone
suffix** (e.g. `"2026-09-06T22:51:24"`), matching the gold layer's timezone
contract (staging is UTC, gold is local — see `app/assets/marts.py`).

Source tables (already materialized in `app/data/warehouse.duckdb`):

- `device_state_intervals(device_id, device_name, switch_code, interval_start, interval_end, duration_minutes, is_on)`
- `device_on_time_daily(device_id, device_name, event_day, on_minutes, on_sessions, longest_session_minutes, overnight_on_minutes)`
- `device_metrics_daily(device_id, device_name, event_day, event_count, last_seen_at, on_event_count)`
- `device_metrics_hourly(...)` — same columns as daily, bucketed by `event_hour`

Energy tables (from `gold_energy_metrics`, `app/assets/energy_marts.py`):

- `device_power_hourly(device_id, device_name, event_hour, sample_count, power_w_{mean,max,min}, voltage_v_{mean,max,min}, current_ma_{mean,max,min}, energy_kwh)`
- `device_power_daily(...)` — the same rolled up per `event_day`, plus `peak_hour`
- `device_cusum_baseline(device_id, device_name, hour_of_day, mu0, sigma0, n_obs)`

---

## `GET /api/overview?days=<int|all>&devices=<comma-separated names>`

Both query params are optional. `days` defaults to `7`; `devices` defaults to
all devices. Filtering applies to `timeline`, `on_time` and the KPI sparklines,
but **not** to `all_devices` (the filter control needs the full list).

```json
{
  "source": "warehouse",
  "latest_event": "2026-09-06T22:51:24",
  "window": { "days": 7, "start": "2026-08-30T22:51:24", "end": "2026-09-06T22:51:24" },
  "all_devices": ["Bedroom Fan", "LED Strip", "Living Room Switch",
                  "Mosquito Repellent", "Office Lamp", "Office Outlet"],
  "kpis": [
    { "key": "devices_reporting", "label": "Devices reporting",
      "value": "6 / 6", "sub": "in the last 24h", "spark": null },
    { "key": "events", "label": "Events ingested",
      "value": "471", "sub": "last 30 days", "spark": [12, 18, 9, 14, 20] },
    { "key": "on_time", "label": "Total on-time, last day",
      "value": "28 h 33 m", "sub": "across all devices", "spark": [1520, 1710, 1655] },
    { "key": "latest_event", "label": "Latest event",
      "value": "06 Sep, 22:51", "sub": "4m ago", "spark": null }
  ],
  "timeline": {
    "lanes": ["Bedroom Fan", "LED Strip", "Living Room Switch",
              "Mosquito Repellent", "Office Lamp", "Office Outlet"],
    "intervals": [
      { "device": "LED Strip",
        "start": "2026-09-06T19:18:36", "end": "2026-09-06T22:50:54",
        "duration_minutes": 212.3, "duration_label": "3 h 32 m" }
    ]
  },
  "on_time": [
    { "device": "Mosquito Repellent", "minutes": 5423.0,
      "hours": 90.4, "label": "90 h 25 m" }
  ],
  "devices": [
    { "device_id": "ebb50554f386a6d20fvbwv", "name": "LED Strip",
      "state": "on",
      "last_seen": "2026-09-06T21:20:09",
      "last_seen_label": "1h ago",
      "detail": "ON for 3 h 32 m" }
  ],
  "empty": false,
  "empty_reason": null
}
```

Rules:

- `on_time` is sorted **descending** by `minutes`.
- `devices` is in `device_mapping.json` order, one entry per mapped device, even
  when a device has no data (`state: "unknown"`, `last_seen: null`).
- `state` is one of `"on" | "off" | "unknown"`.
- **`last_seen` MUST come from `max(device_metrics_daily.last_seen_at)` per
  device**, never from `device_state_intervals.interval_end`. The final interval
  of every device is clipped to the same global `max(event_time)`, so using it
  makes all six devices report the identical timestamp. This is a fixed bug;
  there is a regression test for it.
- When no data layer is available at all: `empty: true`, `empty_reason` a short
  human sentence, `source: null`, and every list empty. The endpoint must still
  return HTTP 200 — never a 500.

## `GET /api/health`

```json
{
  "data_source": "warehouse",
  "latest_event": "2026-09-06T22:51:24",
  "freshness_label": "4m ago",
  "provider": "gemini",
  "provider_label": "Gemini",
  "model": "gemini-3.8-flash",
  "available": true,
  "guidance": null
}
```

`guidance` is `null` when `available` is true; otherwise the provider-specific
setup sentence (the strings already used in `app/dashboard/dashboard.py`).
`model` is `GeminiProvider.active_model` when the provider is Gemini, else the
provider's configured model. This endpoint must never raise —
`provider.is_available()` is already contractually non-raising.

## `GET /api/agent/stream?q=<question>&dry_run=<1|0>`

`text/event-stream`. Each message is a named SSE event with a JSON `data` line:

```
event: model_call
data: {"iteration": 1}

event: tool_call_start
data: {"tool": "query_iot_data", "label": "Querying the warehouse",
       "input": {"sql": "SELECT ..."}}

event: tool_call_end
data: {"tool": "query_iot_data", "duration_ms": 18, "is_error": false,
       "output": "{\"source\":\"warehouse\",\"columns\":[...],\"rows\":[...]}"}

event: result
data: {"reply": "The Mosquito Repellent ...", "tool_trace": [ ... ]}
```

- `model_call`, `tool_call_start` and `tool_call_end` are forwarded straight
  from `run_agent`'s `on_event` callback (`app/agent/agent.py`). The `done`
  event from that callback is **not** forwarded — `result` supersedes it.
- `label` is a human phrase for the tool: `query_iot_data` → "Querying the
  warehouse", `get_device_state` → "Reading device state", `control_device` →
  "Preparing a device command"; unknown tools fall back to the tool name.
- `tool_trace` in `result` is `run_agent`'s trace verbatim (each entry has
  `tool`, `input`, `output`, `duration_ms`, `is_error`).
- On any exception the stream ends with an `error` event and **HTTP 200** — the
  response has already begun, and a half-written 500 is worse than a clean
  error message:

```
event: error
data: {"message": "The model provider is overloaded right now ..."}
```

  The message comes from the shared `friendly_agent_error()` helper.
- Events must be flushed **as they happen**, not buffered until the turn ends.
  `run_agent` is synchronous and blocking, so it runs in a worker thread and its
  callback pushes onto an `asyncio.Queue` via `loop.call_soon_threadsafe`.

---

# Energy, analysis and actuation

Everything below was added to bring the app to parity with chapter 4 of the
monograph. The conventions above still hold: local wall-clock ISO timestamps
with no timezone suffix, **HTTP 200 with an `empty: true` body** when a data
layer is missing rather than a 500, and no endpoint may raise.

The empty shape shared by every route in this section:

```json
{ "empty": true, "empty_reason": "No energy data yet. Run scripts/...", "source": null }
```

`source` is `"warehouse"`, `"marts"`, `"staging (computed on the fly)"` or
`null`, exactly as in `/api/overview`.

Shared query parameters:

- `days=<int|all>` — trailing window (default `7`; `all` means no window).
- `start=YYYY-MM-DD&end=YYYY-MM-DD` — an absolute range, both bounds inclusive
  whole local days. Either may be given alone. When present, it **overrides**
  `days`, because "Yesterday" and a custom range cannot be expressed as a
  trailing window. A malformed date is ignored and the route falls back to
  `days` rather than returning an error — a dashboard is better served by a
  window than by an error card.
- `devices=<comma-separated friendly names>` (default all devices).

Every payload in this section echoes what it actually used:
`"window": { "days": 7|null, "start": null|"...", "end": null|"...", ... }`.

## `GET /api/house/summary?days=&devices=`

```json
{
  "empty": false, "source": "warehouse", "latest_day": "2026-09-07T00:00:00",
  "window": { "days": 7, "start": null, "end": null, "devices": null },
  "totals": [ { "key": "today", "days": 1, "energy_kwh": 0.769 },
              { "key": "last_7_days", "days": 7, "energy_kwh": 13.018 },
              { "key": "this_month", "days": 30, "energy_kwh": 55.257 } ],
  "total_kwh": 13.018,
  "top_consumers": [ { "device": "Office Outlet", "energy_kwh": 8.029, "share": 0.6168 } ],
  "daily_energy": [ { "day": "2026-09-01T00:00:00", "energy_kwh": 2.041 } ],
  "hourly_profile": [ { "hour": 0, "power_w": null, "energy_kwh": 0.0 } ]
}
```

Rules:
- `totals` always has exactly the three keys above, in that order, and is **not**
  narrowed by `days` — those tiles are the fixed reference periods of the
  monograph's "Resumo da Casa" and answer a different question from the window.
- `top_consumers` is at most 5 entries, sorted by `energy_kwh` descending.
  `share` is the fraction of the window's total, so a bar chart has a denominator.
- `hourly_profile` always has 24 entries, hours `0..23`. An hour the house never
  drew in has `power_w: null` — nulls are a gap in the line, not zero.
- "Today" means the most recent day **present in the data**, not the wall-clock
  date; this is a fixed historical dataset (see `latest_day`).

## `GET /api/device/{device}/summary?days=`

`{device}` is the friendly name (URL-encoded). Returns **404** — still with the
`empty` shape, plus a `known` list — when the name is not in
`device_mapping.json`. A known device that simply has no readings returns 200
with `empty: true` and no `known` key.

```json
{
  "empty": false, "source": "warehouse", "device": "Office Outlet",
  "window": { "days": 7, "start": null, "end": null, "latest_day": "2026-09-07T00:00:00" },
  "totals": [ ...same three keys as the house summary... ],
  "power": { "mean_w": 162.2, "max_w": 176.2, "min_w": 144.9, "energy_kwh": 8.029 },
  "power_series":  [ { "time": "2026-09-07T09:00:00", "power_w": 168.4 } ],
  "daily_energy":  [ { "day": "2026-09-07T00:00:00", "energy_kwh": 1.42 } ],
  "hourly_profile":[ { "hour": 9, "power_w": 168.4, "energy_kwh": 0.168 } ],
  "voltage": { "unit": "V", "mean": 127.1, "max": 131.9, "min": 122.6,
               "series": [ { "time": "...", "value": 127.2 } ],
               "distribution": { "count": 54, "min": 125.4, "q1": 126.61,
                                 "median": 127.09, "q3": 127.68, "max": 129.0,
                                 "whisker_low": 125.4, "whisker_high": 129.0,
                                 "mean": 127.1, "outliers": [] } },
  "current": { "unit": "mA", ...same shape as voltage... }
}
```

Rules:
- Series are ordered by time ascending and are hourly means, not raw samples —
  the gold layer does not keep raw readings.
- `distribution` is a five-number summary plus Tukey fences, computed
  server-side; `whisker_low`/`whisker_high` are the extreme values *inside*
  1.5 IQR, and `outliers` is capped at 60 values (extremes kept). It is `null`
  when there is nothing to summarise.

## `GET /api/analysis/cusum?device=&k=&h=&days=`

Phase II of the multichannel CUSUM scheme (monograph §3.3.2). `k` defaults to
`0.5`, `h` to `5`, `days` to `all`. **400** if `device` is missing, if `k < 0`,
or if `h <= 0`.

```json
{
  "empty": false, "device": "Office Outlet", "k": 0.5, "h": 5.0,
  "monitored_variable": "energy_kwh",
  "monitored_count": 244, "skipped_count": 0,
  "points": [ { "time": "2026-09-03T09:00:00", "hour": 9, "value": 0.1698,
                "mu0": 0.1423, "s_hi": 0.0687, "s_lo": 0.0,
                "limit": 0.0589, "signal": true, "monitored": true } ],
  "faults": [ { "time": "2026-09-03T09:00:00", "hour": 9, "direction": "high",
                "value": 0.1698, "expected": 0.1423, "cusum": 0.0687,
                "limit": 0.0589, "excess": 0.0098 } ],
  "baseline": [ { "hour": 9, "mu0": 0.1423, "sigma0": 0.01177, "n_obs": 15 } ]
}
```

Rules:
- `points` aligns one-to-one with the device's hourly observations, in time order.
- `limit` is **per point**, not global: H = h·sigma0 and sigma0 varies by channel,
  so the decision limit is a step function, not a straight line. Draw it as one.
- `monitored: false` marks an observation whose hour has no usable baseline
  (fewer than 3 historical observations, or zero spread). Its sums are carried
  through unchanged and it can never raise a signal.
- Each hour-of-day accumulates its own pair of sums; a signal resets the
  offending sum to zero. `faults` is therefore a list of distinct crossings.

## `GET /api/analysis/profiles?devices=&days=`

```json
{
  "empty": false,
  "daily_profiles": [ { "weekday": 0, "label": "Monday",
                        "points": [ { "hour": 0, "power_w": null } ] } ],
  "weekly": { "historical_mean": [ { "hour_of_week": 0, "power_w": 12.4 } ],
              "weeks": [ { "week_start": "2026-08-31T00:00:00",
                           "points": [ { "hour_of_week": 0, "power_w": 11.8 } ] } ] }
}
```

Rules:
- `daily_profiles` always has 7 entries, `weekday` 0 (Monday) to 6, each with 24
  hourly points.
- `historical_mean` and each week have 168 points, `hour_of_week = weekday*24 + hour`.
- `weeks` holds at most the last 4 weeks, oldest first.
- Figure 4.18 of the monograph shows this as a 3D surface. It is delivered here
  as a 2D overlay — recent weeks against a bold historical mean — deliberately:
  the frontend has no charting library and a hand-projected 3D plot the reader
  cannot rotate would carry less information, not more.

## `GET /api/analysis/peaks?devices=&days=&limit=`

`limit` defaults to 10 and is clamped to 1..100.

```json
{ "empty": false,
  "peaks": [ { "device": "Office Outlet", "time": "2026-09-03T14:00:00",
               "peak_w": 176.2, "mean_w": 168.0, "energy_kwh": 0.168 } ] }
```

Sorted by `peak_w` descending. A "peak" is the highest hourly maximum, since
the gold layer's finest granularity is the hour.

## Actuation

These endpoints can affect physical devices, so the gate is explicit.

**`dry_run` defaults to `true` and only a literal JSON `false` opens it.** The
strings `"false"`, `0` and `null` all leave it closed — a mistyped flag must
fail safe. This mirrors `control_device` in `app/agent/tools.py`, where the
caller's `dry_run` always overrides whatever the model asked for.

Scheduled execution has a **separate** gate: the environment variable
`SCENE_EXECUTION_DRY_RUN` (default `1`), read by the Dagster scheduler. Arming
the dashboard does not arm the unattended job, and vice versa.

### `GET /api/scenes` → `{ "scenes": [ ... ] }`

A stored scene:

```json
{ "id": "56e09f73ff2f4694807005962783c2c7", "name": "Evening wind-down",
  "actions": { "LED Strip": "off", "Living Room Switch": "off" },
  "devices": ["LED Strip", "Living Room Switch"],
  "schedule": { "time": "22:30", "days_of_week": [0,1,2,3,4], "recurring": true },
  "enabled": true, "created_at": "2026-09-07T11:40:00",
  "last_executed_at": null, "executed": false }
```

`days_of_week` is 0 = Monday .. 6 = Sunday (`date.weekday()`). `time` is `HH:mm`
24-hour, or `null` for a manual-only scene.

### `POST /api/scenes`

Body is `{name, actions, schedule?, enabled?}`. **201** with the stored scene,
or **400** with `{"error": "..."}` for: an empty name, no actions, an unknown
action, a device not in `device_mapping.json`, a malformed `time`, a day outside
0..6, or a scheduled scene with no days.

### `DELETE /api/scenes/{id}` → 200 `{"deleted": true}`, or 404.

### `POST /api/scenes/{id}/run`

Body `{"dry_run": bool}`. 404 for an unknown id. Response:

```json
{ "scene_id": "...", "scene": "Evening wind-down", "dry_run": true, "ok": true,
  "results": [ { "device": "LED Strip", "action": "off", "ok": true,
                 "dry_run": true,
                 "payload": { "commands": [ { "code": "switch_led", "value": false } ] },
                 "error": null } ] }
```

One device failing does not abort the others; `ok` is the conjunction.

### `POST /api/devices/{device}/toggle`

Body `{"action": "on"|"off", "dry_run": bool}`. **400** for any other action,
**404** for an unknown device. Response mirrors one `results` entry above, plus
`device` and `action`. This route does **not** go through the agent — a toggle
should not cost a model call or require a configured LLM provider.
