"""
Fetches device status logs from the Tuya Cloud API.

This script connects to the Tuya API using credentials stored in environment
variables, reads a list of device IDs from a mapping file, and retrieves
specified status logs (e.g., current, power, voltage) for each device
within a defined recent time window. The fetched logs are then printed.
"""
import os
import json
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from tuya_connector import TuyaOpenAPI

# --- Configuration ---
LOG_PAGE_SIZE = 100 # Max recommended by docs is 100
TIME_WINDOW_HOURS = 168

# --- Load Environment Variables ---
load_dotenv()
ACCESS_ID = os.getenv("ACCESS_ID")
ACCESS_SECRET = os.getenv("ACCESS_SECRET")
API_ENDPOINT = os.getenv("API_ENDPOINT")

# --- Helper Functions ---
def load_device_mapping(file_path):
    """Loads the device ID to name mapping from a JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as mapping_file:
            mapping = json.load(mapping_file)
        print(f"Loaded device mapping from {file_path}")
        return mapping
    except FileNotFoundError:
        print(f"Error: Mapping file not found at {file_path}")
        return None
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {file_path}")
        return None

def get_device_supported_codes(openapi_client, p_device_id):
    """Queries the Tuya API to get the list of supported status codes for a device."""
    print(f"  - Querying supported codes for device {p_device_id}...")
    endpoint = f"/v2.0/cloud/thing/{p_device_id}/shadow/properties"
    try:
        response = openapi_client.get(endpoint)
        if response.get("success", False):
            properties = response.get("result", {}).get("properties", [])
            codes = [prop.get("code") for prop in properties if prop.get("code")]
            if codes:
                print(f"  - Found supported codes: {', '.join(codes)}")
                return codes
            else:
                print(f"  - No supported codes found in API response for {p_device_id}.")
                return []
        else:
            print(f"  - Error querying codes for device {p_device_id}: {response}")
            return None # Indicate error
    except ConnectionError as e: # More specific exception
        print(f"  - Connection error querying codes for device {p_device_id}: {e}")
        return None # Indicate error


def get_time_range_ms(hours_ago):
    """Calculates the start and end time (in milliseconds) for a past time window."""
    now = datetime.now(timezone.utc)
    end_time = now
    start_time = now - timedelta(hours=hours_ago)
    # Convert to milliseconds timestamp
    _end_time_ms = int(end_time.timestamp() * 1000)
    _start_time_ms = int(start_time.timestamp() * 1000)
    print(f"Querying logs from {start_time} to {end_time} ({_start_time_ms}ms to {_end_time_ms}ms)")
    return _start_time_ms, _end_time_ms

def fetch_status_logs(
    openapi_client,
    p_device_id,
    codes, # Re-added: Now expects comma-separated string of codes
    p_start_time_ms,
    p_end_time_ms
):
    """Fetches specified device status logs from the Tuya API, handling pagination."""
    all_logs = []
    last_row_key = ""
    page_num = 1

    print(f"Fetching logs for device {p_device_id}...")

    while True:
        endpoint = f"/v2.0/cloud/thing/{p_device_id}/report-logs"
        params = {
            "codes": codes, # Use the provided codes string
            "start_time": p_start_time_ms,
            "end_time": p_end_time_ms,
            "size": LOG_PAGE_SIZE, # Use global constant
            "last_row_key": last_row_key
        }

        print(f"  - Requesting page {page_num} for codes '{codes}' "
              f"(last_row_key: '{last_row_key}')...")
        response = openapi_client.get(endpoint, params)

        if not response.get("success", False):
            print(f"  - Error fetching logs for device {p_device_id}: {response}")
            break # Exit loop on error

        result = response.get("result", {})
        page_logs = result.get("logs", [])
        has_more = result.get("has_more", False)
        last_row_key = result.get("last_row_key", "")

        if page_logs:
            print(f"  - Received {len(page_logs)} logs on page {page_num}.")
            all_logs.extend(page_logs)
        else:
            print(f"  - Received 0 logs on page {page_num}.")


        if not has_more or not last_row_key:
            print(f"  - No more pages for device {p_device_id}.")
            break # Exit loop if no more pages

        page_num += 1

    print(f"Finished fetching logs for device {p_device_id}. Total logs: {len(all_logs)}")
    return all_logs

# --- Main Execution ---
if __name__ == "__main__":
    print("Starting Tuya Log Ingestion Script...")

    # Validate environment variables
    if not all([ACCESS_ID, ACCESS_SECRET, API_ENDPOINT]):
        print("Error: Missing required environment variables "
              "(ACCESS_ID, ACCESS_SECRET, API_ENDPOINT).")
        print("Please ensure they are set in your .env file.")
        exit(1)

    # Determine device mapping file path
    DEFAULT_MAPPING_PATH = "./device_mapping.json"
    mapping_file_path = os.getenv("DEVICE_MAPPING_PATH", DEFAULT_MAPPING_PATH)
    print(f"Using device mapping file: {mapping_file_path}")

    # Load device mapping
    device_mapping = load_device_mapping(mapping_file_path)
    if not device_mapping:
        exit(1)

    device_ids = list(device_mapping.keys())
    if not device_ids:
        print("Error: No device IDs found in the mapping file.")
        exit(1)

    print(f"Found {len(device_ids)} devices in mapping file.")

    # Calculate time range
    start_time_ms, end_time_ms = get_time_range_ms(TIME_WINDOW_HOURS)

    # Initialize Tuya OpenAPI connector
    try:
        openapi = TuyaOpenAPI(API_ENDPOINT, ACCESS_ID, ACCESS_SECRET)
        openapi.connect()
        print("Successfully connected to Tuya API.")
    except ConnectionError as e: # Changed from Exception
        print(f"Error connecting to Tuya API: {e}")
        exit(1)

    # Fetch logs for each device
    all_device_logs = {}
    for device_id in device_ids:
        device_name = device_mapping.get(device_id, "Unknown Device")
        print("-" * 30)
        print(f"Processing: {device_name} ({device_id})")

        # Get supported codes for this device
        supported_codes = get_device_supported_codes(openapi, device_id)

        if supported_codes is None: # API error querying codes
            print(f"  - Skipping log fetch for {device_id} due to error retrieving codes.")
            all_device_logs[device_id] = [] # Ensure key exists but is empty
            continue # Move to the next device
        if not supported_codes: # Empty list, no codes found/supported
            print(f"  - No supported codes found for {device_id}. Skipping log fetch.")
            all_device_logs[device_id] = []
            continue

        CODES_STR = ",".join(supported_codes)

        logs = fetch_status_logs(
            openapi,
            device_id,
            CODES_STR, # Pass the dynamically fetched codes
            start_time_ms,
            end_time_ms
        )
        all_device_logs[device_id] = logs

        # Print fetched logs (or process/store them)
        if logs:
            print(f"\nLogs for {device_name} ({device_id}):")
            for log in logs:
                # Convert timestamp for readability
                event_time_sec = log.get('event_time', 0) / 1000
                readable_time = datetime.fromtimestamp(event_time_sec, timezone.utc).isoformat()
                print(f"  - Code: {log.get('code')}, Value: {log.get('value')}, "
                      f"Time: {readable_time} ({log.get('event_time')}ms)")
        else:
            print(f"\nNo logs found for {device_name} ({device_id}) "
                  f"in the specified time range.")

    print("-" * 30)
    print("Log ingestion process finished.")

    # --- Save logs to files ---
    base_output_dir = os.path.join("..", "data", "raw") # Base directory for all logs
    os.makedirs(base_output_dir, exist_ok=True) # Ensure base directory exists
    print(f"Base log directory: {os.path.abspath(base_output_dir)}")

    # Get current time once for the ingestion timestamp
    ingestion_time_utc = datetime.now(timezone.utc).isoformat()
    INGESTED_BY_IDENTIFIER = "tuya_log_ingestion_script" # Renamed to conform to UPPER_CASE
    print(f"Ingestion timestamp (UTC): {ingestion_time_utc}")

    for device_id, logs in all_device_logs.items():
        if logs: # Only save if logs were fetched
            try:
                # Add ingestion metadata to each log record
                processed_logs = []
                for log in logs:
                    log_copy = log.copy() # Avoid modifying the original dict if needed elsewhere
                    log_copy["device_id"] = device_id # Add the device_id to the log record
                    log_copy["ingestion_timestamp_utc"] = ingestion_time_utc
                    log_copy["ingested_by"] = INGESTED_BY_IDENTIFIER # Use renamed constant
                    processed_logs.append(log_copy)

                # Get timestamp and date components from the first log entry
                first_log_time_ms = logs[0].get('event_time', 0)
                first_log_time_sec = first_log_time_ms / 1000
                dt_object = datetime.fromtimestamp(first_log_time_sec, timezone.utc)
                date_folder_str = dt_object.strftime('%Y-%m-%d') # Format YYYY-MM-DD for folder name
                timestamp_str = dt_object.strftime('%Y%m%d%H%M%S') # For filename

                # Create nested device-specific and date-specific directory
                # Structure: ../data/raw/DEVICE_ID/YYYY-MM-DD/
                date_specific_output_dir = os.path.join(
                    base_output_dir, device_id, date_folder_str # Use single date folder name
                )
                os.makedirs(date_specific_output_dir, exist_ok=True)

                # Construct filename and full path
                FILE_NAME = f"{device_id}_{timestamp_str}_logs.json"
                output_file_path = os.path.join(date_specific_output_dir, FILE_NAME)

                # Save the processed logs (with metadata)
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    json.dump(processed_logs, f, indent=4, ensure_ascii=False)
                print(f"  - Saved {len(processed_logs)} logs for {device_id} to {output_file_path}")
            except (
                IOError,
                IndexError,
                KeyError,
                AttributeError,
                TypeError
            ) as e: # Catch potential errors
                print(f"  - Error processing or saving logs for {device_id}: {e}")
        else:
            print(f"  - No logs to save for {device_id}.")

    print("Finished saving logs.")
