"""
Gold-layer energy marts: the electrical side of the warehouse.

`gold_device_metrics` (app/assets/marts.py) models *when* devices were on.
This asset models *how much they drew* while they were — the `cur_power`,
`cur_voltage` and `cur_current` datapoints the BL0937-based plugs report — and
derives the 24-channel Phase I baseline the CUSUM page monitors against.

It is a separate asset from `gold_device_metrics` on purpose: the two mart
families read the same staging layer but have no dependency on each other, so
either can be rematerialized alone and a schema problem in one does not block
the other.
"""
import os

import duckdb
from dagster import AssetExecutionContext, asset
from dagster_duckdb import DuckDBResource

from app.assets.ingestion import STAGING_DIR
from app.assets.marts import MARTS_DIR, _LOCAL_EVENT_TIME

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Tuya's scale factors for this chipset: power and voltage arrive in tenths,
# current already in milliamps.
POWER_SCALE = 10.0
VOLTAGE_SCALE = 10.0

# How long a single reading is taken to represent.
#
# The plugs report every 15 minutes while drawing current and stop reporting
# entirely when off, so the gap between two consecutive readings is either the
# sampling interval or the whole off-period. Holding a reading for at most one
# sampling interval is what keeps the integration from drawing a phantom line
# across an off-period: a device that was on for one hour at 18:00 and off
# until noon the next day must not be charged for the 18 hours in between.
MAX_SAMPLE_HOLD_MINUTES = 15

# Days at the end of the window held out of the Phase I baseline. The baseline
# is meant to describe the process *before* the period under test; letting the
# monitored days set their own control limits would mask exactly the drift the
# chart exists to find.
BASELINE_HOLDOUT_DAYS = 7

# One row per reading of a single electrical datapoint, in local time.
_READINGS_CTE = """
readings AS (
    SELECT
        device_id,
        device_name,
        code,
        {local_event_time} AS sample_time,
        CAST(value AS DOUBLE) AS raw_value
    FROM read_parquet('{staging_glob}', hive_partitioning = 1)
    WHERE code IN ('cur_power', 'cur_voltage', 'cur_current')
      AND TRY_CAST(value AS DOUBLE) IS NOT NULL
)
"""

# Energy by zero-order hold: each power reading is taken to hold until the next
# one, capped at MAX_SAMPLE_HOLD_MINUTES (see above). A held segment can straddle
# an hour boundary — the hold is shorter than an hour, so it spans at most two —
# and is split so each hour is charged only for the minutes that actually fall
# inside it. Charging the whole segment to the reading's own hour would be
# simpler but would smear energy across the hourly CUSUM channels.
_ENERGY_HOURLY_QUERY = """
WITH {readings_cte},
power AS (
    SELECT device_id, device_name, sample_time, raw_value / {power_scale} AS power_w
    FROM readings WHERE code = 'cur_power'
),
held AS (
    SELECT
        device_id,
        device_name,
        sample_time,
        power_w,
        least(
            coalesce(
                lead(sample_time) OVER (PARTITION BY device_id ORDER BY sample_time),
                sample_time + INTERVAL {hold} MINUTE
            ),
            sample_time + INTERVAL {hold} MINUTE
        ) AS hold_end
    FROM power
),
segments AS (
    -- the part of the hold that falls in the reading's own hour
    SELECT
        device_id, device_name, power_w,
        date_trunc('hour', sample_time) AS event_hour,
        sample_time AS seg_start,
        least(hold_end, date_trunc('hour', sample_time) + INTERVAL 1 HOUR) AS seg_end
    FROM held
    UNION ALL
    -- the spill into the next hour, when the hold crosses the boundary
    SELECT
        device_id, device_name, power_w,
        date_trunc('hour', hold_end) AS event_hour,
        date_trunc('hour', hold_end) AS seg_start,
        hold_end AS seg_end
    FROM held
    WHERE date_trunc('hour', hold_end) > date_trunc('hour', sample_time)
),
energy AS (
    SELECT
        device_id,
        device_name,
        event_hour,
        sum(power_w * date_diff('second', seg_start, seg_end) / 3600.0) / 1000.0 AS energy_kwh
    FROM segments
    WHERE seg_end > seg_start
    GROUP BY device_id, device_name, event_hour
),
stats AS (
    SELECT
        device_id,
        device_name,
        date_trunc('hour', sample_time) AS event_hour,
        count(*) FILTER (WHERE code = 'cur_power') AS sample_count,
        avg(raw_value / {power_scale}) FILTER (WHERE code = 'cur_power') AS power_w_mean,
        max(raw_value / {power_scale}) FILTER (WHERE code = 'cur_power') AS power_w_max,
        min(raw_value / {power_scale}) FILTER (WHERE code = 'cur_power') AS power_w_min,
        avg(raw_value / {voltage_scale}) FILTER (WHERE code = 'cur_voltage') AS voltage_v_mean,
        max(raw_value / {voltage_scale}) FILTER (WHERE code = 'cur_voltage') AS voltage_v_max,
        min(raw_value / {voltage_scale}) FILTER (WHERE code = 'cur_voltage') AS voltage_v_min,
        avg(raw_value) FILTER (WHERE code = 'cur_current') AS current_ma_mean,
        max(raw_value) FILTER (WHERE code = 'cur_current') AS current_ma_max,
        min(raw_value) FILTER (WHERE code = 'cur_current') AS current_ma_min
    FROM readings
    GROUP BY device_id, device_name, event_hour
)
SELECT
    stats.device_id,
    stats.device_name,
    stats.event_hour,
    stats.sample_count,
    stats.power_w_mean,
    stats.power_w_max,
    stats.power_w_min,
    stats.voltage_v_mean,
    stats.voltage_v_max,
    stats.voltage_v_min,
    stats.current_ma_mean,
    stats.current_ma_max,
    stats.current_ma_min,
    coalesce(energy.energy_kwh, 0.0) AS energy_kwh
FROM stats
LEFT JOIN energy USING (device_id, device_name, event_hour)
ORDER BY stats.device_id, stats.event_hour
"""

# Daily rollup. Energy sums; power statistics are re-derived from the hourly
# means rather than averaged naively, and the peak carries the hour it happened
# in so the "power peaks" panel can point at a time.
_ENERGY_DAILY_QUERY = """
WITH hourly AS (SELECT * FROM {hourly_table}),
peaks AS (
    SELECT device_id, date_trunc('day', event_hour) AS event_day, event_hour AS peak_hour,
           power_w_max,
           row_number() OVER (
               PARTITION BY device_id, date_trunc('day', event_hour)
               ORDER BY power_w_max DESC, event_hour
           ) AS rn
    FROM hourly
)
SELECT
    hourly.device_id,
    hourly.device_name,
    date_trunc('day', hourly.event_hour) AS event_day,
    sum(hourly.energy_kwh) AS energy_kwh,
    sum(hourly.sample_count) AS sample_count,
    avg(hourly.power_w_mean) AS power_w_mean,
    max(hourly.power_w_max) AS power_w_max,
    min(hourly.power_w_min) AS power_w_min,
    avg(hourly.voltage_v_mean) AS voltage_v_mean,
    max(hourly.voltage_v_max) AS voltage_v_max,
    min(hourly.voltage_v_min) AS voltage_v_min,
    avg(hourly.current_ma_mean) AS current_ma_mean,
    max(hourly.current_ma_max) AS current_ma_max,
    min(hourly.current_ma_min) AS current_ma_min,
    any_value(peaks.peak_hour) AS peak_hour
FROM hourly
LEFT JOIN peaks
    ON peaks.device_id = hourly.device_id
   AND peaks.event_day = date_trunc('day', hourly.event_hour)
   AND peaks.rn = 1
GROUP BY hourly.device_id, hourly.device_name, date_trunc('day', hourly.event_hour)
ORDER BY hourly.device_id, event_day
"""

# Phase I of the CUSUM scheme (monograph section 3.3.2). The multichannel
# structure is daily-periodic at one-hour resolution, so a device gets 24
# channels and each hour of the day is characterised only by that same hour on
# other days: 03:00 is compared with 03:00, never with 19:00.
#
# The monitored variable is energy per hour, as the monograph specifies. sigma0
# is the *sample* standard deviation — DuckDB's stddev_samp, the m-1 denominator
# of equation 3.2 — not the population form, which would understate the spread
# and manufacture false alarms.
_CUSUM_BASELINE_QUERY = """
WITH bounded AS (
    SELECT *, max(event_hour) OVER () AS latest_hour FROM {hourly_table}
)
SELECT
    device_id,
    device_name,
    CAST(extract('hour' FROM event_hour) AS INTEGER) AS hour_of_day,
    avg(energy_kwh) AS mu0,
    stddev_samp(energy_kwh) AS sigma0,
    count(*) AS n_obs
FROM bounded
WHERE event_hour < date_trunc('day', latest_hour) - INTERVAL {holdout} DAY
GROUP BY device_id, device_name, hour_of_day
ORDER BY device_id, hour_of_day
"""


@asset(
    # `deps` rather than `ins`, for the same reason as the other mart asset:
    # the staging location is a project convention, so this can be rebuilt on
    # its own without the upstream having a stored output to load.
    deps=["staging_tuya_logs"],
    group_name="data_marts",
    required_resource_keys={"duckdb"},
    kinds={"python", "duckdb"},
)
def gold_energy_metrics(context: AssetExecutionContext) -> str:
    """
    Aggregates the electrical datapoints in staging into three gold tables, all
    in local wall-clock time (see LOCAL_UTC_OFFSET_HOURS in app/assets/marts.py):

      - device_power_hourly — per device-hour: power/voltage/current statistics
        and energy in kWh.
      - device_power_daily — the same rolled up per day, plus the day's peak.
      - device_cusum_baseline — per device and hour-of-day, the Phase I mean and
        sample standard deviation of hourly energy.

    Writes Parquet to data/marts/{power_hourly,power_daily,cusum_baseline}/ and
    materializes the matching tables in the persistent DuckDB warehouse.
    """
    context.log.info("Starting Gold Energy Metrics mart asset...")

    staging_path = os.path.abspath(os.path.join(_APP_DIR, STAGING_DIR))
    marts_dir_abs = os.path.abspath(os.path.join(_APP_DIR, MARTS_DIR))
    power_hourly_dir = os.path.join(marts_dir_abs, "power_hourly")
    power_daily_dir = os.path.join(marts_dir_abs, "power_daily")
    baseline_dir = os.path.join(marts_dir_abs, "cusum_baseline")
    for directory in (power_hourly_dir, power_daily_dir, baseline_dir):
        os.makedirs(directory, exist_ok=True)

    staging_glob = os.path.join(staging_path, "**", "*.parquet")
    readings_cte = _READINGS_CTE.format(
        staging_glob=staging_glob, local_event_time=_LOCAL_EVENT_TIME
    ).strip()

    duckdb_resource: DuckDBResource = context.resources.duckdb
    with duckdb_resource.get_connection() as conn:
        try:
            context.log.info("Materializing device_power_hourly in warehouse.duckdb...")
            conn.execute(
                "CREATE OR REPLACE TABLE device_power_hourly AS "
                + _ENERGY_HOURLY_QUERY.format(
                    readings_cte=readings_cte,
                    power_scale=POWER_SCALE,
                    voltage_scale=VOLTAGE_SCALE,
                    hold=MAX_SAMPLE_HOLD_MINUTES,
                )
            )
            hourly_rows = conn.execute("SELECT count(*) FROM device_power_hourly").fetchone()[0]
            context.log.info(f"device_power_hourly: {hourly_rows} rows.")

            if hourly_rows == 0:
                # No electrical datapoints in staging at all. The downstream
                # tables would be empty anyway; say so loudly rather than
                # leaving three empty tables that look like a silent failure.
                context.log.warning(
                    "No cur_power/cur_voltage/cur_current readings found in staging — "
                    "the energy marts will be empty. Re-run scripts/seed_synthetic_data.py "
                    "if this is the demo dataset."
                )

            context.log.info("Materializing device_power_daily in warehouse.duckdb...")
            conn.execute(
                "CREATE OR REPLACE TABLE device_power_daily AS "
                + _ENERGY_DAILY_QUERY.format(hourly_table="device_power_hourly")
            )
            daily_rows = conn.execute("SELECT count(*) FROM device_power_daily").fetchone()[0]
            context.log.info(f"device_power_daily: {daily_rows} rows.")

            context.log.info("Materializing device_cusum_baseline in warehouse.duckdb...")
            conn.execute(
                "CREATE OR REPLACE TABLE device_cusum_baseline AS "
                + _CUSUM_BASELINE_QUERY.format(
                    hourly_table="device_power_hourly", holdout=BASELINE_HOLDOUT_DAYS
                )
            )
            baseline_rows = conn.execute(
                "SELECT count(*) FROM device_cusum_baseline"
            ).fetchone()[0]
            context.log.info(f"device_cusum_baseline: {baseline_rows} rows.")

            for table_name, partition_col, out_dir in (
                ("device_power_hourly", "event_hour", power_hourly_dir),
                ("device_power_daily", "event_day", power_daily_dir),
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

            # The baseline is 24 rows per device and has no time axis to
            # partition on, so it is written as a single file.
            context.log.info(f"Writing device_cusum_baseline Parquet to {baseline_dir}...")
            conn.execute(
                "COPY (SELECT * FROM device_cusum_baseline) TO "
                f"'{os.path.join(baseline_dir, 'baseline.parquet')}' (FORMAT PARQUET);"
            )
        except duckdb.Error as e:
            context.log.error(f"A DuckDB error occurred building the energy marts: {e}")
            raise
        except Exception as e:  # pylint: disable=broad-except
            context.log.error(f"An unexpected error occurred building the energy marts: {e}")
            raise

    context.log.info("Gold Energy Metrics mart asset finished.")
    return marts_dir_abs
