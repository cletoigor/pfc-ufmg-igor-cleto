"""
Processes raw JSON logs from Tuya devices into a partitioned Parquet dataset.

Reads JSON files from the `../data/raw/` directory structure, enriches the data
by converting the event timestamp, adding the source filename, and looking up
the device name from a mapping file. The final dataset is saved in the
`../data/staging/` directory, partitioned by event date.
"""
import os
import glob
import json
import sys

import duckdb
import pandas as pd

# --- Constants ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DATA_PATTERN = os.path.join(BASE_DIR, 'data', 'raw', '**', '*.json')
STAGING_DIR = os.path.join(BASE_DIR, 'data', 'staging')
DEVICE_MAPPING_PATH = os.path.join(BASE_DIR, 'data_ingestion', 'device_mapping.json')

os.makedirs(STAGING_DIR, exist_ok=True)

# --- Load Device Mapping ---
device_map_df = None # pylint: disable=invalid-name
try:
    with open(DEVICE_MAPPING_PATH, 'r', encoding='utf-8') as f:
        device_mapping_dict = json.load(f)
    # Convert mapping dict to DataFrame for easier joining in DuckDB
    device_map_df = pd.DataFrame(
        list(device_mapping_dict.items()),
        columns=['device_id', 'device_name']
    )
    print(f"Successfully loaded device mapping from {DEVICE_MAPPING_PATH}")
except FileNotFoundError:
    print(f"Error: Device mapping file not found at {DEVICE_MAPPING_PATH}. "
          "Cannot add device names.")
except json.JSONDecodeError:
    print(f"Error: Could not decode JSON from {DEVICE_MAPPING_PATH}. "
          "Cannot add device names.")
except Exception as e: # pylint: disable=broad-except # Catch other potential errors during loading/conversion
    print(f"An unexpected error occurred loading device mapping: {e}")


# Find all JSON files matching the pattern recursively
# Use snake_case for this list variable
json_files = glob.glob(RAW_DATA_PATTERN, recursive=True)

if not json_files:
    print("No JSON files found in app/data/raw/. Exiting.")
    sys.exit() # Use sys.exit() for clarity

# Using an in-memory database
db_connection = None # pylint: disable=invalid-name
try:
    db_connection = duckdb.connect(database=':memory:', read_only=False)

    print(f"Found {len(json_files)} JSON files to process.")
    # Break long print statement
    print("Processing files:")
    for file_path in json_files:
        print(f"  - {file_path}")
    files_list_str = ', '.join([f"'{f}'" for f in json_files]) # pylint: disable=invalid-name

    join_clause = "" # pylint: disable=invalid-name
    select_device_name = "NULL AS device_name" # pylint: disable=invalid-name # Default to NULL

    if device_map_df is not None:
        db_connection.register('device_map_view', device_map_df)
        print("Device mapping registered as DuckDB view 'device_map_view'.")
        join_clause = "LEFT JOIN device_map_view dm ON rl.device_id = dm.device_id" # pylint: disable=invalid-name
        select_device_name = "dm.device_name" # pylint: disable=invalid-name
    else:
        print("Skipping device name enrichment due to mapping load error.")

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
            -- Calculate and alias the new timestamp as event_time
            to_timestamp(rl.event_time / 1000)::TIMESTAMP AS event_time,
            {select_device_name}, -- Select device_name from join or NULL
            -- Keep event_date for partitioning (calculated from original event_time)
            strftime(to_timestamp(rl.event_time / 1000), '%Y-%m-%d') AS event_date
        FROM raw_logs rl
        {join_clause} -- Add the join clause (or empty string if no mapping)
    ) TO '{STAGING_DIR}' (
        FORMAT PARQUET,
        PARTITION_BY (event_date),
        OVERWRITE_OR_IGNORE 1
    );
    """

    print(f"Executing query:\n{copy_query}")
    db_connection.execute(copy_query)
    print("Successfully processed raw data and saved partitioned Parquet files to "
          f"{STAGING_DIR}")

except duckdb.Error as e: # Catch specific DuckDB errors
    print(f"A DuckDB error occurred during processing: {e}")
except Exception as e: # pylint: disable=broad-except # Catch any other unexpected errors during processing
    print(f"An unexpected error occurred during processing: {e}")

finally:
    # Close the database connection if it was opened
    if db_connection:
        db_connection.close()
        print("Database connection closed.")
