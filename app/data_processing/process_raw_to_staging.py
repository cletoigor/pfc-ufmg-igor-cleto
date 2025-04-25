import duckdb
import os
import glob
import json
import pandas as pd # Import pandas

# Define paths
# Use os.path.join for better cross-platform compatibility
# Go up one level from data_processing to app, then down to data
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
raw_data_pattern = os.path.join(base_dir, 'data', 'raw', '**', '*.json')
staging_dir = os.path.join(base_dir, 'data', 'staging')
# Path to the device mapping file (relative to base_dir)
device_mapping_path = os.path.join(base_dir, 'data_ingestion', 'device_mapping.json')

# Ensure the staging directory exists
os.makedirs(staging_dir, exist_ok=True)

# --- Load Device Mapping ---
try:
    with open(device_mapping_path, 'r', encoding='utf-8') as f:
        device_mapping_dict = json.load(f)
    # Convert mapping dict to DataFrame for easier joining in DuckDB
    device_map_df = pd.DataFrame(list(device_mapping_dict.items()), columns=['device_id', 'device_name'])
    print(f"Successfully loaded device mapping from {device_mapping_path}")
except FileNotFoundError:
    print(f"Error: Device mapping file not found at {device_mapping_path}. Cannot add device names.")
    device_map_df = None # Set to None to handle gracefully later
except json.JSONDecodeError:
    print(f"Error: Could not decode JSON from {device_mapping_path}. Cannot add device names.")
    device_map_df = None
except Exception as e:
    print(f"An unexpected error occurred loading device mapping: {e}")
    device_map_df = None


# Find all JSON files matching the pattern recursively
json_files = glob.glob(raw_data_pattern, recursive=True)

if not json_files:
    print("No JSON files found in app/data/raw/. Exiting.")
    exit()

# Using an in-memory database
con = duckdb.connect(database=':memory:', read_only=False)

print(f"Found {len(json_files)} JSON files to process.")
print(f"Processing files: {json_files}") # Log the files being processed

try:
    files_list_str = ', '.join([f"'{f}'" for f in json_files])

    # Register the pandas DataFrame as a virtual table if it loaded successfully
    if device_map_df is not None:
        con.register('device_map_view', device_map_df)
        print("Device mapping registered as DuckDB view 'device_map_view'.")
        join_clause = "LEFT JOIN device_map_view dm ON rl.device_id = dm.device_id"
        select_device_name = "dm.device_name"
    else:
        # If mapping failed, create a dummy NULL column for device_name
        print("Skipping device name enrichment due to mapping load error.")
        join_clause = "" # No join needed
        select_device_name = "NULL AS device_name" # Select NULL

    # Construct the main query with CTE, join, and timestamp conversion
    # The WITH clause must be *inside* the COPY statement's subquery
    query = f"""
    COPY (
        WITH raw_logs AS (
            SELECT *
            FROM read_json_auto([{files_list_str}], format='auto', filename=true)
        )
        SELECT
            -- Explicitly list columns, excluding original event_time
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
    ) TO '{staging_dir}' (FORMAT PARQUET, PARTITION_BY (event_date), OVERWRITE_OR_IGNORE 1);
    """

    print(f"Executing query:\n{query}")
    con.execute(query)
    print(f"Successfully processed raw data and saved partitioned Parquet files to {staging_dir}")

except Exception as e:
    print(f"An error occurred during DuckDB processing: {e}")

finally:
    # Close the database connection
    con.close()
    print("Database connection closed.")
