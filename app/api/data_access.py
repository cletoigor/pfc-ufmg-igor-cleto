"""
Data access + formatting for the web UI backend (`app.api.server`) and the
Streamlit dashboard (`app.dashboard.dashboard`).

Framework-free by design: no `streamlit` import anywhere in this module, so
`app.api.server` (a plain Starlette app) can use it without pulling in
Streamlit, and the dashboard can keep using it under its own
`@st.cache_data`/`@st.cache_resource` wrappers.

Two "reference now" values matter here, and they are deliberately different:
  - `latest_event` (the newest timestamp anywhere in the dataset) is the
    reference for anything that describes a device's activity *relative to
    the rest of the dataset* — the per-device `last_seen_label` in
    `build_overview`, and the window start/end. This is a fixed historical
    demo dataset, so comparing against wall-clock `datetime.now()` here would
    make every device say "31 days ago" and destroy the signal of which
    devices were active around the same time as the most recent event.
  - real wall-clock `datetime.now()` is the reference for anything that
    answers "is the pipeline stale *right now*" — the `latest_event` KPI's
    `sub` in `build_overview`, and `freshness_label` in `build_health`. That
    is a genuinely different question ("has this stopped ingesting") and
    conflating it with the dataset-relative reference above would make a
    health check useless.
"""
import glob
import json
import os
from datetime import datetime

import duckdb
import pandas as pd

# ---------------------------------------------------------------------------
# Paths (mirrors the layout/fallback logic in app/agent/tools.py, kept
# independent here — this module has no import-time dependency on the agent
# or on Streamlit).
# ---------------------------------------------------------------------------
_API_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_API_DIR)

WAREHOUSE_DB_PATH = os.path.join(_APP_DIR, "data", "warehouse.duckdb")
DEVICE_MAPPING_PATH = os.path.join(_APP_DIR, "device_mapping.json")
STAGING_GLOB = os.path.join(_APP_DIR, "data", "staging", "**", "*.parquet")

# One glob per mart — the four marts have different schemas, so they can never
# share a single `marts/**` glob.
_MARTS_DIR = os.path.join(_APP_DIR, "data", "marts")
MART_GLOBS = {
    "hourly": os.path.join(_MARTS_DIR, "hourly", "**", "*.parquet"),
    "daily": os.path.join(_MARTS_DIR, "daily", "**", "*.parquet"),
    "intervals": os.path.join(_MARTS_DIR, "state_intervals", "**", "*.parquet"),
    "on_time": os.path.join(_MARTS_DIR, "on_time_daily", "**", "*.parquet"),
    "power_hourly": os.path.join(_MARTS_DIR, "power_hourly", "**", "*.parquet"),
    "power_daily": os.path.join(_MARTS_DIR, "power_daily", "**", "*.parquet"),
    # The baseline has no time axis to partition on, so it is a single file.
    "baseline": os.path.join(_MARTS_DIR, "cusum_baseline", "*.parquet"),
}
_MART_TABLES = {
    "hourly": "device_metrics_hourly",
    "daily": "device_metrics_daily",
    "intervals": "device_state_intervals",
    "on_time": "device_on_time_daily",
    "power_hourly": "device_power_hourly",
    "power_daily": "device_power_daily",
    "baseline": "device_cusum_baseline",
}


def load_device_mapping() -> dict:
    """device_id -> friendly name, loaded from app/device_mapping.json."""
    try:
        with open(DEVICE_MAPPING_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_metrics() -> dict:
    """Loads the gold tables, trying each storage layer in order.

    Returns {"source": "warehouse"|"marts"|"staging (computed on the fly)"|None,
             "hourly"/"daily"/"intervals"/"on_time": DataFrame|None,
             "error": str|None}.
    Never raises — a missing/partial data layer degrades gracefully to the
    next fallback, and if nothing is available at all, source is None so the
    caller can render the empty-state card.
    """
    empty = {key: None for key in MART_GLOBS}

    # 1) Persistent warehouse (read-only — never contends with Dagster's writer).
    if os.path.exists(WAREHOUSE_DB_PATH):
        try:
            conn = duckdb.connect(WAREHOUSE_DB_PATH, read_only=True)
            try:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT table_name FROM information_schema.tables"
                    ).fetchall()
                }
                if tables & set(_MART_TABLES.values()):
                    frames = dict(empty)
                    for key, table in _MART_TABLES.items():
                        if table in tables:
                            frames[key] = conn.execute(f"SELECT * FROM {table}").df()
                    return {"source": "warehouse", "error": None, **frames}
            finally:
                conn.close()
        except duckdb.Error:
            pass  # fall through to the Parquet fallbacks below

    # 2) Gold marts Parquet, one view per mart.
    available = {
        key: pattern
        for key, pattern in MART_GLOBS.items()
        if glob.glob(pattern, recursive=True)
    }
    if available:
        try:
            conn = duckdb.connect(database=":memory:")
            try:
                frames = dict(empty)
                for key, pattern in available.items():
                    frames[key] = conn.execute(
                        f"SELECT * FROM read_parquet('{pattern}', hive_partitioning=1)"
                    ).df()
                return {"source": "marts", "error": None, **frames}
            finally:
                conn.close()
        except duckdb.Error:
            pass

    # 3) Raw staging Parquet — no rollups exist yet, so compute the hourly
    #    rollup on the fly. The duration tables are deliberately not
    #    reconstructed here: that is the mart's job, and a half-built version
    #    of it in the dashboard would be a second definition to keep in sync.
    if glob.glob(STAGING_GLOB, recursive=True):
        try:
            conn = duckdb.connect(database=":memory:")
            try:
                hourly = conn.execute(
                    f"""
                    SELECT
                        device_id,
                        device_name,
                        date_trunc('hour', event_time) AS event_hour,
                        count(*) AS event_count,
                        max(event_time) AS last_seen_at,
                        count(*) FILTER (
                            WHERE code ILIKE 'switch%' AND CAST(value AS VARCHAR) ILIKE 'true'
                        ) AS on_event_count
                    FROM read_parquet('{STAGING_GLOB}', hive_partitioning=1)
                    GROUP BY device_id, device_name, event_hour
                    ORDER BY event_hour
                    """
                ).df()
                return {
                    "source": "staging (computed on the fly)",
                    "error": None,
                    **{**empty, "hourly": hourly},
                }
            finally:
                conn.close()
        except duckdb.Error as e:
            return {"source": None, "error": str(e), **empty}

    return {"source": None, "error": None, **empty}


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------
def humanize_minutes(minutes) -> str:
    """45 m / 3 h 20 m / 3 d 13 h / — for a duration in minutes.

    The unit follows the magnitude, because the same field is read over
    windows from one day to the whole history: "85 h 10 m" for a month of
    on-time makes the reader divide by 24 in their head, and the trailing
    minutes are noise at that scale. Once a duration reaches a day it is
    reported in days and hours, and the minutes are dropped.
    """
    if minutes is None or pd.isna(minutes):
        return "—"
    minutes = int(round(float(minutes)))
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    if days:
        return f"{days} d {hours} h" if hours else f"{days} d"
    if hours and mins:
        return f"{hours} h {mins} m"
    if hours:
        return f"{hours} h"
    return f"{mins} m"


def relative_time(when, *, now=None) -> str:
    """"3h ago" / "just now". Measured against the newest event in the dataset
    rather than wall-clock, since the demo data is a fixed historical window and
    "31 days ago" on every tile would say nothing useful."""
    if when is None or pd.isna(when):
        return "no events"
    now = now if now is not None else datetime.now()
    delta = pd.Timestamp(now) - pd.Timestamp(when)
    seconds = delta.total_seconds()
    if seconds < 0:
        return "just now"
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def friendly_agent_error(exc: Exception) -> str:
    """Turns a provider exception into something readable in the chat panel.

    The charts never depend on the LLM, so a provider outage is a degraded
    panel rather than a broken page — and a raw traceback in the transcript is
    the worst possible way to say so.
    """
    text = str(exc)
    lowered = text.lower()
    if "unavailable" in lowered or "503" in text or "high demand" in lowered:
        return (
            "The model provider is overloaded right now and every fallback "
            "model was busy too. This is a capacity problem on their side, not "
            "a problem with the query — try again in a moment. The dashboard on "
            "the left is unaffected."
        )
    if "429" in text or "quota" in lowered or "rate limit" in lowered:
        return (
            "The provider's free-tier rate limit has been reached. Wait a "
            "minute and try again, or set `GEMINI_MODEL` to a different model."
        )
    if "api key" in lowered or "401" in text or "403" in text:
        return (
            "The provider rejected the API key. Check `GEMINI_API_KEY` in "
            "`app/.env`."
        )
    return f"The agent hit an error and couldn't complete this turn: {exc}"


def _iso(ts) -> str | None:
    """`pd.Timestamp`/`datetime`/None -> local wall-clock ISO-8601 string with
    no timezone suffix and no sub-second component (the api_contract.md
    shape), or None."""
    if ts is None or pd.isna(ts):
        return None
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


def _empty_overview(days, device_mapping: dict, reason: str) -> dict:
    """The `empty: true` payload shape — still HTTP-200-shaped, every list
    empty, `devices` still lists every mapped device (as "unknown")."""
    return {
        "source": None,
        "latest_event": None,
        "window": {"days": days, "start": None, "end": None},
        "all_devices": sorted(device_mapping.values()),
        "kpis": [
            {"key": "devices_reporting", "label": "Devices reporting",
             "value": f"0 / {len(device_mapping) or '—'}", "sub": "in the last 24h", "spark": None},
            {"key": "events", "label": "Events ingested",
             "value": "—", "sub": "last 30 days", "spark": None},
            {"key": "on_time", "label": "Total on-time, last day",
             "value": "—", "sub": "across all devices", "spark": None},
            {"key": "latest_event", "label": "Latest event",
             "value": "—", "sub": "no events", "spark": None},
        ],
        "timeline": {"lanes": [], "intervals": []},
        "on_time": [],
        "devices": [
            {"device_id": device_id, "name": name, "state": "unknown",
             "last_seen": None, "last_seen_label": "no events", "detail": None}
            for device_id, name in device_mapping.items()
        ],
        "empty": True,
        "empty_reason": reason,
    }


def build_overview(days=7, devices=None, start=None, end=None) -> dict:
    """Builds the `/api/overview` payload (see docs/api_contract.md).

    Args:
        days: window size in days, or None for all history.
        start, end: an explicit inclusive date range, which overrides `days`
            when given. "Yesterday" and a custom range cannot be expressed as a
            trailing window, and the sidebar's period control drives every page,
            so this endpoint accepts the same bounds the energy routes do.
        devices: optional iterable of friendly device names to filter
            `timeline`, `on_time` and the KPI sparklines by. `all_devices`
            and the `devices` status list are never filtered by this — the
            filter control itself needs the full list.
    """
    device_mapping = load_device_mapping()
    devices_filter = set(devices) if devices else None

    metrics = load_metrics()
    source = metrics["source"]

    intervals_df = metrics.get("intervals")
    on_time_df = metrics.get("on_time")
    daily_df = metrics.get("daily")
    hourly_df = metrics.get("hourly")

    has_durations = intervals_df is not None and not intervals_df.empty

    # `latest_event`: max across BOTH device_metrics_daily.last_seen_at and
    # device_state_intervals.interval_end — daily's last_seen_at can be later
    # than the (clipped) interval_end for some devices, so taking either alone
    # can understate the true newest event in the dataset.
    candidates = []
    if daily_df is not None and not daily_df.empty and "last_seen_at" in daily_df.columns:
        candidates.append(pd.Timestamp(daily_df["last_seen_at"].max()))
    if has_durations:
        candidates.append(pd.Timestamp(intervals_df["interval_end"].max()))
    if not candidates and hourly_df is not None and not hourly_df.empty and "last_seen_at" in hourly_df.columns:
        candidates.append(pd.Timestamp(hourly_df["last_seen_at"].max()))
    latest_event = max(candidates) if candidates else None

    if source is None or latest_event is None:
        return _empty_overview(
            days, device_mapping,
            metrics.get("error") or "No data has been ingested yet.",
        )

    # --- window ---
    # An explicit range wins over the trailing one. `window_end` is exclusive
    # and sits at the end of `end`'s day, so a single-date range covers that
    # whole day rather than only midnight.
    if start is not None or end is not None:
        window_start = pd.Timestamp(start).normalize() if start is not None else None
        window_end = (
            pd.Timestamp(end).normalize() + pd.Timedelta(days=1) if end is not None else None
        )
    else:
        window_start = latest_event - pd.Timedelta(days=days) if days else None
        window_end = None

    window = {
        "days": None if (start is not None or end is not None) else days,
        "start": _iso(window_start) if window_start is not None else None,
        "end": _iso(
            min(latest_event, window_end - pd.Timedelta(seconds=1))
            if window_end is not None
            else latest_event
        ),
    }

    # --- all_devices (never filtered by `devices` or `days`) ---
    known_devices = sorted(
        set(device_mapping.values())
        | (set(intervals_df["device_name"].dropna()) if has_durations else set())
    )

    # --- timeline (windowed + device-filtered) ---
    lanes = [d for d in known_devices if devices_filter is None or d in devices_filter]
    timeline_intervals = []
    if has_durations:
        on_intervals = intervals_df[intervals_df["is_on"]].copy()
        if devices_filter is not None:
            on_intervals = on_intervals[on_intervals["device_name"].isin(devices_filter)]
        if window_start is not None:
            on_intervals = on_intervals[on_intervals["interval_end"] >= window_start]
            on_intervals["interval_start"] = on_intervals["interval_start"].clip(lower=window_start)
        if window_end is not None:
            on_intervals = on_intervals[on_intervals["interval_start"] < window_end]
            on_intervals["interval_end"] = on_intervals["interval_end"].clip(upper=window_end)
        for _, row in on_intervals.sort_values("interval_start").iterrows():
            timeline_intervals.append({
                "device": row["device_name"],
                "start": _iso(row["interval_start"]),
                "end": _iso(row["interval_end"]),
                "duration_minutes": round(float(row["duration_minutes"]), 1),
                "duration_label": humanize_minutes(row["duration_minutes"]),
            })

    # --- on_time (windowed + device-filtered, sorted desc by minutes) ---
    on_time_entries = []
    if on_time_df is not None and not on_time_df.empty:
        windowed = on_time_df
        if devices_filter is not None:
            windowed = windowed[windowed["device_name"].isin(devices_filter)]
        if window_start is not None:
            windowed = windowed[windowed["event_day"] >= window_start.normalize()]
        if window_end is not None:
            windowed = windowed[windowed["event_day"] < window_end]
        if not windowed.empty:
            totals = (
                windowed.groupby("device_name", as_index=False)["on_minutes"]
                .sum()
                .sort_values("on_minutes", ascending=False)
            )
            for _, row in totals.iterrows():
                minutes = float(row["on_minutes"])
                on_time_entries.append({
                    "device": row["device_name"],
                    "minutes": round(minutes, 1),
                    "hours": round(minutes / 60, 1),
                    # Bug fix: a preformatted label so the chart layer can
                    # reserve width for the longest one up front, instead of
                    # clipping it (the old Plotly bar chart clipped
                    # "90 h 25 m" down to "90 h 3").
                    "label": humanize_minutes(minutes),
                })

    # --- devices status list (mapping order, never filtered) ---
    # Bug fix: last_seen MUST come from max(device_metrics_daily.last_seen_at)
    # per device, not from device_state_intervals.interval_end — the final
    # interval of every device is clipped to the same global max(event_time),
    # so using it makes every device report an identical timestamp.
    last_seen_by_device = {}
    if daily_df is not None and not daily_df.empty and "last_seen_at" in daily_df.columns:
        last_seen_by_device = daily_df.groupby("device_id")["last_seen_at"].max().to_dict()
    elif hourly_df is not None and not hourly_df.empty and "last_seen_at" in hourly_df.columns:
        # Only reached when the daily rollup itself isn't available (e.g. the
        # on-the-fly staging fallback, which only computes hourly).
        last_seen_by_device = hourly_df.groupby("device_id")["last_seen_at"].max().to_dict()

    current_state = {}
    if has_durations:
        newest = intervals_df.sort_values("interval_end").groupby("device_id").tail(1)
        current_state = {
            row["device_id"]: (bool(row["is_on"]), row["duration_minutes"])
            for _, row in newest.iterrows()
        }

    device_entries = []
    for device_id, name in device_mapping.items():
        is_on, duration = current_state.get(device_id, (None, None))
        last_seen = last_seen_by_device.get(device_id)
        if is_on is None:
            state, detail = "unknown", None
        else:
            state = "on" if is_on else "off"
            # The device holding the newest event in the dataset has a
            # zero-length trailing interval (it has not had time to accumulate
            # any), so "ON for 0 m" is the literal truth but reads as a bug.
            if duration is not None and duration < 1:
                detail = "just switched on" if is_on else "just switched off"
            else:
                detail = f"{state.upper()} for {humanize_minutes(duration)}"
        device_entries.append({
            "device_id": device_id,
            "name": name,
            "state": state,
            "last_seen": _iso(last_seen),
            "last_seen_label": relative_time(last_seen, now=latest_event),
            "detail": detail,
        })

    # --- KPIs ---
    total_devices = len(device_mapping)
    devices_reporting = 0
    if has_durations:
        recent = intervals_df[intervals_df["interval_end"] >= latest_event - pd.Timedelta(days=1)]
        devices_reporting = int(recent["device_id"].nunique())
    elif hourly_df is not None and not hourly_df.empty:
        devices_reporting = int(hourly_df["device_id"].nunique())

    events_frame = daily_df if daily_df is not None and not daily_df.empty else hourly_df
    total_events, events_spark = None, None
    if events_frame is not None and not events_frame.empty and "event_count" in events_frame.columns:
        filtered_events = events_frame
        if devices_filter is not None:
            filtered_events = filtered_events[filtered_events["device_name"].isin(devices_filter)]
        total_events = int(filtered_events["event_count"].sum())
        bucket_col = "event_day" if "event_day" in filtered_events.columns else "event_hour"
        if bucket_col in filtered_events.columns and not filtered_events.empty:
            grouped = (
                filtered_events.groupby(bucket_col)["event_count"].sum().sort_index()
            )
            events_spark = [int(v) for v in grouped.tail(5).tolist()]

    on_time_latest_day, on_time_spark = None, None
    if on_time_df is not None and not on_time_df.empty:
        windowed_on_time = on_time_df
        if devices_filter is not None:
            windowed_on_time = windowed_on_time[windowed_on_time["device_name"].isin(devices_filter)]
        if not windowed_on_time.empty:
            daily_totals = windowed_on_time.groupby("event_day")["on_minutes"].sum().sort_index()
            on_time_latest_day = float(daily_totals.iloc[-1])
            on_time_spark = [round(float(v), 1) for v in daily_totals.tail(3).tolist()]

    kpis = [
        {
            "key": "devices_reporting",
            "label": "Devices reporting",
            "value": f"{devices_reporting} / {total_devices or '—'}",
            "sub": "in the last 24h",
            "spark": None,
        },
        {
            "key": "events",
            "label": "Events ingested",
            "value": f"{total_events:,}" if total_events is not None else "—",
            "sub": "last 30 days",
            "spark": events_spark,
        },
        {
            "key": "on_time",
            "label": "Total on-time, last day",
            "value": humanize_minutes(on_time_latest_day) if on_time_latest_day is not None else "—",
            "sub": "across all devices",
            "spark": on_time_spark,
        },
        {
            "key": "latest_event",
            "label": "Latest event",
            "value": latest_event.strftime("%d %b, %H:%M"),
            # Wall-clock on purpose here (see module docstring): this is the
            # one field that answers "is the pipeline stale right now".
            "sub": relative_time(latest_event),
            "spark": None,
        },
    ]

    return {
        "source": source,
        "latest_event": _iso(latest_event),
        "window": window,
        "all_devices": known_devices,
        "kpis": kpis,
        "timeline": {"lanes": lanes, "intervals": timeline_intervals},
        "on_time": on_time_entries,
        "devices": device_entries,
        "empty": False,
        "empty_reason": None,
    }


def build_health() -> dict:
    """Builds the `/api/health` payload (see docs/api_contract.md).

    Never raises: `provider.is_available()` is already contractually
    non-raising, and the metrics load below shares `load_metrics()`'s
    never-raise contract.
    """
    # Imported lazily so a missing provider package/key never breaks
    # importing this module (mirrors llm_provider.py's own lazy-import rule).
    from app.agent.llm_provider import AnthropicProvider, GeminiProvider, OllamaProvider, get_provider

    metrics = load_metrics()
    daily_df = metrics.get("daily")
    hourly_df = metrics.get("hourly")
    intervals_df = metrics.get("intervals")

    candidates = []
    if daily_df is not None and not daily_df.empty and "last_seen_at" in daily_df.columns:
        candidates.append(pd.Timestamp(daily_df["last_seen_at"].max()))
    if intervals_df is not None and not intervals_df.empty:
        candidates.append(pd.Timestamp(intervals_df["interval_end"].max()))
    if not candidates and hourly_df is not None and not hourly_df.empty and "last_seen_at" in hourly_df.columns:
        candidates.append(pd.Timestamp(hourly_df["last_seen_at"].max()))
    latest_event = max(candidates) if candidates else None

    try:
        provider = get_provider()
        available = provider.is_available()
    except Exception:  # pylint: disable=broad-except
        # is_available() is contractually non-raising, but get_provider()
        # itself is trivial construction — belt and suspenders so this
        # endpoint truly can never 500.
        provider, available = None, False

    if isinstance(provider, GeminiProvider):
        provider_name, provider_label = "gemini", "Gemini"
        model = provider.active_model
        guidance = None if available else (
            "Set GEMINI_API_KEY (free key from Google AI Studio: "
            "aistudio.google.com) to enable the agent."
        )
    elif isinstance(provider, OllamaProvider):
        provider_name, provider_label = "ollama", "Ollama"
        model = provider.model
        guidance = None if available else (
            "Local model not reachable. Install Ollama, run `ollama serve`, and "
            "`ollama pull qwen3:8b` (or set OLLAMA_MODEL)."
        )
    elif isinstance(provider, AnthropicProvider):
        provider_name, provider_label = "anthropic", "Anthropic"
        model = provider.model
        guidance = None if available else "Set ANTHROPIC_API_KEY to enable the agent."
    else:
        provider_name, provider_label, model = None, None, None
        guidance = "No LLM provider is available. Set LLM_PROVIDER plus the matching credentials."

    return {
        "data_source": metrics["source"],
        "latest_event": _iso(latest_event),
        # Wall-clock on purpose (see module docstring): a health check answers
        # "is this pipeline stale right now", not "how does this dataset look
        # relative to itself".
        "freshness_label": relative_time(latest_event),
        "provider": provider_name,
        "provider_label": provider_label,
        "model": model,
        "available": bool(available),
        "guidance": guidance,
    }
