# Active Context: Data Pipeline Setup & TCC Monografia

## 1. Current Focus

-   Setting up a data pipeline to process raw JSON logs into a staging Parquet file using DuckDB.
-   Updating project documentation (Memory Bank) to reflect the new data processing components.

## 2. Recent Changes

-   Updated `.clineignore` to allow access to `memory-bank/`.
-   Read all core Memory Bank files.
-   Added `duckdb` dependency to `app/requirements.txt`.
-   Created `app/data_processing/` directory.
-   Updated `app/data_ingestion/tuya_log_ingestion.py` to add `device_id` field to each raw log record.
-   Created `app/data_processing/` directory.
-   Added `pandas` dependency to `app/requirements.txt`.
-   Updated `app/data_processing/process_raw_to_staging.py` script to:
    -   Read raw JSON logs (including `device_id`).
    -   Add a `filename` column.
    -   Replace `event_time` (ms) with a readable timestamp format (aliased as `event_time`).
    -   Load `device_mapping.json` and join to add a `device_name` column.
    -   Derive an `event_date` (from original ms timestamp) for partitioning.
    -   Output daily partitioned Parquet files.
-   Created `app/data/staging/` directory.
-   Removed the old single `staging_logs.parquet` file.
-   Successfully installed dependencies and re-ran the processing script, generating partitioned Parquet files in `app/data/staging/` with the final schema (including replaced `event_time`, `device_id`, `filename`, `device_name`).

## 3. Next Steps

-   Update `memory-bank/systemPatterns.md` to reflect the final staging schema (replaced `event_time`) and partitioning.
-   Update `memory-bank/techContext.md` to reflect the final transformations.
-   Update `memory-bank/progress.md` to reflect the completed pipeline enhancements.
-   Continue work on the TCC Monografia LaTeX content as needed.
-   Define further steps for utilizing the staged data (e.g., analysis, visualization).

## 4. Active Decisions & Considerations

-   The `device_id` is now included directly within the raw JSON data during ingestion.
-   The data pipeline processing script (`process_raw_to_staging.py`) reads raw JSON, adds `filename`, replaces `event_time` with a readable timestamp, looks up `device_name` from `device_mapping.json` (loaded via pandas into DuckDB), derives `event_date`, and uses `PARTITION_BY(event_date)`.
-   The staging layer in `app/data/staging/` consists of partitioned Parquet files. Each file contains original fields (except ms `event_time`) plus `device_id`, `filename`, the readable `event_time`, and `device_name`.
-   Memory Bank files are being updated to reflect the final implementation.
