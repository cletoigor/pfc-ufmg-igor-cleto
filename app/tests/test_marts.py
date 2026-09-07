"""
Tests for app/assets/marts.py.

`gold_device_metrics` is tightly coupled to a Dagster `AssetExecutionContext`
and a `DuckDBResource` connection, so rather than invoking the asset function
directly we exercise the same aggregation SQL template
(`_AGG_QUERY_TEMPLATE`) it uses, against a tiny hand-built staging Parquet
fixture written with duckdb/pandas in a tmp dir. This validates the actual
aggregation logic (grouping, event counts, on_event_count) without needing a
live Dagster run. We additionally do a light smoke check that the asset
object itself is importable and looks like a Dagster asset.
"""
import os

import duckdb
import pandas as pd
import pytest

from app.assets.marts import (
    _AGG_QUERY_TEMPLATE,
    _LOCAL_EVENT_TIME,
    _ON_TIME_DAILY_QUERY,
    _STATE_INTERVALS_QUERY,
    LOCAL_UTC_OFFSET_HOURS,
    gold_device_metrics,
)


@pytest.fixture
def staging_fixture(tmp_path):
    """Writes a tiny partitioned staging Parquet dataset mirroring the shape
    produced by staging_tuya_logs (device_id, device_name, code, value,
    event_time, event_date partition column)."""
    rows = [
        # device-1: two "on" switch events + one non-switch event, same hour.
        {
            "device_id": "device-1",
            "device_name": "Living Room Lamp",
            "code": "switch_1",
            "value": "true",
            "event_time": pd.Timestamp("2026-01-01 10:15:00"),
            "event_date": "2026-01-01",
        },
        {
            "device_id": "device-1",
            "device_name": "Living Room Lamp",
            "code": "switch_1",
            "value": "true",
            "event_time": pd.Timestamp("2026-01-01 10:45:00"),
            "event_date": "2026-01-01",
        },
        {
            "device_id": "device-1",
            "device_name": "Living Room Lamp",
            "code": "temperature",
            "value": "21",
            "event_time": pd.Timestamp("2026-01-01 10:50:00"),
            "event_date": "2026-01-01",
        },
        # device-1, different hour, same day.
        {
            "device_id": "device-1",
            "device_name": "Living Room Lamp",
            "code": "switch_1",
            "value": "false",
            "event_time": pd.Timestamp("2026-01-01 14:00:00"),
            "event_date": "2026-01-01",
        },
        # device-2: one event, different day.
        {
            "device_id": "device-2",
            "device_name": "Bedroom Fan",
            "code": "switch_1",
            "value": "true",
            "event_time": pd.Timestamp("2026-01-02 08:00:00"),
            "event_date": "2026-01-02",
        },
    ]
    df = pd.DataFrame(rows)

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()

    conn = duckdb.connect(database=":memory:")
    try:
        conn.register("staging_df", df)
        conn.execute(
            f"""
            COPY staging_df TO '{staging_dir}' (
                FORMAT PARQUET,
                PARTITION_BY (event_date),
                OVERWRITE_OR_IGNORE 1
            )
            """
        )
    finally:
        conn.close()

    return staging_dir


def _run_agg(staging_dir, granularity):
    bucket_expr, bucket_alias = {
        "hourly": (f"date_trunc('hour', {_LOCAL_EVENT_TIME})", "event_hour"),
        "daily": (f"date_trunc('day', {_LOCAL_EVENT_TIME})", "event_day"),
    }[granularity]

    staging_glob = os.path.join(str(staging_dir), "**", "*.parquet")
    query = _AGG_QUERY_TEMPLATE.format(
        bucket_expr=bucket_expr,
        bucket_alias=bucket_alias,
        staging_glob=staging_glob,
        local_event_time=_LOCAL_EVENT_TIME,
    )

    conn = duckdb.connect(database=":memory:")
    try:
        return conn.execute(query).fetchdf()
    finally:
        conn.close()


def _local(utc_timestamp: str) -> pd.Timestamp:
    """The local-time bucket a UTC staging timestamp lands in."""
    return pd.Timestamp(utc_timestamp) - pd.Timedelta(hours=LOCAL_UTC_OFFSET_HOURS)


def test_agg_query_hourly_groups_and_counts(staging_fixture):
    result = _run_agg(staging_fixture, "hourly")

    device_1_rows = result[result["device_id"] == "device-1"]
    # Two distinct hours for device-1: 10:xx and 14:xx UTC.
    assert len(device_1_rows) == 2

    hour_10 = device_1_rows[
        device_1_rows["event_hour"] == _local("2026-01-01 10:00:00")
    ].iloc[0]
    assert hour_10["event_count"] == 3
    # Only the two "true" switch_1 events count as on-events.
    assert hour_10["on_event_count"] == 2

    hour_14 = device_1_rows[
        device_1_rows["event_hour"] == _local("2026-01-01 14:00:00")
    ].iloc[0]
    assert hour_14["event_count"] == 1
    assert hour_14["on_event_count"] == 0


def test_agg_query_converts_staging_utc_to_local(staging_fixture):
    """Staging is UTC by contract; every gold bucket is local wall-clock."""
    result = _run_agg(staging_fixture, "hourly")

    device_1_hours = set(result[result["device_id"] == "device-1"]["event_hour"])
    assert device_1_hours == {
        _local("2026-01-01 10:00:00"),
        _local("2026-01-01 14:00:00"),
    }
    # Sanity: the shift actually happened, i.e. these are not the raw UTC hours.
    assert pd.Timestamp("2026-01-01 10:00:00") not in device_1_hours


def test_agg_query_daily_per_device_counts(staging_fixture):
    result = _run_agg(staging_fixture, "daily")

    assert set(result["device_id"]) == {"device-1", "device-2"}

    device_1 = result[result["device_id"] == "device-1"].iloc[0]
    assert device_1["event_count"] == 4
    assert device_1["on_event_count"] == 2
    assert device_1["device_name"] == "Living Room Lamp"

    device_2 = result[result["device_id"] == "device-2"].iloc[0]
    assert device_2["event_count"] == 1
    assert device_2["on_event_count"] == 1
    assert device_2["device_name"] == "Bedroom Fan"


# --- duration marts: device_state_intervals / device_on_time_daily ---


@pytest.fixture
def intervals_staging(tmp_path):
    """Staging fixture (UTC) exercising the tricky cases for the interval mart:
    a duplicate `true` reading, a session crossing midnight, and a device whose
    final event leaves its state open."""
    def row(device_id, name, code, value, ts):
        return {
            "device_id": device_id,
            "device_name": name,
            "code": code,
            "value": value,
            "event_time": pd.Timestamp(ts),
            "event_date": ts[:10],
        }

    # Times are UTC; the mart shifts them by -LOCAL_UTC_OFFSET_HOURS. Chosen so
    # the local-time results land on round numbers (UTC 12:00 -> local 09:00).
    rows = [
        # lamp: on 09:00 local, a redundant repeat "on" at 09:30, off at 11:00.
        row("lamp", "Lamp", "switch_led", "true", "2026-03-02 12:00:00"),
        row("lamp", "Lamp", "switch_led", "true", "2026-03-02 12:30:00"),
        row("lamp", "Lamp", "switch_led", "false", "2026-03-02 14:00:00"),
        # lamp: on 23:00 local, off 02:00 local next day (crosses midnight).
        row("lamp", "Lamp", "switch_led", "true", "2026-03-03 02:00:00"),
        row("lamp", "Lamp", "switch_led", "false", "2026-03-03 05:00:00"),
        # fan: turns on and never reports again — open trailing interval.
        row("fan", "Fan", "switch", "true", "2026-03-03 03:00:00"),
        # A non-switch reading, which must be ignored entirely.
        row("fan", "Fan", "bright_value", "80", "2026-03-03 03:30:00"),
    ]

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    conn = duckdb.connect(database=":memory:")
    try:
        conn.register("staging_df", pd.DataFrame(rows))
        conn.execute(
            f"""
            COPY staging_df TO '{staging_dir}' (
                FORMAT PARQUET, PARTITION_BY (event_date), OVERWRITE_OR_IGNORE 1
            )
            """
        )
    finally:
        conn.close()
    return staging_dir


def _run_duration_marts(staging_dir):
    """Builds both duration marts the way the asset does, returning both frames."""
    staging_glob = os.path.join(str(staging_dir), "**", "*.parquet")
    conn = duckdb.connect(database=":memory:")
    try:
        conn.execute(
            "CREATE TABLE device_state_intervals AS "
            + _STATE_INTERVALS_QUERY.format(
                staging_glob=staging_glob, local_event_time=_LOCAL_EVENT_TIME
            )
        )
        conn.execute(
            "CREATE TABLE device_on_time_daily AS "
            + _ON_TIME_DAILY_QUERY.format(intervals_table="device_state_intervals")
        )
        return (
            conn.execute("SELECT * FROM device_state_intervals").fetchdf(),
            conn.execute("SELECT * FROM device_on_time_daily").fetchdf(),
        )
    finally:
        conn.close()


def test_state_intervals_drops_repeated_same_state_readings(intervals_staging):
    intervals, _ = _run_duration_marts(intervals_staging)

    lamp = intervals[intervals["device_id"] == "lamp"].sort_values("interval_start")
    first_on = lamp[lamp["is_on"]].iloc[0]

    # The redundant 09:30 "true" must not split the session or create a
    # zero-length interval: one ON stretch from 09:00 to 11:00 local.
    assert first_on["interval_start"] == pd.Timestamp("2026-03-02 09:00:00")
    assert first_on["interval_end"] == pd.Timestamp("2026-03-02 11:00:00")
    assert first_on["duration_minutes"] == 120

    # Only the trailing interval of the device holding the newest event may be
    # zero-length (see test_state_intervals_keeps_the_current_state_of_the_
    # newest_device); a duplicate reading must never manufacture one.
    latest = intervals["interval_end"].max()
    spurious = intervals[
        (intervals["duration_minutes"] <= 0) & (intervals["interval_start"] != latest)
    ]
    assert spurious.empty


def test_state_intervals_keeps_the_current_state_of_the_newest_device(intervals_staging):
    """Regression: the device that produced the newest event in the dataset has
    its open interval clipped to that same timestamp, making it zero-length. It
    must survive, or that device's current state is silently lost — a device
    that just switched on would be reported as off."""
    intervals, _ = _run_duration_marts(intervals_staging)

    # The lamp's final event (02:00 local on the 3rd) is the newest switch event
    # in the fixture, so its trailing interval is zero-length.
    lamp = intervals[intervals["device_id"] == "lamp"].sort_values("interval_start")
    trailing = lamp.iloc[-1]

    assert trailing["interval_start"] == trailing["interval_end"]
    assert trailing["duration_minutes"] == 0
    # It carries the state the device is actually in right now.
    assert bool(trailing["is_on"]) is False


def test_state_intervals_ignores_non_switch_codes_and_clips_open_interval(
    intervals_staging,
):
    intervals, _ = _run_duration_marts(intervals_staging)

    fan = intervals[intervals["device_id"] == "fan"]
    # The bright_value reading is not a state change, so the fan has exactly one
    # interval: its trailing ON, clipped to the last switch event in the dataset
    # (the lamp's 02:00 local "false") rather than left NULL.
    assert len(fan) == 1
    assert bool(fan.iloc[0]["is_on"]) is True
    assert fan.iloc[0]["interval_start"] == pd.Timestamp("2026-03-03 00:00:00")
    assert pd.notna(fan.iloc[0]["interval_end"])


def test_on_time_daily_splits_overnight_session_across_days(intervals_staging):
    _, on_time = _run_duration_marts(intervals_staging)

    lamp = on_time[on_time["device_id"] == "lamp"].set_index("event_day")

    # 09:00-11:00 on the 2nd, plus 23:00-00:00 of the overnight session.
    day_2 = lamp.loc[pd.Timestamp("2026-03-02")]
    assert day_2["on_minutes"] == 180
    assert day_2["on_sessions"] == 2
    # The overnight stretch is the longest single session (23:00 -> 02:00).
    assert day_2["longest_session_minutes"] == 180
    assert day_2["overnight_on_minutes"] == 0

    # The remainder of the overnight session lands on the 3rd: 00:00-02:00,
    # all of it inside the 00:00-06:00 overnight window.
    day_3 = lamp.loc[pd.Timestamp("2026-03-03")]
    assert day_3["on_minutes"] == 120
    assert day_3["overnight_on_minutes"] == 120
    # The session started the previous day, so it is not counted again here.
    assert day_3["on_sessions"] == 0


def test_gold_device_metrics_asset_is_importable_dagster_asset():
    # Limitation: gold_device_metrics itself requires a Dagster
    # AssetExecutionContext + a DuckDBResource connection (staging_path input,
    # context.resources.duckdb), which is impractical to fully fake in a unit
    # test. We only assert it's wired up as a Dagster asset with the expected
    # name/dependency, and rely on the aggregation-SQL tests above (which use
    # the exact same _AGG_QUERY_TEMPLATE) to validate the actual logic.
    assert gold_device_metrics.key.to_user_string() == "gold_device_metrics"
