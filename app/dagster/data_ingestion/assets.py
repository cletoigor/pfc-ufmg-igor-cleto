"""
Dagster assets for ingesting Tuya device logs and processing them into a staging area.
"""
import os
import glob
import json
from datetime import datetime, timezone
import pandas as pd
import duckdb # Keep direct import for type hints if needed, resource provides connection
from dotenv import load_dotenv
from tuya_connector import TuyaOpenAPI
from dagster import (
    asset,
    AssetExecutionContext, # Added
    Definitions,
    ScheduleDefinition,
    define_asset_job,
    AssetIn, # Added
    Config, # Added
    EnvVar, # Added
)
from dagster_duckdb import DuckDBResource # Added

# Import helper functions from the utils module
from app.data_ingestion.ingestion_utils import (
    load_device_mapping,
    get_time_range_ms,
    get_device_supported_codes,
    fetch_status_logs,
)

# --- Configuration ---
# Ingestion Config
TIME_WINDOW_HOURS = 1
# Path relative to app dir for ingestion asset
DEFAULT_INGESTION_MAPPING_PATH = "device_mapping.json"
BASE_OUTPUT_DIR = "data/raw"  # Path relative to app dir for ingestion asset

# Processing Config
STAGING_DIR = "data/staging"  # Path relative to app dir for staging asset
# Path relative to app dir for processing asset
DEFAULT_PROCESSING_MAPPING_PATH = "device_mapping.json"

# --- Load Environment Variables ---
# Ensure .env file is in the 'app' directory or accessible from where Dagster runs
load_dotenv()

# --- Dagster Asset Definitions ---

# Use EnvVar for configuration from environment variables
class TuyaCredentials(Config):
    """Configuration for Tuya API credentials and mapping file path."""
    access_id: str = EnvVar("ACCESS_ID")
    access_secret: str = EnvVar("ACCESS_SECRET")
    api_endpoint: str = EnvVar("API_ENDPOINT")
    # Store relative path from env or default, resolve later
    device_mapping_path: str = os.getenv(
        "DEVICE_MAPPING_PATH", DEFAULT_INGESTION_MAPPING_PATH
    )


@asset(group_name="data_ingestion")
def raw_tuya_logs(context: AssetExecutionContext, config: TuyaCredentials) -> str:
    """
    Fetches device status logs from the Tuya Cloud API for configured devices
    and saves them as JSON files in a structured directory:
    data/raw/<device_id>/<YYYY-MM-DD>/<device_id>_<timestamp>_logs.json
    Returns the absolute base path where logs are saved.
    """
    context.log.info("Starting Tuya Log Ingestion Asset...")

    # Config object handles validation via EnvVar
    access_id = config.access_id
    access_secret = config.access_secret
    api_endpoint = config.api_endpoint
    # Resolve the mapping path relative to this script's directory
    script_dir = os.path.dirname(__file__)
    relative_mapping_path = config.device_mapping_path
    absolute_mapping_path = os.path.abspath(os.path.join(script_dir, relative_mapping_path))

    context.log.info(f"Using device mapping file: {absolute_mapping_path}")

    # Load device mapping using the correctly resolved absolute path
    device_mapping = load_device_mapping(absolute_mapping_path) # Use imported helper
    if not device_mapping:
        # Log error instead of raising immediately, allow asset to potentially proceed
        # if mapping isn't critical? Or raise as before if mapping is essential.
        # Let's keep raising for now. Wrapped long line.
        raise FileNotFoundError(
            f"Could not load device mapping from {absolute_mapping_path}"
        )

    device_ids = list(device_mapping.keys())
    if not device_ids:
        raise ValueError("No device IDs found in the mapping file.")

    context.log.info(f"Found {len(device_ids)} devices in mapping file.")

    # Calculate time range
    start_time_ms, end_time_ms = get_time_range_ms(TIME_WINDOW_HOURS) # Use imported helper

    # Initialize Tuya OpenAPI connector
    try:
        openapi = TuyaOpenAPI(api_endpoint, access_id, access_secret) # Use config values
        openapi.connect()
        context.log.info("Successfully connected to Tuya API.")
    except ConnectionError as e:
        context.log.error(f"Error connecting to Tuya API: {e}")
        raise ConnectionError(f"Error connecting to Tuya API: {e}") from e
    except Exception as e: # pylint: disable=broad-except # Catching general exception for unknown API issues
        context.log.error(f"An unexpected error occurred connecting to Tuya API: {e}")
        # Raise a more specific runtime error if possible, or keep generic with explanation
        raise RuntimeError(f"An unexpected error occurred connecting to Tuya API: {e}") from e


    # Fetch logs for each device
    all_device_logs = {}
    for device_id in device_ids:
        device_name = device_mapping.get(device_id, "Unknown Device")
        context.log.info("-" * 30)
        context.log.info(f"Processing: {device_name} ({device_id})")

        supported_codes = get_device_supported_codes(openapi, device_id) # Use imported helper

        if supported_codes is None:
            # Wrapped long line
            context.log.warning(
                f"  - Skipping log fetch for {device_id} due to error retrieving codes."
            )
            all_device_logs[device_id] = []
            continue
        if not supported_codes:
            # Wrapped long line
            context.log.warning(
                f"  - No supported codes found for {device_id}. Skipping log fetch."
            )
            all_device_logs[device_id] = []
            continue

        codes_str = ",".join(supported_codes) # Renamed variable

        logs = fetch_status_logs( # Use imported helper
            openapi,
            device_id,
            codes_str, # Use renamed variable
            start_time_ms,
            end_time_ms
        )
        all_device_logs[device_id] = logs

    context.log.info("-" * 30)
    context.log.info("Log ingestion fetch finished.")

    # --- Save logs to files ---
    # Ensure base directory exists, relative to this script's directory
    script_dir = os.path.dirname(__file__)
    absolute_base_output_dir = os.path.abspath(os.path.join(script_dir, BASE_OUTPUT_DIR))
    os.makedirs(absolute_base_output_dir, exist_ok=True)
    context.log.info(f"Base log directory: {absolute_base_output_dir}")

    ingestion_time_utc = datetime.now(timezone.utc).isoformat()
    ingested_by_identifier = "dagster_tuya_log_ingestion_asset" # Renamed variable
    context.log.info(f"Ingestion timestamp (UTC): {ingestion_time_utc}")

    saved_files_count = 0
    for device_id, logs in all_device_logs.items():
        if logs:
            try:
                processed_logs = []
                for log in logs:
                    log_copy = log.copy()
                    log_copy["device_id"] = device_id
                    log_copy["ingestion_timestamp_utc"] = ingestion_time_utc
                    log_copy["ingested_by"] = ingested_by_identifier # Use renamed variable
                    processed_logs.append(log_copy)

                # Determine output path based on first log entry's date
                first_log_time_ms = logs[0].get('event_time', 0)
                first_log_time_sec = first_log_time_ms / 1000
                dt_object = datetime.fromtimestamp(first_log_time_sec, timezone.utc)
                date_folder_str = dt_object.strftime('%Y-%m-%d')
                timestamp_str = dt_object.strftime('%Y%m%d%H%M%S')

                # Path: data/raw/<device_id>/<YYYY-MM-DD>/
                date_specific_output_dir = os.path.join(
                    absolute_base_output_dir, device_id, date_folder_str
                )
                os.makedirs(date_specific_output_dir, exist_ok=True)

                file_name = f"{device_id}_{timestamp_str}_logs.json"
                output_file_path = os.path.join(date_specific_output_dir, file_name)

                with open(output_file_path, 'w', encoding='utf-8') as f:
                    # Wrapped long line
                    json.dump(
                        processed_logs, f, indent=4, ensure_ascii=False
                    )
                # Create message string first to avoid long line
                save_message = (
                    f"  - Saved {len(processed_logs)} logs for {device_id} "
                    f"to {output_file_path}"
                )
                context.log.info(save_message)
                saved_files_count += 1
            except (IOError, TypeError, ValueError) as e: # Catch more specific errors
                context.log.error(f"  - Error processing or saving logs for {device_id}: {e}")
            except Exception as e: # pylint: disable=broad-except
                # Wrapped long line
                context.log.error(
                    f"  - Unexpected error processing/saving logs for {device_id}: {e}"
                )
        else:
            context.log.info(f"  - No logs to save for {device_id}.")

    context.log.info(f"Finished saving logs. Total files saved: {saved_files_count}")
    if saved_files_count == 0:
        context.log.warning("No log files were saved in this run.")

    # Return the absolute path to the base directory where logs were saved.
    # The downstream asset will need this to know where to look for input.
    return absolute_base_output_dir


@asset(
    ins={"raw_tuya_logs_path": AssetIn(key="raw_tuya_logs")}, # Declare dependency
    group_name="data_ingestion",
    required_resource_keys={"duckdb"}, # Declare resource requirement
)
def staging_tuya_logs(context: AssetExecutionContext, raw_tuya_logs_path: str) -> str:
    """
    Processes raw JSON logs from the raw_tuya_logs asset output directory
    into a partitioned Parquet dataset using DuckDB.

    Reads JSON files, enriches data (timestamp, filename, device_name),
    and saves partitioned Parquet to data/staging/, partitioned by event_date.
    Returns the absolute path to the staging directory.
    """
    context.log.info("Starting Raw-to-Staging Processing Asset...")
    context.log.info(f"Input raw logs directory: {raw_tuya_logs_path}")

    # Define paths relative to this script's directory
    script_dir = os.path.dirname(__file__)
    staging_dir_abs = os.path.abspath(os.path.join(script_dir, STAGING_DIR))
    device_mapping_path_abs = os.path.abspath(os.path.join(script_dir, DEFAULT_PROCESSING_MAPPING_PATH))
    os.makedirs(staging_dir_abs, exist_ok=True)
    context.log.info(f"Output staging directory: {staging_dir_abs}")
    context.log.info(f"Device mapping path: {device_mapping_path_abs}")

    # --- Load Device Mapping ---
    device_map_df = None
    try:
        # Use the correctly resolved absolute path
        with open(device_mapping_path_abs, 'r', encoding='utf-8') as f:
            device_mapping_dict = json.load(f)
        device_map_df = pd.DataFrame(
            list(device_mapping_dict.items()),
            columns=['device_id', 'device_name']
        )
        context.log.info(f"Successfully loaded device mapping from {device_mapping_path_abs}")
    except FileNotFoundError:
        # Wrapped long line
        context.log.error(
            f"Device mapping file not found at {device_mapping_path_abs}. "
            "Cannot add device names."
        )
    except json.JSONDecodeError:
        # Wrapped long line
        context.log.error(
            f"Could not decode JSON from {device_mapping_path_abs}. "
            "Cannot add device names."
        )
    except Exception as e: # pylint: disable=broad-except # Catch other potential errors during loading
        context.log.error(f"An unexpected error occurred loading device mapping: {e}")

    # Find all JSON files in the input directory structure
    raw_data_pattern = os.path.join(raw_tuya_logs_path, '**', '*.json')
    json_files = glob.glob(raw_data_pattern, recursive=True)

    if not json_files:
        context.log.warning(f"No JSON files found in {raw_tuya_logs_path}. Skipping processing.")
        # Still return the target staging dir path, even if empty
        return staging_dir_abs

    context.log.info(f"Found {len(json_files)} JSON files to process.")
    files_list_str = ', '.join([f"'{f}'" for f in json_files])

    # Get DuckDB connection from the resource
    duckdb_resource: DuckDBResource = context.resources.duckdb
    with duckdb_resource.get_connection() as conn:
        context.log.info("Acquired DuckDB connection from resource.")

        join_clause = ""
        select_device_name = "NULL AS device_name" # Default to NULL

        if device_map_df is not None:
            try:
                conn.register('device_map_view', device_map_df)
                context.log.info("Device mapping registered as DuckDB view 'device_map_view'.")
                join_clause = "LEFT JOIN device_map_view dm ON rl.device_id = dm.device_id"
                select_device_name = "dm.device_name"
            except Exception as e: # pylint: disable=broad-except # Catch potential DuckDB or other errors
                context.log.error(
                    f"Failed to register device map view: {e}. "
                    "Skipping device name enrichment."
                )
                # Reset join/select in case of registration error
                join_clause = ""
                select_device_name = "NULL AS device_name"
        else:
            context.log.warning("Skipping device name enrichment due to mapping load error.")

        copy_query = f"""
        COPY (
            WITH raw_logs AS (
                SELECT *
                FROM read_json_auto(
                    [{files_list_str}],
                    format='auto',
                    filename=true
                )
            )
            SELECT
                rl.code,
                rl.value,
                rl.device_id,
                rl.ingestion_timestamp_utc,
                rl.ingested_by,
                rl.filename,
                to_timestamp(rl.event_time / 1000)::TIMESTAMP AS event_time,
                {select_device_name},
                strftime(to_timestamp(rl.event_time / 1000), '%Y-%m-%d') AS event_date
            FROM raw_logs rl
            {join_clause}
        ) TO '{staging_dir_abs}' (
            FORMAT PARQUET,
            PARTITION_BY (event_date),
            OVERWRITE_OR_IGNORE 1
        );
        """

        try:
            context.log.info(f"Executing query:\n{copy_query}")
            conn.execute(copy_query)
            # Wrapped long line
            context.log.info(
                "Successfully processed raw data and saved partitioned Parquet files to "
                f"{staging_dir_abs}"
            )
        except duckdb.Error as e:
            context.log.error(f"A DuckDB error occurred during processing: {e}")
            raise # Re-raise the error to fail the asset run
        except Exception as e: # pylint: disable=broad-except # Catch other unexpected processing errors
            context.log.error(f"An unexpected error occurred during processing: {e}")
            raise # Re-raise the error

    return staging_dir_abs


# --- Job Definition ---
# Define a job that targets both assets
tuya_processing_job = define_asset_job(
    name="tuya_processing_job",
    selection=[raw_tuya_logs, staging_tuya_logs]
)

# --- Schedule Definition ---
# Define the hourly schedule for the job
hourly_schedule = ScheduleDefinition(
    job=tuya_processing_job,
    cron_schedule="0 * * * *",  # Every hour at minute 0
)

# --- Repository Definition ---
defs = Definitions(
    assets=[raw_tuya_logs, staging_tuya_logs],
    resources={
        # Configure the DuckDB resource (can be customized further)
        "duckdb": DuckDBResource(database=":memory:") # Use in-memory for now
    },
    jobs=[tuya_processing_job],
    schedules=[hourly_schedule],
)
