"""
Gold-layer mart assets: per-device rollups aggregated from the staging Parquet layer.
"""
import os

import duckdb
from dagster import AssetExecutionContext, asset
from dagster_duckdb import DuckDBResource

from app.assets.ingestion import STAGING_DIR

# Path relative to the app directory (mirrors app/assets/ingestion.py's STAGING_DIR).
MARTS_DIR = "data/marts"

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Staging stores `event_time` in UTC (it comes straight from Tuya's epoch-ms
# `event_time`). Every question a human asks of this data — "during work hours",
# "overnight", "what time do I turn the fan on" — means *local* wall-clock time,
# so the whole gold layer is expressed in the devices' local timezone. Brazil
# abolished DST in 2019, so the offset is a constant UTC-3 year-round and a plain
# interval shift is exact (no ICU/tz-database dependency needed).
LOCAL_UTC_OFFSET_HOURS = 3
_LOCAL_EVENT_TIME = f"(event_time - INTERVAL {LOCAL_UTC_OFFSET_HOURS} HOUR)"

# Shared aggregation logic for both granularities. `{bucket_expr}` buckets the
# local event time, `{bucket_alias}` names the output column. The "on-time"
# metric here is a simple proxy: the count of switch-like codes
# (`code ILIKE 'switch%'`) reporting a truthy value — a stand-in for "how many
# times this device was turned on". For actual durations, use the
# `device_state_intervals` / `device_on_time_daily` tables below.
_AGG_QUERY_TEMPLATE = """
SELECT
    device_id,
    device_name,
    {bucket_expr} AS {bucket_alias},
    count(*) AS event_count,
    max({local_event_time}) AS last_seen_at,
    count(*) FILTER (
        WHERE code ILIKE 'switch%' AND CAST(value AS VARCHAR) ILIKE 'true'
    ) AS on_event_count
FROM read_parquet('{staging_glob}', hive_partitioning = 1)
GROUP BY device_id, device_name, {bucket_alias}
ORDER BY device_id, {bucket_alias}
"""

# Turns the discrete switch-event stream into contiguous state intervals — the
# table that lets the agent (and the timeline chart) reason about *duration*
# rather than event counts.
#
# Three things this has to get right:
#   1. Consecutive duplicate readings. A device can report `true` twice in a row
#      (a re-affirmed state, not a new session); LAG(...) drops those, otherwise
#      they'd manufacture a zero-length interval and inflate the session count.
#   2. The trailing open interval. The final event has no successor, so it is
#      clipped to the last observed event time across the whole dataset rather
#      than left NULL (which would drop the device's current state entirely).
#   3. Sessions crossing midnight. Nothing special is done here — intervals are
#      stored whole, and `device_on_time_daily` below splits them per day.
_STATE_INTERVALS_QUERY = """
WITH switch_events AS (
    SELECT
        device_id,
        device_name,
        code AS switch_code,
        {local_event_time} AS event_time_local,
        CAST(value AS VARCHAR) ILIKE 'true' AS is_on
    FROM read_parquet('{staging_glob}', hive_partitioning = 1)
    WHERE code ILIKE 'switch%'
),
flagged AS (
    SELECT
        *,
        LAG(is_on) OVER (PARTITION BY device_id ORDER BY event_time_local) AS prev_is_on
    FROM switch_events
),
transitions AS (
    SELECT device_id, device_name, switch_code, event_time_local, is_on
    FROM flagged
    WHERE prev_is_on IS NULL OR prev_is_on <> is_on
),
bounded AS (
    SELECT
        device_id,
        device_name,
        -- The Tuya datapoint this device reports on/off through. It varies per
        -- device (switch_1 / switch_led / switch), and a control command has to
        -- address the right one, so it is carried through to the gold layer
        -- rather than assumed downstream.
        switch_code,
        is_on,
        event_time_local AS interval_start,
        COALESCE(
            LEAD(event_time_local) OVER (
                PARTITION BY device_id ORDER BY event_time_local
            ),
            (SELECT max(event_time_local) FROM switch_events)
        ) AS interval_end
    FROM transitions
)
SELECT
    device_id,
    device_name,
    switch_code,
    interval_start,
    interval_end,
    date_diff('second', interval_start, interval_end) / 60.0 AS duration_minutes,
    is_on
FROM bounded
-- `>=`, not `>`: the device that produced the newest event in the whole
-- dataset has its open trailing interval clipped to that very timestamp, so
-- the interval is zero-length. Dropping it would discard that device's
-- CURRENT state — a device that just switched on would be reported as off.
-- Duplicate readings are already removed by the LAG filter above, so this is
-- not a back door for the zero-length rows that filter exists to prevent.
WHERE interval_end >= interval_start
ORDER BY device_id, interval_start
"""

# Per-device, per-day on-time. Built from the ON intervals above, sliced at day
# boundaries so an overnight session contributes to both days it touches.
# `overnight_on_minutes` measures time spent on between 00:00 and 06:00 local —
# the "did I leave something running all night" signal.
_ON_TIME_DAILY_QUERY = """
WITH on_intervals AS (
    SELECT * FROM {intervals_table} WHERE is_on
),
day_spans AS (
    SELECT
        device_id,
        device_name,
        interval_start,
        interval_end,
        unnest(generate_series(
            date_trunc('day', interval_start),
            date_trunc('day', interval_end),
            INTERVAL 1 DAY
        )) AS event_day
    FROM on_intervals
),
slices AS (
    SELECT
        device_id,
        device_name,
        event_day,
        interval_start,
        interval_end,
        greatest(interval_start, event_day) AS slice_start,
        least(interval_end, event_day + INTERVAL 1 DAY) AS slice_end
    FROM day_spans
)
SELECT
    device_id,
    device_name,
    event_day,
    sum(date_diff('second', slice_start, slice_end)) / 60.0 AS on_minutes,
    count(*) FILTER (
        WHERE interval_start >= event_day AND interval_start < event_day + INTERVAL 1 DAY
    ) AS on_sessions,
    max(date_diff('second', interval_start, interval_end)) / 60.0
        AS longest_session_minutes,
    sum(greatest(0, date_diff(
        'second',
        greatest(slice_start, event_day),
        least(slice_end, event_day + INTERVAL 6 HOUR)
    ))) / 60.0 AS overnight_on_minutes
FROM slices
WHERE slice_end > slice_start
GROUP BY device_id, device_name, event_day
ORDER BY device_id, event_day
"""


@asset(
    # A `deps` edge rather than an `ins` input, for the same reason as
    # `staging_tuya_logs` — see the comment on that asset. The staging location
    # is a project convention (STAGING_DIR), so this asset can be rematerialized
    # on its own without the upstream having a stored output value to load.
    deps=["staging_tuya_logs"],
    group_name="data_marts",
    required_resource_keys={"duckdb"},
    kinds={"python", "duckdb"},
)
def gold_device_metrics(context: AssetExecutionContext) -> str:
    """
    Aggregates the staging Parquet layer into four per-device gold tables, all
    expressed in local wall-clock time (see LOCAL_UTC_OFFSET_HOURS):

      - device_metrics_hourly / device_metrics_daily — event counts, last-seen
        timestamp, and a switch-event "on" proxy per bucket.
      - device_state_intervals — contiguous on/off intervals with durations.
      - device_on_time_daily — per-day on-time, session counts, longest session
        and overnight (00:00-06:00) on-time.

    Writes Parquet to data/marts/{hourly,daily,state_intervals,on_time_daily}/
    and materializes the matching tables in the persistent DuckDB warehouse for
    downstream readers (the AI agent, the dashboard).
    """
    context.log.info("Starting Gold Device Metrics mart asset...")

    staging_path = os.path.abspath(os.path.join(_APP_DIR, STAGING_DIR))
    context.log.info(f"Input staging directory: {staging_path}")

    marts_dir_abs = os.path.abspath(os.path.join(_APP_DIR, MARTS_DIR))
    hourly_dir_abs = os.path.join(marts_dir_abs, "hourly")
    daily_dir_abs = os.path.join(marts_dir_abs, "daily")
    intervals_dir_abs = os.path.join(marts_dir_abs, "state_intervals")
    on_time_dir_abs = os.path.join(marts_dir_abs, "on_time_daily")
    for directory in (hourly_dir_abs, daily_dir_abs, intervals_dir_abs, on_time_dir_abs):
        os.makedirs(directory, exist_ok=True)

    staging_glob = os.path.join(staging_path, "**", "*.parquet")

    duckdb_resource: DuckDBResource = context.resources.duckdb
    with duckdb_resource.get_connection() as conn:
        context.log.info("Acquired DuckDB connection from resource.")

        for granularity, bucket_expr, bucket_alias, out_dir, table_name in (
            (
                "hourly",
                f"date_trunc('hour', {_LOCAL_EVENT_TIME})",
                "event_hour",
                hourly_dir_abs,
                "device_metrics_hourly",
            ),
            (
                "daily",
                f"date_trunc('day', {_LOCAL_EVENT_TIME})",
                "event_day",
                daily_dir_abs,
                "device_metrics_daily",
            ),
        ):
            agg_query = _AGG_QUERY_TEMPLATE.format(
                bucket_expr=bucket_expr,
                bucket_alias=bucket_alias,
                staging_glob=staging_glob,
                local_event_time=_LOCAL_EVENT_TIME,
            )

            try:
                context.log.info(f"Materializing {table_name} in warehouse.duckdb...")
                conn.execute(
                    f"CREATE OR REPLACE TABLE {table_name} AS {agg_query}"
                )

                row_count = conn.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]
                context.log.info(f"{table_name}: {row_count} rows.")

                partition_col = "event_hour" if granularity == "hourly" else "event_day"
                copy_query = f"""
                COPY (
                    SELECT *, strftime({partition_col}, '%Y-%m-%d') AS {partition_col}_date
                    FROM {table_name}
                ) TO '{out_dir}' (
                    FORMAT PARQUET,
                    PARTITION_BY ({partition_col}_date),
                    OVERWRITE_OR_IGNORE 1
                );
                """
                context.log.info(f"Writing {granularity} rollup Parquet to {out_dir}...")
                conn.execute(copy_query)
                context.log.info(f"Successfully wrote {granularity} rollup to {out_dir}.")
            except duckdb.Error as e:
                context.log.error(f"A DuckDB error occurred building {table_name}: {e}")
                raise
            except Exception as e:  # pylint: disable=broad-except
                context.log.error(f"An unexpected error occurred building {table_name}: {e}")
                raise

        # --- Duration-based marts -------------------------------------------
        # These are what let the agent answer "how long was X on" / "did I leave
        # anything running overnight" instead of only counting events.
        try:
            context.log.info("Materializing device_state_intervals in warehouse.duckdb...")
            conn.execute(
                "CREATE OR REPLACE TABLE device_state_intervals AS "
                + _STATE_INTERVALS_QUERY.format(
                    staging_glob=staging_glob,
                    local_event_time=_LOCAL_EVENT_TIME,
                )
            )
            interval_count = conn.execute(
                "SELECT count(*) FROM device_state_intervals"
            ).fetchone()[0]
            context.log.info(f"device_state_intervals: {interval_count} rows.")

            context.log.info("Materializing device_on_time_daily in warehouse.duckdb...")
            conn.execute(
                "CREATE OR REPLACE TABLE device_on_time_daily AS "
                + _ON_TIME_DAILY_QUERY.format(intervals_table="device_state_intervals")
            )
            on_time_count = conn.execute(
                "SELECT count(*) FROM device_on_time_daily"
            ).fetchone()[0]
            context.log.info(f"device_on_time_daily: {on_time_count} rows.")

            for table_name, partition_col, out_dir in (
                ("device_state_intervals", "interval_start", intervals_dir_abs),
                ("device_on_time_daily", "event_day", on_time_dir_abs),
            ):
                context.log.info(f"Writing {table_name} Parquet to {out_dir}...")
                conn.execute(
                    f"""
                    COPY (
                        SELECT *, strftime({partition_col}, '%Y-%m-%d') AS {partition_col}_date
                        FROM {table_name}
                    ) TO '{out_dir}' (
                        FORMAT PARQUET,
                        PARTITION_BY ({partition_col}_date),
                        OVERWRITE_OR_IGNORE 1
                    );
                    """
                )
                context.log.info(f"Successfully wrote {table_name} to {out_dir}.")
        except duckdb.Error as e:
            context.log.error(f"A DuckDB error occurred building the duration marts: {e}")
            raise
        except Exception as e:  # pylint: disable=broad-except
            context.log.error(f"An unexpected error occurred building the duration marts: {e}")
            raise

    context.log.info("Gold Device Metrics mart asset finished.")
    return marts_dir_abs
