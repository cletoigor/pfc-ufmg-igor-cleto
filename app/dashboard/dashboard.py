"""
Streamlit dashboard: the filmable surface for the home-IoT AI copilot.

Three areas:
  1. A KPI strip — the headline numbers, so the page opens on facts rather
     than on a chart that has to be read.
  2. Data view — a device on/off timeline and per-device on-time, read from
     the persistent DuckDB warehouse (falling back to the marts/staging
     Parquet layers, and to a friendly empty-state card if nothing has been
     ingested yet).
  3. AI chat panel — wired to `app.agent.agent.run_agent`. Streams the agent's
     progress live (which tool it is calling, and how long each took), shows
     the SQL it wrote and any device command it produced. Device commands are
     always dry-run: the payload is shown, never sent.

Run with:  app/.venv/bin/streamlit run app/dashboard/dashboard.py
"""
import json
import os
import sys
from datetime import timedelta

# Streamlit only adds this script's own directory to sys.path, but the code
# below imports the sibling `app` package (repo_root/app) — add repo root
# (two levels up: dashboard/ -> app/ -> repo root) so that import resolves
# regardless of the cwd the app is launched from.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pandas as pd
import plotly.express as px
import streamlit as st

from app.agent.agent import run_agent
from app.agent.llm_provider import AnthropicProvider, GeminiProvider, OllamaProvider, get_provider
from app.api.data_access import (
    friendly_agent_error,
    humanize_minutes,
    load_device_mapping as _load_device_mapping,
    load_metrics as _load_metrics,
    relative_time,
)

# ---------------------------------------------------------------------------
# Palette. Single accent for data marks: every chart here plots one measure,
# and identity is carried by the axis label, so a per-device rainbow would
# double-encode what the axis already says. Status hues are reserved for state
# (a device being on) and never used as a series.
# ---------------------------------------------------------------------------
PALETTE = {
    "series": "#3987e5",
    "surface": "#1a1a19",
    "plane": "#0d0d0d",
    "ink": "#ffffff",
    "ink_secondary": "#c3c2b7",
    "muted": "#898781",
    "grid": "#2c2c2a",
    "axis": "#383835",
    "good": "#0ca30c",
    "warning": "#fab219",
    "critical": "#d03b3b",
}

FONT_STACK = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def style_figure(fig, *, height: int):
    """Applies the shared chart chrome: transparent surface, hairline grid,
    recessive axes, no legend (every chart here is single-series)."""
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_STACK, color=PALETTE["ink_secondary"], size=13),
        showlegend=False,
        hoverlabel=dict(
            bgcolor=PALETTE["surface"],
            bordercolor=PALETTE["axis"],
            font=dict(family=FONT_STACK, color=PALETTE["ink"]),
        ),
    )
    fig.update_xaxes(
        showgrid=True,
        gridcolor=PALETTE["grid"],
        gridwidth=1,
        linecolor=PALETTE["axis"],
        zeroline=False,
        tickfont=dict(color=PALETTE["muted"]),
        title=None,
    )
    fig.update_yaxes(
        showgrid=False,
        linecolor=PALETTE["axis"],
        zeroline=False,
        tickfont=dict(color=PALETTE["muted"]),
        title=None,
    )
    return fig


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_device_mapping() -> dict:
    """device_id -> friendly name, loaded from app/device_mapping.json."""
    return _load_device_mapping()


@st.cache_resource(show_spinner=False)
def cached_provider():
    """The provider is constructed once per session rather than per rerun.

    `is_available()` can make a network call (Ollama's `client.list()`), and
    every widget interaction reruns this script top-to-bottom — checking on
    each rerun made the whole page wait on that probe.
    """
    return get_provider()


@st.cache_data(ttl=30, show_spinner=False)
def load_metrics() -> dict:
    """Loads the gold tables, trying each storage layer in order.

    Returns {"source": "warehouse"|"marts"|"staging (computed on the fly)"|None,
             "hourly"/"daily"/"intervals"/"on_time": DataFrame|None,
             "error": str|None}.
    Never raises — a missing/partial data layer degrades gracefully to the
    next fallback, and if nothing is available at all, source is None so the
    caller can render the empty-state card.

    Delegates to app.api.data_access.load_metrics (shared with the web API
    backend); this wrapper only adds Streamlit's per-session cache.
    """
    return _load_metrics()


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Home IoT Copilot", page_icon="🏠", layout="wide")

st.markdown(
    f"""
    <style>
      .block-container {{ padding-top: 2.2rem; max-width: 1500px; }}
      /* Stat tiles and the device status cards share one card treatment. */
      div[data-testid="stMetric"] {{
        background: {PALETTE["surface"]};
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 10px;
        padding: 14px 16px;
      }}
      div[data-testid="stMetricLabel"] p {{
        color: {PALETTE["muted"]};
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }}
      .device-card {{
        background: {PALETTE["surface"]};
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 10px;
        padding: 12px 14px;
        margin-bottom: 10px;
      }}
      .device-card .name {{
        color: {PALETTE["ink"]};
        font-weight: 600;
        font-size: 0.95rem;
      }}
      .device-card .meta {{
        color: {PALETTE["muted"]};
        font-size: 0.8rem;
        margin-top: 2px;
      }}
      .state-dot {{
        display: inline-block; width: 8px; height: 8px;
        border-radius: 50%; margin-right: 7px; vertical-align: middle;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🏠 Home IoT Copilot")
st.caption(
    "Six Tuya smart-home devices, ingested by a Dagster pipeline into a DuckDB "
    "warehouse, and fronted by an AI agent that answers questions in plain "
    "English and can act on the devices."
)

device_mapping = load_device_mapping()
metrics = load_metrics()

intervals_df = metrics.get("intervals")
on_time_df = metrics.get("on_time")
daily_df = metrics.get("daily")
hourly_df = metrics.get("hourly")

has_durations = intervals_df is not None and not intervals_df.empty

# The dataset is a fixed historical window, so "now" for the purposes of
# freshness and current state is the newest event we have.
latest_event = None
for frame, column in ((intervals_df, "interval_end"), (hourly_df, "last_seen_at"),
                      (daily_df, "last_seen_at")):
    if frame is not None and not frame.empty and column in frame.columns:
        latest_event = pd.Timestamp(frame[column].max())
        break

# ---------------------------------------------------------------------------
# KPI strip
# ---------------------------------------------------------------------------
if metrics["source"] is not None:
    kpi_cols = st.columns(4)

    devices_reporting = 0
    if latest_event is not None and intervals_df is not None and not intervals_df.empty:
        recent = intervals_df[intervals_df["interval_end"] >= latest_event - timedelta(days=1)]
        devices_reporting = recent["device_id"].nunique()
    elif hourly_df is not None and not hourly_df.empty:
        devices_reporting = hourly_df["device_id"].nunique()

    kpi_cols[0].metric(
        "Devices reporting", f"{devices_reporting} / {len(device_mapping) or '—'}"
    )

    total_events = None
    for frame in (daily_df, hourly_df):
        if frame is not None and not frame.empty and "event_count" in frame.columns:
            total_events = int(frame["event_count"].sum())
            break
    kpi_cols[1].metric(
        "Events ingested", f"{total_events:,}" if total_events is not None else "—"
    )

    on_time_latest_day = None
    if on_time_df is not None and not on_time_df.empty:
        last_day = on_time_df["event_day"].max()
        on_time_latest_day = on_time_df[on_time_df["event_day"] == last_day]["on_minutes"].sum()
    kpi_cols[2].metric("Total on-time, last day", humanize_minutes(on_time_latest_day))

    kpi_cols[3].metric(
        "Latest event",
        latest_event.strftime("%d %b, %H:%M") if latest_event is not None else "—",
        help="Newest event in the warehouse. All timestamps are local time.",
    )

data_col, chat_col = st.columns([3, 2], gap="large")

# ---------------------------------------------------------------------------
# Left: data view
# ---------------------------------------------------------------------------
with data_col:
    if metrics["source"] is None:
        with st.container(border=True):
            st.markdown("### No data yet")
            st.write(
                "The warehouse and the marts/staging Parquet layers are all empty. "
                "Seed the demo dataset and build the marts:"
            )
            st.code(
                "python scripts/seed_synthetic_data.py\n"
                "dagster asset materialize -m app.definitions \\\n"
                "    --select 'staging_tuya_logs,gold_device_metrics'",
                language="bash",
            )
            st.write("Then refresh this page.")
            if metrics["error"]:
                st.caption(f"(diagnostic: {metrics['error']})")
    else:
        # --- Filters, in one row above the charts ---
        known_devices = sorted(
            set(device_mapping.values())
            | (set(intervals_df["device_name"].dropna()) if has_durations else set())
        )
        filter_cols = st.columns([3, 2])
        selected_devices = filter_cols[0].multiselect(
            "Devices", known_devices, default=known_devices, placeholder="All devices"
        )
        if not selected_devices:
            selected_devices = known_devices

        window_label = filter_cols[1].selectbox(
            "Time range", ("Last 7 days", "Last 14 days", "Last 30 days", "All history"),
            index=0,
        )
        window_days = {"Last 7 days": 7, "Last 14 days": 14, "Last 30 days": 30}.get(window_label)
        window_start = (
            latest_event - timedelta(days=window_days)
            if (window_days and latest_event is not None)
            else None
        )

        # --- Primary chart: on/off timeline ---
        st.subheader("When each device was on")
        if not has_durations:
            st.info(
                "The duration tables aren't built yet — rematerialize "
                "`gold_device_metrics` to enable the timeline."
            )
        else:
            on_intervals = intervals_df[
                intervals_df["is_on"] & intervals_df["device_name"].isin(selected_devices)
            ].copy()
            if window_start is not None:
                on_intervals = on_intervals[on_intervals["interval_end"] >= window_start]
                on_intervals["interval_start"] = on_intervals["interval_start"].clip(
                    lower=window_start
                )

            if on_intervals.empty:
                st.info("No device activity in the selected range.")
            else:
                on_intervals["Duration"] = on_intervals["duration_minutes"].map(
                    humanize_minutes
                )
                fig = px.timeline(
                    on_intervals.sort_values("device_name", ascending=False),
                    x_start="interval_start",
                    x_end="interval_end",
                    y="device_name",
                    custom_data=["Duration"],
                )
                fig.update_traces(
                    marker_color=PALETTE["series"],
                    marker_line_width=0,
                    hovertemplate=(
                        "<b>%{y}</b><br>%{base|%a %d %b, %H:%M} → %{x|%H:%M}"
                        "<br>on for %{customdata[0]}<extra></extra>"
                    ),
                )
                style_figure(fig, height=300)
                st.plotly_chart(fig, width="stretch")
                st.caption(
                    "Each bar is one continuous stretch with the device switched on."
                )

        # --- Secondary chart: total on-time per device ---
        if on_time_df is not None and not on_time_df.empty:
            st.subheader("Total time on")
            windowed = on_time_df[on_time_df["device_name"].isin(selected_devices)]
            if window_start is not None:
                windowed = windowed[windowed["event_day"] >= window_start.normalize()]

            if windowed.empty:
                st.info("No on-time recorded in the selected range.")
            else:
                totals = (
                    windowed.groupby("device_name", as_index=False)["on_minutes"]
                    .sum()
                    .sort_values("on_minutes")
                )
                totals["hours"] = totals["on_minutes"] / 60
                totals["label"] = totals["on_minutes"].map(humanize_minutes)
                bar = px.bar(
                    totals, x="hours", y="device_name", orientation="h",
                    text="label", custom_data=["label"],
                )
                bar.update_traces(
                    marker_color=PALETTE["series"],
                    marker_line_width=0,
                    textposition="outside",
                    textfont=dict(color=PALETTE["ink_secondary"], size=12),
                    cliponaxis=False,
                    hovertemplate="<b>%{y}</b><br>on for %{customdata[0]}<extra></extra>",
                )
                style_figure(bar, height=40 * len(totals) + 60)
                bar.update_xaxes(
                    title="hours",
                    title_font=dict(color=PALETTE["muted"]),
                    # Bug fix: the outside text label ("90 h 25 m") is drawn
                    # past the end of its bar, so without headroom the
                    # longest label gets clipped by the plot edge (this used
                    # to render as "90 h 3"). 15% headroom over the longest
                    # bar is enough for the widest label this dataset produces.
                    range=[0, totals["hours"].max() * 1.15],
                )
                st.plotly_chart(bar, width="stretch")

        # --- Device status tiles: 2 rows x 3 columns ---
        st.subheader("Device status")
        # Bug fix: on/off state still comes from the last state interval, but
        # `last_seen` must come from device_metrics_daily.last_seen_at per
        # device — device_state_intervals.interval_end is clipped to the same
        # global max(event_time) for every device's final interval, so using
        # it makes every device report an identical "just now".
        current_state = {}
        if has_durations:
            newest = intervals_df.sort_values("interval_end").groupby("device_id").tail(1)
            current_state = {
                row["device_id"]: bool(row["is_on"]) for _, row in newest.iterrows()
            }
        last_seen_by_device = {}
        if daily_df is not None and not daily_df.empty and "last_seen_at" in daily_df.columns:
            last_seen_by_device = daily_df.groupby("device_id")["last_seen_at"].max().to_dict()
        elif hourly_df is not None and not hourly_df.empty and "last_seen_at" in hourly_df.columns:
            last_seen_by_device = hourly_df.groupby("device_id")["last_seen_at"].max().to_dict()

        tile_items = list(device_mapping.items())
        for row_start in range(0, len(tile_items), 3):
            for col, (device_id, friendly_name) in zip(
                st.columns(3), tile_items[row_start:row_start + 3]
            ):
                is_on = current_state.get(device_id)
                last_seen = last_seen_by_device.get(device_id)
                if is_on is None:
                    dot, state_text = PALETTE["muted"], "no data"
                elif is_on:
                    dot, state_text = PALETTE["good"], "ON"
                else:
                    dot, state_text = PALETTE["muted"], "OFF"
                col.markdown(
                    f"""
                    <div class="device-card">
                      <div class="name">
                        <span class="state-dot" style="background:{dot}"></span>{friendly_name}
                      </div>
                      <div class="meta">{state_text} · {relative_time(last_seen, now=latest_event)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.caption(
            f"Data source: **{metrics['source']}** · timestamps in local time"
        )

# ---------------------------------------------------------------------------
# Right: AI chat panel
# ---------------------------------------------------------------------------
TOOL_LABELS = {
    "query_iot_data": "Querying the warehouse",
    "get_device_state": "Reading device state",
    "control_device": "Preparing a device command",
}

SUGGESTED_PROMPTS = [
    "Which device was on the longest this week?",
    "Did anything unusual stay on overnight?",
    "Turn off the LED strip",
]


def render_tool_trace(trace: list) -> None:
    """Renders the agent's tool calls as numbered steps.

    This is the part of the UI that shows the agent actually reasoning over the
    warehouse — the SQL it wrote and the exact device payload it produced — so
    it renders expanded, and query results become a table rather than raw JSON.
    """
    if not trace:
        return
    with st.expander(f"Agent steps ({len(trace)})", expanded=True):
        for index, call in enumerate(trace, start=1):
            label = TOOL_LABELS.get(call["tool"], call["tool"])
            timing = f" · {call['duration_ms']} ms" if call.get("duration_ms") is not None else ""
            marker = "⚠️" if call.get("is_error") else f"{index}."
            st.markdown(f"**{marker} {label}** `{call['tool']}`{timing}")

            tool_input = call.get("input") or {}
            if "sql" in tool_input:
                st.code(tool_input["sql"], language="sql")
            elif tool_input:
                st.json(tool_input, expanded=False)

            output = call.get("output")
            parsed = output
            if isinstance(output, str):
                try:
                    parsed = json.loads(output)
                except (json.JSONDecodeError, TypeError):
                    parsed = None

            if isinstance(parsed, dict) and "rows" in parsed and "columns" in parsed:
                rows, columns = parsed.get("rows") or [], parsed.get("columns") or []
                if rows:
                    st.dataframe(
                        pd.DataFrame(rows, columns=columns),
                        width="stretch",
                        hide_index=True,
                    )
                else:
                    st.caption("Query returned no rows.")
                if parsed.get("truncated"):
                    st.caption("Results truncated to the first 200 rows.")
            elif isinstance(parsed, dict) and "payload" in parsed:
                # A device command. The payload is the point: it is exactly what
                # would go to Tuya.
                st.code(json.dumps(parsed["payload"], indent=2), language="json")
                if parsed.get("error"):
                    st.warning(parsed["error"])
            elif parsed is not None:
                st.json(parsed, expanded=False)
            elif output:
                st.text(output)

            if index < len(trace):
                st.divider()


with chat_col:
    st.subheader("AI copilot")

    provider = cached_provider()
    provider_available = provider.is_available()

    if "agent_history" not in st.session_state:
        st.session_state.agent_history = []  # provider-format messages, fed back to run_agent
    if "display_turns" not in st.session_state:
        st.session_state.display_turns = []  # what we render: [{"role","text","tool_trace"}]

    # Suggested prompts — one click beats typing, and they advertise the range
    # of what the agent can do (query, anomaly reasoning, actuation).
    if provider_available and not st.session_state.display_turns:
        st.caption("Try asking:")
        for i, prompt in enumerate(SUGGESTED_PROMPTS):
            if st.button(prompt, key=f"suggest_{i}", width="stretch"):
                st.session_state.pending_prompt = prompt
                st.rerun()

    # Render prior turns.
    for turn in st.session_state.display_turns:
        with st.chat_message(turn["role"]):
            st.write(turn["text"])
            render_tool_trace(turn.get("tool_trace") or [])

    if not provider_available:
        if isinstance(provider, GeminiProvider):
            guidance = (
                "Set GEMINI_API_KEY (free key from Google AI Studio: "
                "aistudio.google.com) to enable the agent. The charts on the "
                "left still work without it."
            )
        elif isinstance(provider, OllamaProvider):
            guidance = (
                "Local model not reachable. Install Ollama, run `ollama serve`, and "
                "`ollama pull qwen3:8b` (or set OLLAMA_MODEL). The charts on the "
                "left still work without it."
            )
        elif isinstance(provider, AnthropicProvider):
            guidance = (
                "Set ANTHROPIC_API_KEY to enable the agent. The charts on the "
                "left still work without it."
            )
        else:
            guidance = (
                "No LLM provider is available. Set LLM_PROVIDER plus the "
                "matching credentials (GEMINI_API_KEY by default). The charts "
                "on the left still work without it."
            )
        st.info(guidance)

    typed_message = st.chat_input(
        "Ask about the devices, or tell the agent to control one…",
        disabled=not provider_available,
    )
    user_message = typed_message or st.session_state.pop("pending_prompt", None)

    if user_message:
        st.session_state.display_turns.append(
            {"role": "user", "text": user_message, "tool_trace": None}
        )
        with st.chat_message("user"):
            st.write(user_message)

        with st.chat_message("assistant"):
            # Live progress. `run_agent` makes up to MAX_ITERATIONS sequential
            # model round-trips; without this the panel would sit on a single
            # opaque spinner for the whole turn.
            with st.status("Thinking…", expanded=True) as status:
                def on_event(event: dict) -> None:
                    kind = event["type"]
                    if kind == "model_call":
                        status.update(label=f"Thinking… (step {event['iteration']})")
                    elif kind == "tool_call_start":
                        label = TOOL_LABELS.get(event["tool"], event["tool"])
                        status.update(label=label)
                        st.write(f"→ {label}")
                    elif kind == "tool_call_end":
                        note = "failed" if event["is_error"] else f"{event['duration_ms']} ms"
                        st.write(f"   ✓ {event['tool']} ({note})")

                try:
                    result = run_agent(
                        user_message,
                        dry_run=True,
                        history=st.session_state.agent_history,
                        on_event=on_event,
                    )
                    reply = result.get("reply", "")
                    tool_trace = result.get("tool_trace", [])

                    st.session_state.agent_history.append(
                        {"role": "user", "content": user_message}
                    )
                    st.session_state.agent_history.append(
                        {"role": "assistant", "content": reply}
                    )
                    status.update(label="Done", state="complete", expanded=False)
                except Exception as e:  # pylint: disable=broad-except
                    reply = friendly_agent_error(e)
                    tool_trace = []
                    status.update(label="Failed", state="error", expanded=False)

            st.write(reply)
            render_tool_trace(tool_trace)

        st.session_state.display_turns.append(
            {"role": "assistant", "text": reply, "tool_trace": tool_trace}
        )

    if st.session_state.display_turns:
        if st.button("Clear chat", width="stretch"):
            st.session_state.agent_history = []
            st.session_state.display_turns = []
            st.rerun()
