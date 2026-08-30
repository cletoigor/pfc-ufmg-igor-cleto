"""
Gold-layer mart assets: per-device rollups aggregated from the staging Parquet layer.
"""
import os

import duckdb
from dagster import AssetExecutionContext, AssetIn, asset
from dagster_duckdb import DuckDBResource

# Path relative to the app directory (mirrors app/assets/ingestion.py's STAGING_DIR).
MARTS_DIR = "data/marts"

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Shared aggregation logic for both granularities. `{bucket_expr}` buckets event_time,
# `{bucket_alias}` names the output column. The "on-time" metric is a simple proxy:
# the count of switch-like codes (`code ILIKE 'switch%'`) reporting a truthy value —
# a stand-in for "how many times this device was turned on" given the source data is
# discrete state-change events rather than continuous duration samples.
_AGG_QUERY_TEMPLATE = """
SELECT
    device_id,
    device_name,
    {bucket_expr} AS {bucket_alias},
    count(*) AS event_count,
    max(event_time) AS last_seen_at,
    count(*) FILTER (
        WHERE code ILIKE 'switch%' AND CAST(value AS VARCHAR) ILIKE 'true'
    ) AS on_event_count
FROM read_parquet('{staging_glob}', hive_partitioning = 1)
GROUP BY device_id, device_name, {bucket_alias}
ORDER BY device_id, {bucket_alias}
"""


@asset(
    ins={"staging_path": AssetIn(key="staging_tuya_logs")},
    group_name="data_marts",
    required_resource_keys={"duckdb"},
)
def gold_device_metrics(context: AssetExecutionContext, staging_path: str) -> str:
    """
    Aggregates the staging Parquet layer into per-device hourly and daily rollups
    (event counts, last-seen timestamp, and a simple on-time/usage proxy per
    device_name). Writes Parquet to data/marts/{hourly,daily}/ and materializes
    `device_metrics_hourly` / `device_metrics_daily` tables in the persistent
    DuckDB warehouse for downstream readers (the AI agent, the dashboard).
    """
    context.log.info("Starting Gold Device Metrics mart asset...")

    marts_dir_abs = os.path.abspath(os.path.join(_APP_DIR, MARTS_DIR))
    hourly_dir_abs = os.path.join(marts_dir_abs, "hourly")
    daily_dir_abs = os.path.join(marts_dir_abs, "daily")
    os.makedirs(hourly_dir_abs, exist_ok=True)
    os.makedirs(daily_dir_abs, exist_ok=True)

    staging_glob = os.path.join(staging_path, "**", "*.parquet")

    duckdb_resource: DuckDBResource = context.resources.duckdb
    with duckdb_resource.get_connection() as conn:
        context.log.info("Acquired DuckDB connection from resource.")

        for granularity, bucket_expr, bucket_alias, out_dir, table_name in (
            (
                "hourly",
                "date_trunc('hour', event_time)",
                "event_hour",
                hourly_dir_abs,
                "device_metrics_hourly",
            ),
            (
                "daily",
                "date_trunc('day', event_time)",
                "event_day",
                daily_dir_abs,
                "device_metrics_daily",
            ),
        ):
            agg_query = _AGG_QUERY_TEMPLATE.format(
                bucket_expr=bucket_expr,
                bucket_alias=bucket_alias,
                staging_glob=staging_glob,
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

    context.log.info("Gold Device Metrics mart asset finished.")
    return marts_dir_abs
