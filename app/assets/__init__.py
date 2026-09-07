"""
Dagster asset definitions for the Tuya IoT pipeline.
"""
from app.assets.ingestion import raw_tuya_logs, staging_tuya_logs
from app.assets.energy_marts import gold_energy_metrics
from app.assets.marts import gold_device_metrics

__all__ = [
    "raw_tuya_logs",
    "staging_tuya_logs",
    "gold_device_metrics",
    "gold_energy_metrics",
]
