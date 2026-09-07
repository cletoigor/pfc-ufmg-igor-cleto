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
