# Active Context: Dagster Orchestration Setup & TCC Monografia

## 1. Current Focus

-   Implementing Dagster to orchestrate the existing Tuya data ingestion and processing pipeline.
-   Refactoring Python scripts into Dagster assets.
-   Setting up an hourly schedule for the pipeline.
-   Updating project documentation (Memory Bank) to reflect the Dagster implementation.

## 2. Recent Changes

-   Added Dagster dependencies (`dagster`, `dagster-duckdb`, `dagster-webserver`) to `app/requirements.txt`.
-   Created `app/data_ingestion/ingestion_utils.py` and moved helper functions from the original ingestion script into it.
-   Created `app/assets.py` containing:
    -   `raw_tuya_logs` asset: Refactored from `app/data_ingestion/tuya_log_ingestion.py`, uses helpers from `ingestion_utils.py`, configured via `TuyaCredentials` Config class (using EnvVar). Returns the absolute path to the raw data output directory (`data/raw/`).
    -   `staging_tuya_logs` asset: Refactored from `app/data_processing/process_raw_to_staging.py`, depends on `raw_tuya_logs`, uses `DuckDBResource` (configured for in-memory DB), loads device mapping, processes raw JSONs, and writes partitioned Parquet to `data/staging/`. Returns the absolute path to the staging directory.
    -   `tuya_processing_job`: A job definition targeting both assets.
    -   `hourly_schedule`: A `ScheduleDefinition` targeting `tuya_processing_job` with a cron schedule of `0 * * * *`.
    -   `defs`: A `Definitions` object containing assets, resources (DuckDB), job, and schedule.
-   Created `dagster.yaml` (using default instance storage settings).
-   Created `workspace.yaml` pointing to `app/assets.py`.
-   *Previous changes related to the standalone scripts (adding device_id, partitioning, etc.) are now part of the asset logic.*

## 3. Next Steps

-   Update `memory-bank/systemPatterns.md` to reflect the Dagster orchestration pattern.
-   Update `memory-bank/techContext.md` to include Dagster and related packages.
-   Update `memory-bank/progress.md` to reflect the completed Dagster setup.
-   Start the Dagster UI (`dagster dev`) to visualize assets and schedules.
-   Verify the hourly schedule is active and runs successfully.
-   Consider configuring persistent storage for Dagster instance in `dagster.yaml` if needed beyond local testing.
-   Consider configuring the DuckDB resource to use a file-based database instead of in-memory if persistence is required between runs or for external querying.
-   Continue work on the TCC Monografia LaTeX content as needed.

## 4. Active Decisions & Considerations

-   The data pipeline is now orchestrated by Dagster.
-   The ingestion and processing steps are defined as separate assets (`raw_tuya_logs`, `staging_tuya_logs`) with an explicit dependency.
-   Helper functions for ingestion are kept separate in `app/data_ingestion/ingestion_utils.py`.
-   The pipeline is scheduled to run hourly via `ScheduleDefinition`.
-   Tuya API credentials and mapping file path for ingestion are configured via a Dagster `Config` object using `EnvVar`.
-   The processing asset uses the `dagster-duckdb` integration and `DuckDBResource` (currently configured for in-memory).
-   Dagster instance configuration (`dagster.yaml`) uses defaults (likely `~/.dagster`).
-   `workspace.yaml` points Dagster to the code location in `app/assets.py`.
