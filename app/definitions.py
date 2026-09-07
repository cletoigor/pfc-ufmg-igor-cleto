"""
Dagster Definitions for the Tuya IoT pipeline: assets, resources, jobs, and schedules.
"""
from dagster import Definitions, ScheduleDefinition, define_asset_job

from app.assets import (
    gold_device_metrics,
    gold_energy_metrics,
    raw_tuya_logs,
    staging_tuya_logs,
)
from app.resources import duckdb_resource
from app.scenes.scheduler import scene_execution_schedule, scene_scheduler_job

# --- Job Definition ---
# Define a job that targets the full asset graph: raw -> staging -> gold marts.
tuya_processing_job = define_asset_job(
    name="tuya_processing_job",
    selection=[raw_tuya_logs, staging_tuya_logs, gold_device_metrics, gold_energy_metrics],
)

# --- Schedule Definition ---
# Define the hourly schedule for the job
hourly_schedule = ScheduleDefinition(
    job=tuya_processing_job,
    cron_schedule="0 * * * *",  # Every hour at minute 0
)

# --- Scene automation ---
# `scene_scheduler_job` checks app/data/scheduled_scenes.json every minute and
# fires whatever is due (see app/scenes/scheduler.py). It only runs while the
# Dagster daemon is up, and it is dry-run unless SCENE_EXECUTION_DRY_RUN=0.

# --- Repository Definition ---
defs = Definitions(
    assets=[raw_tuya_logs, staging_tuya_logs, gold_device_metrics, gold_energy_metrics],
    resources={
        "duckdb": duckdb_resource,
    },
    jobs=[tuya_processing_job, scene_scheduler_job],
    schedules=[hourly_schedule, scene_execution_schedule],
)
