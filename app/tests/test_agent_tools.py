"""
Unit tests for app/agent/tools.py.

Tests call the plain callables via the provider-neutral `TOOLS` registry. No
real Tuya, Ollama, or Anthropic calls are ever made; `control_device` is only
exercised with `dry_run=True`.
"""
import json

import duckdb

import pytest

from app.agent import tools as tools_module
from app.agent.tools import TOOLS

query_iot_data = TOOLS["query_iot_data"]["callable"]
get_device_state = TOOLS["get_device_state"]["callable"]
control_device = TOOLS["control_device"]["callable"]


@pytest.fixture(autouse=True)
def isolate_data_paths(tmp_path, monkeypatch):
    """Point the tools module at an empty tmp dir so tests never touch the
    real (or possibly absent) app/data/{warehouse.duckdb,marts,staging}."""
    fake_warehouse = tmp_path / "warehouse.duckdb"
    fake_staging_glob = str(tmp_path / "staging" / "**" / "*.parquet")
    fake_mart_globs = {
        table: str(tmp_path / "marts" / table / "**" / "*.parquet")
        for table in tools_module.MART_GLOBS
    }

    monkeypatch.setattr(tools_module, "WAREHOUSE_DB_PATH", str(fake_warehouse))
    monkeypatch.setattr(tools_module, "MART_GLOBS", fake_mart_globs)
    monkeypatch.setattr(tools_module, "STAGING_GLOB", fake_staging_glob)
    yield


# --- query_iot_data: SQL safety gate ---


@pytest.mark.parametrize(
    "bad_sql",
    [
        "DROP TABLE device_metrics_hourly",
        "INSERT INTO device_metrics_hourly VALUES (1)",
        "DELETE FROM device_metrics_hourly",
        "UPDATE device_metrics_hourly SET event_count = 0",
        "ATTACH 'evil.db' AS evil",
        "PRAGMA database_list",
        "SELECT 1; DROP TABLE device_metrics_hourly",
        "",
        "   ",
    ],
)
def test_query_iot_data_rejects_unsafe_sql(bad_sql):
    result = query_iot_data(bad_sql)
    assert result.startswith("Error")


def test_query_iot_data_allows_select_but_no_data_available():
    result = query_iot_data("SELECT * FROM device_metrics_hourly")
    assert "No data yet" in result


def test_query_iot_data_allows_with_and_show():
    # These should pass the safety gate (not be rejected as unsafe); with no
    # backing data they fall through to the "no data" message rather than an
    # "Error:" safety rejection.
    for sql in ("WITH x AS (SELECT 1) SELECT * FROM x", "SHOW TABLES"):
        result = query_iot_data(sql)
        assert not result.startswith("Error:")


# --- get_device_state ---


def test_get_device_state_unknown_device():
    result = get_device_state("Nonexistent Gadget")
    assert "Unknown device" in result


def test_get_device_state_known_device_no_data():
    # "LED Strip" is a real entry in app/device_mapping.json.
    result = get_device_state("LED Strip")
    assert "No data yet" in result


# --- control_device ---


def test_control_device_unknown_device_refuses():
    result = control_device("Nonexistent Gadget", "on", dry_run=True)
    assert "Unknown device" in result
    assert "Refusing" in result


def test_control_device_unknown_action_refuses():
    result = control_device("LED Strip", "explode", dry_run=True)
    assert "Unknown action" in result


def test_control_device_dry_run_returns_expected_payload():
    result_json = control_device("LED Strip", "on", dry_run=True)
    result = json.loads(result_json)

    assert result["dry_run"] is True
    assert result["success"] is None
    assert result["response"] is None
    assert result["payload"] == {"commands": [{"code": "switch_1", "value": True}]}
    # Device id resolved from app/device_mapping.json.
    assert result["device_id"] == "ebb50554f386a6d20fvbwv"


def test_control_device_dry_run_off_action():
    result_json = control_device("Bedroom Fan", "off", dry_run=True)
    result = json.loads(result_json)

    assert result["dry_run"] is True
    assert result["payload"] == {"commands": [{"code": "switch_1", "value": False}]}


def test_control_device_dry_run_case_insensitive_name():
    result_json = control_device("led strip", "on", dry_run=True)
    result = json.loads(result_json)
    assert result["device_id"] == "ebb50554f386a6d20fvbwv"


# --- control_device addresses the right Tuya datapoint ---


def test_action_to_commands_uses_the_devices_own_switch_code():
    """Devices report on/off through different codes (switch_1 / switch_led /
    switch); a command hardcoded to switch_1 would no-op on the others."""
    assert tools_module._action_to_commands("off", "switch_led") == [
        {"code": "switch_led", "value": False}
    ]
    assert tools_module._action_to_commands("on", "switch") == [
        {"code": "switch", "value": True}
    ]
    # Unchanged default when nothing better is known.
    assert tools_module._action_to_commands("on") == [{"code": "switch_1", "value": True}]


def test_resolve_switch_code_falls_back_when_there_is_no_data():
    # isolate_data_paths points every layer at an empty tmp dir.
    assert tools_module.resolve_switch_code("whatever") == tools_module.DEFAULT_SWITCH_CODE


def test_resolve_switch_code_reads_the_code_from_the_warehouse(tmp_path, monkeypatch):
    warehouse = tmp_path / "wh.duckdb"
    conn = duckdb.connect(str(warehouse))
    try:
        conn.execute(
            """
            CREATE TABLE device_state_intervals AS SELECT * FROM (VALUES
                ('dev-1', 'switch_led', TIMESTAMP '2026-01-01 10:00:00'),
                ('dev-1', 'switch_led', TIMESTAMP '2026-01-02 10:00:00'),
                ('dev-2', 'switch',     TIMESTAMP '2026-01-02 10:00:00')
            ) t(device_id, switch_code, interval_start)
            """
        )
        # _warehouse_ready() looks for a known mart table.
        conn.execute("CREATE TABLE device_metrics_daily AS SELECT 1 AS x")
    finally:
        conn.close()

    monkeypatch.setattr(tools_module, "WAREHOUSE_DB_PATH", str(warehouse))

    assert tools_module.resolve_switch_code("dev-1") == "switch_led"
    assert tools_module.resolve_switch_code("dev-2") == "switch"
    assert tools_module.resolve_switch_code("dev-unknown") == tools_module.DEFAULT_SWITCH_CODE
