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
CODES_TO_QUERY = "cur_current,cur_power,cur_voltage"
LOG_PAGE_SIZE = 100 # Max recommended by docs is 100
TIME_WINDOW_HOURS = 1

# --- Load Environment Variables ---
load_dotenv()
ACCESS_ID = os.getenv("ACCESS_ID")
ACCESS_SECRET = os.getenv("ACCESS_SECRET")
API_ENDPOINT = os.getenv("API_ENDPOINT")

# --- Helper Functions ---
def load_device_mapping(file_path):
    """Loads the device ID to name mapping from a JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
        print(f"Loaded device mapping from {file_path}")
        return mapping
    except FileNotFoundError:
        print(f"Error: Mapping file not found at {file_path}")
        return None
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {file_path}")
        return None

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
    codes,
    p_start_time_ms,
    p_end_time_ms
):
    """Fetches device status logs from the Tuya API, handling pagination."""
    all_logs = []
    last_row_key = ""
    page_num = 1

    print(f"Fetching logs for device {p_device_id}...")

    while True:
        endpoint = f"/v2.0/cloud/thing/{p_device_id}/report-logs"
        params = {
            "codes": codes,
            "start_time": p_start_time_ms,
            "end_time": p_end_time_ms,
            "size": LOG_PAGE_SIZE, # Use global constant
            "last_row_key": last_row_key
        }

        print(f"  - Requesting page {page_num} (last_row_key: '{last_row_key}')...")
        response = openapi_client.get(endpoint, params)

        if not response.get("success", False):
            print(f"  - Error fetching logs for device {p_device_id}: {response}")
            # Consider more robust error handling (e.g., retries, specific error codes)
            break # Exit loop on error

        result = response.get("result", {})
        page_logs = result.get("logs", []) # Renamed from 'logs'
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
        # Optional: Add a small delay between pages if needed
        # time.sleep(0.1)

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

        logs = fetch_status_logs(
            openapi,
            device_id,
            CODES_TO_QUERY,
            start_time_ms,
            end_time_ms
            # LOG_PAGE_SIZE is now used directly inside the function
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
                      f"Time: {readable_time} ({log.get('event_time')}ms)") # Line broken
        else:
            print(f"\nNo logs found for {device_name} ({device_id}) "
                  f"in the specified time range.") # Line broken

    print("-" * 30)
    print("Log ingestion process finished.")

    # Example: Further processing could happen here
    # e.g., save all_device_logs to a file, database, etc.
