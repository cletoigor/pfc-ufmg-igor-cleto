"""
Tests for app/api/data_access.py.

Covers the three-tier fallback chain (warehouse -> marts -> staging -> empty),
`build_overview`'s never-raise/empty-state contract, device filtering, and a
regression test for the "all devices show the same last_seen" bug: two
devices whose final state interval is clipped to the same global
max(event_time) must still report DIFFERENT `last_seen` values, taken from
`device_metrics_daily.last_seen_at` rather than
`device_state_intervals.interval_end`.
"""
import json

import duckdb
import pandas as pd
import pytest

from app.api import data_access


@pytest.fixture(autouse=True)
def isolate_data_paths(tmp_path, monkeypatch):
    """Point data_access at an empty tmp dir so tests never touch the real
    (or possibly absent) app/data/{warehouse.duckdb,marts,staging}."""
    fake_warehouse = tmp_path / "warehouse.duckdb"
    fake_staging_glob = str(tmp_path / "staging" / "**" / "*.parquet")
    fake_mart_globs = {
        key: str(tmp_path / "marts" / key / "**" / "*.parquet")
        for key in data_access.MART_GLOBS
    }

    monkeypatch.setattr(data_access, "WAREHOUSE_DB_PATH", str(fake_warehouse))
    monkeypatch.setattr(data_access, "MART_GLOBS", fake_mart_globs)
    monkeypatch.setattr(data_access, "STAGING_GLOB", fake_staging_glob)
    yield


def _write_device_mapping(tmp_path, monkeypatch, mapping):
    path = tmp_path / "device_mapping.json"
    path.write_text(json.dumps(mapping))
    monkeypatch.setattr(data_access, "DEVICE_MAPPING_PATH", str(path))


# --- load_metrics: fallback chain ---


def test_load_metrics_returns_none_source_when_nothing_exists():
    result = data_access.load_metrics()
    assert result["source"] is None
    assert result["error"] is None
    for key in data_access.MART_GLOBS:
        assert result[key] is None


def test_load_metrics_reads_warehouse_when_present(tmp_path, monkeypatch):
    warehouse = tmp_path / "warehouse.duckdb"
    conn = duckdb.connect(str(warehouse))
    try:
        conn.execute("CREATE TABLE device_metrics_daily AS SELECT 1 AS event_count")
    finally:
        conn.close()
    monkeypatch.setattr(data_access, "WAREHOUSE_DB_PATH", str(warehouse))

    result = data_access.load_metrics()
    assert result["source"] == "warehouse"
    assert result["daily"] is not None
    assert result["daily"]["event_count"].iloc[0] == 1


def test_load_metrics_falls_back_to_marts_when_warehouse_missing(tmp_path, monkeypatch):
    marts_glob = tmp_path / "marts" / "daily"
    marts_glob.mkdir(parents=True)
    df = pd.DataFrame({"device_id": ["d1"], "event_count": [5]})
    df.to_parquet(marts_glob / "part.parquet")

    fake_mart_globs = dict(data_access.MART_GLOBS)
    fake_mart_globs["daily"] = str(marts_glob / "**" / "*.parquet")
    monkeypatch.setattr(data_access, "MART_GLOBS", fake_mart_globs)

    result = data_access.load_metrics()
    assert result["source"] == "marts"
    assert result["daily"]["event_count"].iloc[0] == 5


def test_load_metrics_falls_back_to_staging_when_marts_missing(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging" / "event_date=2026-01-01"
    staging_dir.mkdir(parents=True)
    df = pd.DataFrame({
        "device_id": ["d1"],
        "device_name": ["Lamp"],
        "code": ["switch_1"],
        "value": ["true"],
        "event_time": [pd.Timestamp("2026-01-01 10:00:00")],
    })
    df.to_parquet(staging_dir / "part.parquet")
    monkeypatch.setattr(
        data_access, "STAGING_GLOB", str(tmp_path / "staging" / "**" / "*.parquet")
    )

    result = data_access.load_metrics()
    assert result["source"] == "staging (computed on the fly)"
    assert result["hourly"] is not None
    assert result["daily"] is None


# --- build_overview: empty-state ---


def test_build_overview_never_raises_with_no_data(tmp_path, monkeypatch):
    _write_device_mapping(tmp_path, monkeypatch, {"d1": "Lamp", "d2": "Fan"})

    payload = data_access.build_overview()

    assert payload["empty"] is True
    assert payload["empty_reason"]
    assert payload["source"] is None
    assert payload["latest_event"] is None
    assert payload["timeline"] == {"lanes": [], "intervals": []}
    assert payload["on_time"] == []
    assert payload["all_devices"] == ["Fan", "Lamp"]
    # devices list still has one entry per mapped device, state "unknown".
    assert [d["device_id"] for d in payload["devices"]] == ["d1", "d2"]
    assert all(d["state"] == "unknown" for d in payload["devices"])
    assert all(d["last_seen"] is None for d in payload["devices"])


# --- build_overview: regression test for the last_seen bug ---


def _seed_warehouse_with_clipped_intervals(tmp_path, monkeypatch):
    """Two devices whose final interval is clipped to the SAME global
    max(event_time) (mirroring gold_device_metrics' `_STATE_INTERVALS_QUERY`
    behaviour), but with genuinely different `device_metrics_daily.last_seen_at`
    values. If `last_seen` were read from interval_end, both devices would
    report the same timestamp."""
    warehouse = tmp_path / "warehouse.duckdb"
    conn = duckdb.connect(str(warehouse))
    try:
        clipped_end = pd.Timestamp("2026-09-06 22:51:24")
        conn.execute(
            """
            CREATE TABLE device_state_intervals AS SELECT * FROM (VALUES
                ('d1', 'Lamp', 'switch_1', TIMESTAMP '2026-09-06 17:00:00', ?, 231.4, true),
                ('d2', 'Fan',  'switch_1', TIMESTAMP '2026-09-06 18:00:00', ?, 171.4, true)
            ) t(device_id, device_name, switch_code, interval_start, interval_end,
                duration_minutes, is_on)
            """,
            [clipped_end, clipped_end],
        )
        conn.execute(
            """
            CREATE TABLE device_metrics_daily AS SELECT * FROM (VALUES
                ('d1', 'Lamp', DATE '2026-09-06', 10, TIMESTAMP '2026-09-06 17:10:00', 2),
                ('d2', 'Fan',  DATE '2026-09-06', 15, TIMESTAMP '2026-09-06 22:51:24', 3)
            ) t(device_id, device_name, event_day, event_count, last_seen_at, on_event_count)
            """
        )
        conn.execute(
            """
            CREATE TABLE device_on_time_daily AS SELECT * FROM (VALUES
                ('d1', 'Lamp', DATE '2026-09-06', 231.4, 1, 231.4, 0.0),
                ('d2', 'Fan',  DATE '2026-09-06', 171.4, 1, 171.4, 0.0)
            ) t(device_id, device_name, event_day, on_minutes, on_sessions,
                longest_session_minutes, overnight_on_minutes)
            """
        )
    finally:
        conn.close()
    monkeypatch.setattr(data_access, "WAREHOUSE_DB_PATH", str(warehouse))
    _write_device_mapping(tmp_path, monkeypatch, {"d1": "Lamp", "d2": "Fan"})


def test_build_overview_last_seen_comes_from_daily_not_clipped_interval_end(tmp_path, monkeypatch):
    _seed_warehouse_with_clipped_intervals(tmp_path, monkeypatch)

    payload = data_access.build_overview(days=None)
    by_id = {d["device_id"]: d for d in payload["devices"]}

    # Both devices share the same (clipped) interval_end...
    assert payload["source"] == "warehouse"
    # ...but last_seen must differ, taken from device_metrics_daily.last_seen_at.
    assert by_id["d1"]["last_seen"] == "2026-09-06T17:10:00"
    assert by_id["d2"]["last_seen"] == "2026-09-06T22:51:24"
    assert by_id["d1"]["last_seen"] != by_id["d2"]["last_seen"]

    # state still comes from the last interval's is_on.
    assert by_id["d1"]["state"] == "on"
    assert by_id["d2"]["state"] == "on"


# --- build_overview: device filtering ---


def test_build_overview_devices_filter_applies_to_timeline_and_on_time_not_all_devices(
    tmp_path, monkeypatch
):
    _seed_warehouse_with_clipped_intervals(tmp_path, monkeypatch)

    payload = data_access.build_overview(days=None, devices=["Lamp"])

    assert payload["all_devices"] == ["Fan", "Lamp"]  # unfiltered
    assert payload["timeline"]["lanes"] == ["Lamp"]
    assert {i["device"] for i in payload["timeline"]["intervals"]} == {"Lamp"}
    assert {e["device"] for e in payload["on_time"]} == {"Lamp"}
    # `devices` status list is also never filtered.
    assert {d["device_id"] for d in payload["devices"]} == {"d1", "d2"}


def test_build_overview_on_time_sorted_descending_and_has_label(tmp_path, monkeypatch):
    _seed_warehouse_with_clipped_intervals(tmp_path, monkeypatch)

    payload = data_access.build_overview(days=None)

    minutes = [entry["minutes"] for entry in payload["on_time"]]
    assert minutes == sorted(minutes, reverse=True)
    for entry in payload["on_time"]:
        assert "label" in entry and entry["label"]


# --- build_health ---


def test_build_health_never_raises_and_reports_shape():
    result = data_access.build_health()
    assert set(result) == {
        "data_source", "latest_event", "freshness_label",
        "provider", "provider_label", "model", "available", "guidance",
    }
    assert result["data_source"] is None
    assert result["available"] in (True, False)
