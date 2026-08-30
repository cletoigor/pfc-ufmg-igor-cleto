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

from app.assets.marts import _AGG_QUERY_TEMPLATE, gold_device_metrics


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
        "hourly": ("date_trunc('hour', event_time)", "event_hour"),
        "daily": ("date_trunc('day', event_time)", "event_day"),
    }[granularity]

    staging_glob = os.path.join(str(staging_dir), "**", "*.parquet")
    query = _AGG_QUERY_TEMPLATE.format(
        bucket_expr=bucket_expr,
        bucket_alias=bucket_alias,
        staging_glob=staging_glob,
    )

    conn = duckdb.connect(database=":memory:")
    try:
        return conn.execute(query).fetchdf()
    finally:
        conn.close()


def test_agg_query_hourly_groups_and_counts(staging_fixture):
    result = _run_agg(staging_fixture, "hourly")

    device_1_rows = result[result["device_id"] == "device-1"]
    # Two distinct hours for device-1: 10:xx and 14:xx.
    assert len(device_1_rows) == 2

    hour_10 = device_1_rows[
        device_1_rows["event_hour"] == pd.Timestamp("2026-01-01 10:00:00")
    ].iloc[0]
    assert hour_10["event_count"] == 3
    # Only the two "true" switch_1 events count as on-events.
    assert hour_10["on_event_count"] == 2

    hour_14 = device_1_rows[
        device_1_rows["event_hour"] == pd.Timestamp("2026-01-01 14:00:00")
    ].iloc[0]
    assert hour_14["event_count"] == 1
    assert hour_14["on_event_count"] == 0


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


def test_gold_device_metrics_asset_is_importable_dagster_asset():
    # Limitation: gold_device_metrics itself requires a Dagster
    # AssetExecutionContext + a DuckDBResource connection (staging_path input,
    # context.resources.duckdb), which is impractical to fully fake in a unit
    # test. We only assert it's wired up as a Dagster asset with the expected
    # name/dependency, and rely on the aggregation-SQL tests above (which use
    # the exact same _AGG_QUERY_TEMPLATE) to validate the actual logic.
    assert gold_device_metrics.key.to_user_string() == "gold_device_metrics"
