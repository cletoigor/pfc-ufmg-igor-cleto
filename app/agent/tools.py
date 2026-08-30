"""
Tool functions exposed to the AI agent via the Anthropic Tool Runner
(`@beta_tool` decorated — see app/agent/agent.py).

Three tools:
    query_iot_data(sql)                          — read-only DuckDB SQL over the marts.
    get_device_state(device_name)                — latest known reading for a device.
    control_device(device_name, action, dry_run) — actuate a device (dry-run by default).
"""
import json
import os
import re

import duckdb
from anthropic import beta_tool

from app.agent.tuya_control import (
    load_device_registry,
    resolve_device_id,
    send_device_command,
)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WAREHOUSE_DB_PATH = os.path.join(_APP_DIR, "data", "warehouse.duckdb")
MARTS_GLOB = os.path.join(_APP_DIR, "data", "marts", "**", "*.parquet")
STAGING_GLOB = os.path.join(_APP_DIR, "data", "staging", "**", "*.parquet")

KNOWN_TABLES = ("device_metrics_hourly", "device_metrics_daily")

# Only allow read-only, single-statement SELECT/WITH/EXPLAIN/DESCRIBE queries.
# Reject any statement that could mutate the database or the filesystem.
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|COPY|EXPORT|"
    r"IMPORT|PRAGMA|CALL|LOAD|INSTALL|VACUUM|CHECKPOINT|SET)\b",
    re.IGNORECASE,
)
_ALLOWED_START = re.compile(r"^\s*(SELECT|WITH|EXPLAIN|DESCRIBE|SHOW)\b", re.IGNORECASE)


def _reject_unsafe_sql(sql: str) -> str | None:
    """Returns an error message if `sql` is not a safe read-only query, else None."""
    stripped = sql.strip().rstrip(";")
    if not stripped:
        return "Empty SQL query."
    if not _ALLOWED_START.match(stripped):
        return (
            "Only read-only SELECT/WITH/EXPLAIN/DESCRIBE/SHOW statements are allowed."
        )
    if _FORBIDDEN_KEYWORDS.search(stripped):
        return "Query contains a forbidden keyword (writes/DDL/attach/copy/etc. are not permitted)."
    if ";" in stripped:
        return "Only a single statement is allowed (no ';'-separated statements)."
    return None


def _warehouse_ready() -> bool:
    if not os.path.exists(WAREHOUSE_DB_PATH):
        return False
    try:
        conn = duckdb.connect(WAREHOUSE_DB_PATH, read_only=True)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables"
                ).fetchall()
            }
            return any(t in tables for t in KNOWN_TABLES)
        finally:
            conn.close()
    except duckdb.Error:
        return False


def _open_connection():
    """Opens a read-only DuckDB connection, preferring the persistent warehouse.

    Falls back to an in-memory connection with a view over the marts (or
    staging) Parquet files when the warehouse doesn't exist yet or has no
    known tables — this happens the first time the pipeline hasn't run yet.

    Returns (connection, mode, error) where mode is one of
    "warehouse" / "marts" / "staging" / None, and error is a user-facing
    message when no data source could be found at all.
    """
    if _warehouse_ready():
        return duckdb.connect(WAREHOUSE_DB_PATH, read_only=True), "warehouse", None

    # Fall back to reading marts Parquet directly.
    import glob

    if glob.glob(MARTS_GLOB, recursive=True):
        conn = duckdb.connect(database=":memory:")
        conn.execute(
            f"CREATE VIEW device_metrics_hourly AS "
            f"SELECT * FROM read_parquet('{MARTS_GLOB}', hive_partitioning=1) "
            f"WHERE event_hour_date IS NOT NULL"
        )
        conn.execute(
            f"CREATE VIEW device_metrics_daily AS "
            f"SELECT * FROM read_parquet('{MARTS_GLOB}', hive_partitioning=1) "
            f"WHERE event_day_date IS NOT NULL"
        )
        return conn, "marts", None

    if glob.glob(STAGING_GLOB, recursive=True):
        conn = duckdb.connect(database=":memory:")
        conn.execute(
            f"CREATE VIEW staging_events AS "
            f"SELECT * FROM read_parquet('{STAGING_GLOB}', hive_partitioning=1)"
        )
        return conn, "staging", None

    return None, None, (
        "No data yet — the warehouse, marts, and staging layers are all empty. "
        "Run the Dagster pipeline (tuya_processing_job) first, then ask again."
    )


@beta_tool
def query_iot_data(sql: str) -> str:
    """Run a read-only DuckDB SQL query over the IoT metrics warehouse.

    Query the `device_metrics_hourly` and `device_metrics_daily` tables
    (columns: device_id, device_name, event_hour/event_day, event_count,
    last_seen_at, on_event_count). Only SELECT/WITH/EXPLAIN/DESCRIBE/SHOW
    statements are accepted — no writes, DDL, ATTACH, or COPY.

    Args:
        sql: The read-only SQL query to run, e.g.
            "SELECT device_name, sum(event_count) FROM device_metrics_daily GROUP BY 1".
    """
    error = _reject_unsafe_sql(sql)
    if error:
        return f"Error: {error}"

    conn, mode, no_data_error = _open_connection()
    if no_data_error:
        return no_data_error

    try:
        result = conn.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
    except duckdb.Error as e:
        return f"Error running query: {e}"
    finally:
        conn.close()

    if not rows:
        return json.dumps({"source": mode, "columns": columns, "rows": []}, default=str)

    # Cap output size for very large result sets.
    truncated = len(rows) > 200
    rows = rows[:200]
    payload = {
        "source": mode,
        "columns": columns,
        "rows": [list(r) for r in rows],
        "truncated": truncated,
    }
    return json.dumps(payload, default=str)


@beta_tool
def get_device_state(device_name: str) -> str:
    """Get the latest known reading / last-seen info for a named device.

    Args:
        device_name: The device's friendly name (e.g. "Ventilador do quarto"),
            matched case-insensitively against the device registry.
    """
    registry = load_device_registry()
    device_id = resolve_device_id(device_name, registry)
    if device_id is None:
        known = ", ".join(sorted(registry.values()))
        return f"Unknown device '{device_name}'. Known devices: {known}."

    conn, mode, no_data_error = _open_connection()
    if no_data_error:
        return no_data_error

    try:
        row = conn.execute(
            "SELECT device_name, max(last_seen_at) AS last_seen_at, "
            "sum(event_count) AS total_events, sum(on_event_count) AS total_on_events "
            "FROM device_metrics_hourly WHERE device_id = ? GROUP BY device_name",
            [device_id],
        ).fetchone()
    except duckdb.Error as e:
        return f"Error looking up device state: {e}"
    finally:
        conn.close()

    if row is None:
        return (
            f"'{device_name}' is registered but has no readings yet in the "
            f"{mode} layer — it may be offline or the pipeline hasn't ingested "
            f"any events for it."
        )

    name, last_seen_at, total_events, total_on_events = row
    return json.dumps(
        {
            "device_name": name,
            "device_id": device_id,
            "source": mode,
            "last_seen_at": str(last_seen_at),
            "total_events": total_events,
            "total_on_events": total_on_events,
        },
        default=str,
    )


def _action_to_commands(action: str) -> list[dict] | None:
    """Translates a simple action into a Tuya commands payload.

    Uses the generic "switch_1" boolean code (the on/off switch code seen on
    the mapped devices in the control notebook). "toggle" is treated as "on"
    since the agent has no reliable live on/off state to flip from the
    metrics layer (which records discrete events, not continuous state).
    """
    normalized = action.strip().lower()
    if normalized in ("on", "ligar", "turn on", "turn_on"):
        return [{"code": "switch_1", "value": True}]
    if normalized in ("off", "desligar", "turn off", "turn_off"):
        return [{"code": "switch_1", "value": False}]
    if normalized in ("toggle", "alternar"):
        return [{"code": "switch_1", "value": True}]
    return None


@beta_tool
def control_device(device_name: str, action: str, dry_run: bool = True) -> str:
    """Actuate a named device (turn it on/off/toggle).

    Args:
        device_name: The device's friendly name (e.g. "Fita de LED"), matched
            case-insensitively against the device registry.
        action: One of "on", "off", or "toggle".
        dry_run: When True (the default), no real Tuya API call is made —
            the payload that WOULD be sent is returned instead.
    """
    registry = load_device_registry()
    device_id = resolve_device_id(device_name, registry)
    if device_id is None:
        known = ", ".join(sorted(registry.values()))
        return f"Unknown device '{device_name}'. Refusing to send a command. Known devices: {known}."

    commands = _action_to_commands(action)
    if commands is None:
        return f"Unknown action '{action}'. Supported actions: on, off, toggle."

    result = send_device_command(device_id, commands, dry_run=dry_run)
    return json.dumps(result, default=str)
