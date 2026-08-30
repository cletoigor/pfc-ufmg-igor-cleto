"""
Unit tests for app/agent/tools.py.

Tests call the `.func` attribute of each `@beta_tool`-decorated function to
invoke the plain underlying Python callable. No real Tuya or Anthropic calls
are ever made; `control_device` is only exercised with `dry_run=True`.
"""
import json

import pytest

from app.agent import tools as tools_module

query_iot_data = tools_module.query_iot_data.func
get_device_state = tools_module.get_device_state.func
control_device = tools_module.control_device.func


@pytest.fixture(autouse=True)
def isolate_data_paths(tmp_path, monkeypatch):
    """Point the tools module at an empty tmp dir so tests never touch the
    real (or possibly absent) app/data/{warehouse.duckdb,marts,staging}."""
    fake_warehouse = tmp_path / "warehouse.duckdb"
    fake_marts_glob = str(tmp_path / "marts" / "**" / "*.parquet")
    fake_staging_glob = str(tmp_path / "staging" / "**" / "*.parquet")

    monkeypatch.setattr(tools_module, "WAREHOUSE_DB_PATH", str(fake_warehouse))
    monkeypatch.setattr(tools_module, "MARTS_GLOB", fake_marts_glob)
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
    # "Fita de LED" is a real entry in app/device_mapping.json.
    result = get_device_state("Fita de LED")
    assert "No data yet" in result


# --- control_device ---


def test_control_device_unknown_device_refuses():
    result = control_device("Nonexistent Gadget", "on", dry_run=True)
    assert "Unknown device" in result
    assert "Refusing" in result


def test_control_device_unknown_action_refuses():
    result = control_device("Fita de LED", "explode", dry_run=True)
    assert "Unknown action" in result


def test_control_device_dry_run_returns_expected_payload():
    result_json = control_device("Fita de LED", "on", dry_run=True)
    result = json.loads(result_json)

    assert result["dry_run"] is True
    assert result["success"] is None
    assert result["response"] is None
    assert result["payload"] == {"commands": [{"code": "switch_1", "value": True}]}
    # Device id resolved from app/device_mapping.json.
    assert result["device_id"] == "ebb50554f386a6d20fvbwv"


def test_control_device_dry_run_off_action():
    result_json = control_device("Ventilador do quarto", "off", dry_run=True)
    result = json.loads(result_json)

    assert result["dry_run"] is True
    assert result["payload"] == {"commands": [{"code": "switch_1", "value": False}]}


def test_control_device_dry_run_case_insensitive_name():
    result_json = control_device("fita de led", "on", dry_run=True)
    result = json.loads(result_json)
    assert result["device_id"] == "ebb50554f386a6d20fvbwv"
