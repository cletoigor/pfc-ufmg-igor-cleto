"""
Dagster Definitions for the Tuya IoT pipeline: assets, resources, jobs, and schedules.
"""
from dagster import Definitions, ScheduleDefinition, define_asset_job

from app.assets import gold_device_metrics, raw_tuya_logs, staging_tuya_logs
from app.resources import duckdb_resource

# --- Job Definition ---
# Define a job that targets the full asset graph: raw -> staging -> gold marts.
tuya_processing_job = define_asset_job(
    name="tuya_processing_job",
    selection=[raw_tuya_logs, staging_tuya_logs, gold_device_metrics],
)

# --- Schedule Definition ---
# Define the hourly schedule for the job
hourly_schedule = ScheduleDefinition(
    job=tuya_processing_job,
    cron_schedule="0 * * * *",  # Every hour at minute 0
)

# --- Repository Definition ---
defs = Definitions(
    assets=[raw_tuya_logs, staging_tuya_logs, gold_device_metrics],
    resources={
        "duckdb": duckdb_resource,
    },
    jobs=[tuya_processing_job],
    schedules=[hourly_schedule],
)
