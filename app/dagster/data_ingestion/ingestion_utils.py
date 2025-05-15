import os
import json
from datetime import datetime, timedelta, timezone
from tuya_connector import TuyaOpenAPI # Keep import here as it's used by helpers

# --- Configuration (can be moved or passed as args if needed) ---
LOG_PAGE_SIZE = 100

# --- Helper Functions ---
def load_device_mapping(file_path):
    """Loads the device ID to name mapping from a JSON file."""
    try:
        # Ensure path is absolute or correctly relative to execution context
        abs_file_path = os.path.abspath(file_path)
        print(f"Attempting to load device mapping from: {abs_file_path}")
        with open(abs_file_path, 'r', encoding='utf-8') as mapping_file:
            mapping = json.load(mapping_file)
        print(f"Successfully loaded device mapping from {abs_file_path}")
        return mapping
    except FileNotFoundError:
        print(f"Error: Mapping file not found at {abs_file_path}")
        return None
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {abs_file_path}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred loading mapping file {abs_file_path}: {e}")
        return None


def get_device_supported_codes(openapi_client: TuyaOpenAPI, p_device_id: str):
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
    except Exception as e:
        print(f"  - An unexpected error occurred querying codes for {p_device_id}: {e}")
        return None


def get_time_range_ms(hours_ago: int):
    """Calculates the start and end time (in milliseconds) for a past time window."""
    now = datetime.now(timezone.utc)
    end_time = now
    start_time = now - timedelta(hours=hours_ago)
    _end_time_ms = int(end_time.timestamp() * 1000)
    _start_time_ms = int(start_time.timestamp() * 1000)
    print(f"Querying logs from {start_time} to {end_time} ({_start_time_ms}ms to {_end_time_ms}ms)")
    return _start_time_ms, _end_time_ms


def fetch_status_logs(
    openapi_client: TuyaOpenAPI,
    p_device_id: str,
    codes: str,
    p_start_time_ms: int,
    p_end_time_ms: int
):
    """Fetches specified device status logs from the Tuya API, handling pagination."""
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
            "size": LOG_PAGE_SIZE,
            "last_row_key": last_row_key
        }
        print(f"  - Requesting page {page_num} for codes '{codes}' (last_row_key: '{last_row_key}')...")
        try:
            response = openapi_client.get(endpoint, params)
        except ConnectionError as e:
             print(f"  - Connection error during log fetch for device {p_device_id}, page {page_num}: {e}")
             break # Exit loop on connection error during fetch
        except Exception as e:
             print(f"  - An unexpected error occurred during log fetch for {p_device_id}, page {page_num}: {e}")
             break

        if not response.get("success", False):
            print(f"  - Error fetching logs for device {p_device_id}: {response}")
            break # Exit loop on API error

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
            break

        page_num += 1

    print(f"Finished fetching logs for device {p_device_id}. Total logs: {len(all_logs)}")
    return all_logs
