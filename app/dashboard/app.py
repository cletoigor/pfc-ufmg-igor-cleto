"""
Streamlit dashboard: the filmable surface for the home-IoT AI copilot.

Two areas:
  1. Data view — per-device activity charts + "last seen" tiles, read from
     the persistent DuckDB warehouse (falling back to the marts/staging
     Parquet layers, and to a friendly empty-state card if nothing has been
     ingested yet).
  2. AI chat panel — wired to `app.agent.agent.run_agent`. Shows the agent's
     tool trace (the SQL it wrote, any device command it sent) inline, and
     gates real device actuation behind a "Dry run (safe)" toggle.

Run with:  app/.venv/bin/streamlit run app/dashboard/app.py
"""
import glob
import json
import os

import duckdb
import plotly.express as px
import streamlit as st

# ---------------------------------------------------------------------------
# Paths (mirrors the layout/fallback logic in app/agent/tools.py, kept
# independent here so this module has no import-time dependency beyond
# app.agent.agent.run_agent for the chat panel).
# ---------------------------------------------------------------------------
_DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_DASHBOARD_DIR)

WAREHOUSE_DB_PATH = os.path.join(_APP_DIR, "data", "warehouse.duckdb")
MARTS_HOURLY_GLOB = os.path.join(_APP_DIR, "data", "marts", "hourly", "**", "*.parquet")
MARTS_DAILY_GLOB = os.path.join(_APP_DIR, "data", "marts", "daily", "**", "*.parquet")
STAGING_GLOB = os.path.join(_APP_DIR, "data", "staging", "**", "*.parquet")
DEVICE_MAPPING_PATH = os.path.join(_APP_DIR, "device_mapping.json")


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_device_mapping() -> dict:
    """device_id -> friendly name, loaded from app/device_mapping.json."""
    try:
        with open(DEVICE_MAPPING_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@st.cache_data(ttl=30, show_spinner=False)
def load_metrics() -> dict:
    """Loads per-device hourly/daily rollups, trying each layer in order.

    Returns {"source": "warehouse"|"marts"|"staging"|None,
             "hourly": DataFrame|None, "daily": DataFrame|None,
             "error": str|None}.
    Never raises — a missing/partial data layer degrades gracefully to the
    next fallback, and if nothing is available at all, source is None so the
    caller can render the empty-state card.
    """
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
                if "device_metrics_hourly" in tables or "device_metrics_daily" in tables:
                    hourly = (
                        conn.execute(
                            "SELECT * FROM device_metrics_hourly ORDER BY event_hour"
                        ).df()
                        if "device_metrics_hourly" in tables
                        else None
                    )
                    daily = (
                        conn.execute(
                            "SELECT * FROM device_metrics_daily ORDER BY event_day"
                        ).df()
                        if "device_metrics_daily" in tables
                        else None
                    )
                    return {"source": "warehouse", "hourly": hourly, "daily": daily, "error": None}
            finally:
                conn.close()
        except duckdb.Error:
            pass  # fall through to the Parquet fallbacks below

    # 2) Gold marts Parquet (hourly/daily written directly by the mart asset).
    has_hourly_marts = bool(glob.glob(MARTS_HOURLY_GLOB, recursive=True))
    has_daily_marts = bool(glob.glob(MARTS_DAILY_GLOB, recursive=True))
    if has_hourly_marts or has_daily_marts:
        try:
            conn = duckdb.connect(database=":memory:")
            try:
                hourly = (
                    conn.execute(
                        f"SELECT * FROM read_parquet('{MARTS_HOURLY_GLOB}', hive_partitioning=1) "
                        "ORDER BY event_hour"
                    ).df()
                    if has_hourly_marts
                    else None
                )
                daily = (
                    conn.execute(
                        f"SELECT * FROM read_parquet('{MARTS_DAILY_GLOB}', hive_partitioning=1) "
                        "ORDER BY event_day"
                    ).df()
                    if has_daily_marts
                    else None
                )
                return {"source": "marts", "hourly": hourly, "daily": daily, "error": None}
            finally:
                conn.close()
        except duckdb.Error:
            pass

    # 3) Raw staging Parquet — no rollups exist yet, so compute a quick hourly
    #    rollup on the fly (same shape as gold_device_metrics) just for the charts.
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
                    "hourly": hourly,
                    "daily": None,
                    "error": None,
                }
            finally:
                conn.close()
        except duckdb.Error as e:
            return {"source": None, "hourly": None, "daily": None, "error": str(e)}

    return {"source": None, "hourly": None, "daily": None, "error": None}


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Home IoT Copilot",
    page_icon="🏠",
    layout="wide",
)

st.title("🏠 Home IoT Copilot")
st.caption(
    "Live telemetry from six Tuya devices at home, ingested by a Dagster pipeline "
    "and fronted by an AI agent that can answer questions in plain English — "
    "and, with a real command, act on the devices themselves."
)

device_mapping = load_device_mapping()
metrics = load_metrics()

data_col, chat_col = st.columns([3, 2], gap="large")

# ---------------------------------------------------------------------------
# Left: data view
# ---------------------------------------------------------------------------
with data_col:
    st.subheader("Device activity")

    if metrics["source"] is None:
        with st.container(border=True):
            st.markdown("### No data yet")
            st.write(
                "The warehouse and the marts/staging Parquet layers are all empty. "
                "Run the Dagster pipeline first:"
            )
            st.code("dagster dev   # then materialize tuya_processing_job", language="bash")
            st.write("Once it has ingested at least one batch of events, refresh this page.")
            if metrics["error"]:
                st.caption(f"(diagnostic: {metrics['error']})")
    else:
        st.caption(f"Data source: **{metrics['source']}**")

        hourly_df = metrics.get("hourly")
        daily_df = metrics.get("daily")
        chart_df, bucket_col, granularity_label = (
            (hourly_df, "event_hour", "hourly")
            if hourly_df is not None and not hourly_df.empty
            else (daily_df, "event_day", "daily")
        )

        if chart_df is None or chart_df.empty:
            st.info("Data source is available but has no rows yet.")
        else:
            fig = px.line(
                chart_df,
                x=bucket_col,
                y="event_count",
                color="device_name",
                markers=True,
                title=f"Events per device ({granularity_label})",
                labels={
                    bucket_col: "Time",
                    "event_count": "Event count",
                    "device_name": "Device",
                },
            )
            fig.update_layout(legend_title_text="Device", height=420)
            st.plotly_chart(fig, use_container_width=True)

        # "Last seen" tiles, one per known device (friendly names from device_mapping.json).
        st.subheader("Last seen")
        last_seen_by_id = {}
        source_df = hourly_df if hourly_df is not None and not hourly_df.empty else daily_df
        last_seen_col = "last_seen_at"
        if source_df is not None and not source_df.empty and last_seen_col in source_df.columns:
            grouped = source_df.groupby("device_id")[last_seen_col].max()
            last_seen_by_id = grouped.to_dict()

        tile_cols = st.columns(len(device_mapping) or 1)
        for (device_id, friendly_name), col in zip(device_mapping.items(), tile_cols):
            with col:
                with st.container(border=True):
                    st.markdown(f"**{friendly_name}**")
                    last_seen = last_seen_by_id.get(device_id)
                    if last_seen is None:
                        st.caption("No events yet")
                    else:
                        st.write(str(last_seen))

# ---------------------------------------------------------------------------
# Right: AI chat panel
# ---------------------------------------------------------------------------
with chat_col:
    st.subheader("AI copilot")

    dry_run = st.toggle("Dry run (safe)", value=True, key="dry_run_toggle")
    if dry_run:
        st.caption("Dry run ON — device commands are simulated, nothing real is sent.")
    else:
        st.caption("⚠️ Dry run OFF — a control command will hit the real Tuya device.")

    from app.agent.llm_provider import AnthropicProvider, GeminiProvider, OllamaProvider, get_provider

    provider = get_provider()
    provider_available = provider.is_available()

    if "agent_history" not in st.session_state:
        st.session_state.agent_history = []  # Anthropic-format messages, fed back to run_agent
    if "display_turns" not in st.session_state:
        st.session_state.display_turns = []  # what we render: [{"role","text","tool_trace"}]

    # Render prior turns.
    for turn in st.session_state.display_turns:
        with st.chat_message(turn["role"]):
            st.write(turn["text"])
            if turn.get("tool_trace"):
                with st.expander(f"🔧 Agent tool trace ({len(turn['tool_trace'])} call(s))"):
                    for call in turn["tool_trace"]:
                        st.markdown(f"**Tool:** `{call['tool']}`")
                        tool_input = call.get("input") or {}
                        if "sql" in tool_input:
                            st.code(tool_input["sql"], language="sql")
                        else:
                            st.json(tool_input)
                        output = call.get("output")
                        if isinstance(output, str):
                            try:
                                st.json(json.loads(output))
                            except (json.JSONDecodeError, TypeError):
                                st.text(output)
                        elif output is not None:
                            st.json(output)
                        st.divider()

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

    user_message = st.chat_input(
        "Ask about the devices, or tell the agent to control one…",
        disabled=not provider_available,
    )

    if user_message:
        st.session_state.display_turns.append(
            {"role": "user", "text": user_message, "tool_trace": None}
        )
        with st.chat_message("user"):
            st.write(user_message)

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    from app.agent.agent import run_agent

                    result = run_agent(
                        user_message,
                        dry_run=dry_run,
                        history=st.session_state.agent_history,
                    )
                    reply = result.get("reply", "")
                    tool_trace = result.get("tool_trace", [])

                    st.session_state.agent_history.append(
                        {"role": "user", "content": user_message}
                    )
                    st.session_state.agent_history.append(
                        {"role": "assistant", "content": reply}
                    )
                except Exception as e:  # pylint: disable=broad-except
                    reply = f"The agent hit an error and couldn't complete this turn: {e}"
                    tool_trace = []

            st.write(reply)
            if tool_trace:
                with st.expander(f"🔧 Agent tool trace ({len(tool_trace)} call(s))"):
                    for call in tool_trace:
                        st.markdown(f"**Tool:** `{call['tool']}`")
                        tool_input = call.get("input") or {}
                        if "sql" in tool_input:
                            st.code(tool_input["sql"], language="sql")
                        else:
                            st.json(tool_input)
                        output = call.get("output")
                        if isinstance(output, str):
                            try:
                                st.json(json.loads(output))
                            except (json.JSONDecodeError, TypeError):
                                st.text(output)
                        elif output is not None:
                            st.json(output)
                        st.divider()

        st.session_state.display_turns.append(
            {"role": "assistant", "text": reply, "tool_trace": tool_trace}
        )
