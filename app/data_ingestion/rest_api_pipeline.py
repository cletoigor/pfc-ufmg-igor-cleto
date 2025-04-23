"""
This module defines a dlt pipeline for ingesting data from the Tuya REST API.

It includes:
- Custom authentication class for Tuya's HMAC-SHA256 signature.
- A dlt source definition (`tuya_source`) with resources for:
    - Fetching device properties (`device_properties`).
    - Fetching device status reporting logs (`status_reporting_log`) incrementally,
      using device properties to determine which status codes ('codes') to query.
- A helper function (`load_tuya`) to configure and run the pipeline.
"""
import hmac
import hashlib
import time
from typing import List, Iterator
import requests
from requests.auth import AuthBase # Import AuthBase from requests

import dlt
from dlt.common.pendulum import pendulum
from dlt.common.typing import TDataItem

from dlt.sources.rest_api import (
    RESTAPIConfig,
    rest_api_resources,
)
# --- Tuya Authentication ---
# Based on Tuya documentation for HMAC SHA256 signing
# https://developer.tuya.com/en/docs/iot/singnature?id=Ka43a5mtx1gsc
class TuyaAuth(AuthBase): # Inherit from requests.auth.AuthBase
    """
    Custom authentication class for Tuya API using HMAC-SHA256 signature.

    Implements the AuthConfigBase interface for dlt's REST API source.
    Calculates the required signature based on Tuya's specification.
    """
    def __init__(
        self,
        access_id: str,
        access_secret: str,
    ):
        self.access_id = access_id
        self.access_secret = access_secret

    def __call__(
        self, request: requests.PreparedRequest
    ) -> requests.PreparedRequest: # Changed type hint
        timestamp = str(int(time.time() * 1000))
        headers = {
            "client_id": self.access_id,
            "t": timestamp,
            "sign_method": "HMAC-SHA256",
        }

        # Prepare signature string
        method = request.method.upper()
        # Get path relative to base_url
        url_without_query = request.url.split("?")[0]
        url_path = url_without_query.replace(request.base_url, "")
        # Calculate SHA256 hash of the request body (or empty bytes if no body)
        request_body = request.data or b""
        content_sha256 = hashlib.sha256(request_body).hexdigest()
        headers_string = ""
        string_to_sign = f"{method}\n"
        string_to_sign += f"{content_sha256}\n"
        string_to_sign += f"{headers_string}\n"
        string_to_sign += f"{url_path}"

        # Calculate signature
        sign = hmac.new(
            self.access_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()

        headers["sign"] = sign

        # Update request headers
        request.headers.update(headers)

        return request


# --- Helper to extract and join codes ---
def resolve_codes(item: TDataItem, source_resource_name: str) -> str:
    """
    Extracts 'code' from each property in the parent resource ('device_properties')
    and joins them into a comma-separated string for the 'codes' parameter.
    """
    if not item or source_resource_name != "device_properties":
        return "" # Should not happen if dependency is set correctly

    # Assuming item is the list of properties from the parent resource result
    # Filter for specific codes requested by the user
    allowed_codes = {"cur_current", "cur_voltage", "cur_power"}
    codes = [prop.get("code") for prop in item if prop.get("code") in allowed_codes]
    return ",".join(codes)

# --- Tuya Source ---
@dlt.source(name="tuya")
def tuya_source(
    api_base_url: str = "https://openapi.tuyaus.com",
    access_id: str = dlt.secrets.value,
    access_secret: str = dlt.secrets.value,
    device_ids: List[str] = dlt.config.value, # Get from config, e.g., ["eb1ae44e3bb8945c7colh"]
) -> Iterator[TDataItem]:
    """
    A dlt source function that retrieves data from the Tuya API for specified devices.

    This source dynamically generates resources based on the provided device IDs.
    It first fetches device properties (including status codes) and then uses these
    codes to fetch relevant status reporting logs incrementally.

    Args:
        api_base_url (str, optional): The base URL for the Tuya API.
            Defaults to "https://openapi.tuyaus.com".
        access_id (str, optional): Tuya API Access ID. Defaults to value from dlt secrets.
        access_secret (str, optional): Tuya API Access Secret. Defaults to value from dlt secrets.
        device_ids (List[str], optional): A list of Tuya device IDs to fetch data for.
            Defaults to value from dlt config.

    Returns:
        Iterator[TDataItem]: An iterator yielding dlt resources configured for the Tuya API.
            Yields 'device_properties' and 'status_reporting_log' resources.
    """
    # Check if device_ids are provided
    if not device_ids:
        # Log a warning or raise an error if needed
        print("Warning: No device_ids configured for Tuya source. Skipping resource generation.")
        return # Exit the source function if no devices to process

    # --- Configuration for Tuya API ---
    # Note: Incremental loading needs careful testing with Tuya's timestamp format and API behavior.
    # Tuya uses milliseconds epoch time.

    # Define the resource to get device properties (including codes) first
    device_properties_resource = {
        "name": "device_properties",
        "endpoint": {
            "path": "/v1.0/devices/{device_id}/status", # Endpoint to get current status/properties
            "params": {
                "device_id": {
                    "type": "resolve",
                    "resource": "__param__", # Special resource to resolve from function params
                    "field": "device_id"
                }
            },
            "data_path": "result", # Assuming the properties list is directly under 'result'
        },
        # This resource likely doesn't need pagination or incremental loading itself
        "write_disposition": "replace", # Replace properties each time
    }

    # Define the main resource for status reporting logs
    status_reporting_log_resource = {
        "name": "status_reporting_log",
        "endpoint": {
            "path": "/v2.0/cloud/thing/{device_id}/report-logs",
            "params": {
                "device_id": {
                    "type": "resolve",
                    "resource": "__param__",
                    "field": "device_id"
                },
                "codes": {
                    "type": "resolve",
                    "resource": "device_properties", # Depends on the properties resource
                    "field": "$", # Use the entire result list from device_properties
                    "resolver": resolve_codes # Custom function to extract/join codes
                },
                "size": 100, # Max recommended by Tuya docs
                "start_time": {
                    "type": "incremental",
                    "cursor_path": "event_time", # Path within each log entry
                    # Assuming event_time is milliseconds epoch
                    "initial_value": pendulum.now().subtract(days=30).int_timestamp * 1000,
                    # dlt might need adjustment if it expects seconds for timestamp comparisons
                },
                # 'end_time' is implicitly handled by dlt's incremental logic (up to 'now')
                # but Tuya requires it explicitly. We might need a custom incremental handler
                # or adjust dlt's behavior if it doesn't automatically add end_time.
                # For now, let's assume dlt handles the range or we add end_time manually if needed.
                "end_time": lambda: int(time.time() * 1000), # Add current time as end_time
                "last_row_key": {
                    "type": "paginator",
                    "paginator": "json_response", # Use explicit paginator config
                }
            },
            "paginator": {
                "type": "json_response",
                "cursor_path": "result.last_row_key",
                "next_page_token_path": "result.last_row_key", # Use last key as token
                "has_more_path": "result.has_more",
                "data_path": "result.logs", # Extract the list of logs
                "total_path": "result.total", # Optional total count
                "max_pages": None # Load all pages
            },
            "data_path": "result.logs", # Redundant with paginator but good practice
        },
        "primary_key": ("device_id", "code", "event_time"), # Composite key
        "write_disposition": "merge",
        # Add device_id to each log record for clarity, especially if processing multiple devices
        "include_from_parent": ["device_id"],
    }

    # Combine into RESTAPIConfig
    config: RESTAPIConfig = {
        "client": {
            "base_url": api_base_url,
            "auth": TuyaAuth(access_id=access_id, access_secret=access_secret),
            # Add timeouts if needed
            # "timeout": 10,
        },
        "resources": [
            # Define resources. The order might matter if one depends on another implicitly.
            # dlt should handle explicit dependencies via 'resolve'.
            device_properties_resource,
            status_reporting_log_resource,
        ],
        # Define how parameters like device_id are passed to resources
        "param_defaults": {
            "device_id": {
                "type": "param", # Indicates it's a top-level parameter for the source
            }
        }
    }

    # The config defines how device_id is resolved from parameters.
    # dlt should handle iterating or resolving based on the provided 'device_ids' config.
    # We yield the resources based on the config once.
    yield from rest_api_resources(config)


def load_tuya() -> None:
    """Loads data from the Tuya API for configured devices."""
    # Configure pipeline destination (e.g., DuckDB)
    pipeline = dlt.pipeline(
        pipeline_name="rest_api_tuya",
        destination='duckdb', # Or your preferred destination
        dataset_name="tuya_data",
    )

    # Define necessary secrets and config values
    # These should be set in your environment or .dlt/secrets.toml / config.toml
    # Example:
    # secrets.toml:
    # [sources.tuya]
    # access_id = "..."
    # access_secret = "..."
    #
    # config.toml:
    # [sources.tuya]
    # device_ids = ["eb1ae44e3bb8945c7colh", "another_device_id"]

    # Create the source instance (dlt handles injecting secrets/config)
    data_source = tuya_source()

    # Run the pipeline
    print("Running Tuya pipeline...")
    load_info = pipeline.run(data_source)
    print(load_info)


if __name__ == "__main__":
    load_tuya()
