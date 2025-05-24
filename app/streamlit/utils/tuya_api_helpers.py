import os
import json # Import json
from tuya_connector import TuyaOpenAPI
from dotenv import load_dotenv
import streamlit as st # Added for caching

# Load environment variables from .env file
load_dotenv()

# Load Tuya API credentials from environment variables
# Using the variable names provided by the user from their .env file
ACCESS_ID = os.environ.get("ACCESS_ID")
ACCESS_SECRET = os.environ.get("ACCESS_SECRET")
API_ENDPOINT = os.environ.get("API_ENDPOINT", "https://openapi.tuyaus.com") # Default to US endpoint if not in .env

# Initialize Tuya OpenAPI
# It's recommended to initialize once and reuse the object
# However, for simplicity in a Streamlit app where state is managed per session,
# we can re-initialize or use Streamlit's session state for the openapi object.
# For now, let's create a function to get the connected openapi object.

def get_tuya_openapi():
    """Initializes and connects to the Tuya OpenAPI."""
    if not ACCESS_ID or not ACCESS_SECRET:
        raise ValueError("Tuya API credentials (TUYA_ACCESS_ID, TUYA_ACCESS_SECRET) not set in environment variables.")

    openapi = TuyaOpenAPI(API_ENDPOINT, ACCESS_ID, ACCESS_SECRET)
    openapi.connect()
    return openapi

def _load_device_mapping_from_path(path_to_check):
    """
    Attempts to load device mapping from a given path.
    The JSON file is expected to have device IDs as keys and objects as values,
    where each object contains "name" and optionally "on_off_code".
    Returns a list of dictionaries: [{"id": id, "name": name, "on_off_code": code}, ...].
    """
    if not os.path.exists(path_to_check):
        print(f"Info: Device mapping file not found at {path_to_check}")
        return None
    try:
        with open(path_to_check, 'r', encoding='utf-8') as f:
            raw_mapping = json.load(f)
        
        devices_list = []
        for dev_id, dev_info in raw_mapping.items():
            if isinstance(dev_info, dict) and "name" in dev_info:
                # Default to 'switch_led' if on_off_code is not specified in the mapping
                on_off_code = dev_info.get('on_off_code', 'switch_led') 
                devices_list.append({"id": dev_id, "name": dev_info["name"], "on_off_code": on_off_code})
            elif isinstance(dev_info, str): # Handle old format: "DEVICE_ID": "DEVICE_NAME"
                print(f"Info: Device entry for {dev_id} is in old format. Defaulting on_off_code to 'switch_led'.")
                devices_list.append({"id": dev_id, "name": dev_info, "on_off_code": 'switch_led'})
            else:
                print(f"Warning: Device entry for {dev_id} is not in a recognized format. Skipping.")
        
        if not devices_list and raw_mapping:
            print(f"Warning: Processed device list is empty. Original mapping might be malformed: {raw_mapping}")

        return devices_list
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {path_to_check}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred loading device mapping from {path_to_check}: {e}")
        return None

@st.cache_data(ttl=3600) # Cache for 1 hour, or until invalidated
def list_devices():
    """
    Lists devices from the device mapping file.
    Tries path from DEVICE_MAPPING_PATH env var first, then a default path.
    """
    devices_list = []
    
    # Determine script's directory to build absolute paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, "../../../")) # Assuming tuya_api_helpers.py is in app/streamlit/utils/

    # Path from environment variable
    env_mapping_path_relative = os.environ.get("DEVICE_MAPPING_PATH")
    # Default path, relative to project root
    default_mapping_path_relative = "app/data/device_mapping.json"
    
    path_to_try_from_env = None
    if env_mapping_path_relative:
        # If path from .env is absolute, use it. If relative, assume it's relative to project root.
        if os.path.isabs(env_mapping_path_relative):
            path_to_try_from_env = env_mapping_path_relative
        else:
            path_to_try_from_env = os.path.join(project_root, env_mapping_path_relative)
        
        print(f"Attempting to load device mapping from .env path: {path_to_try_from_env} (derived from '{env_mapping_path_relative}')")
        devices_list = _load_device_mapping_from_path(path_to_try_from_env)
        if devices_list:
            os.environ["ACTUAL_DEVICE_MAPPING_PATH_USED"] = path_to_try_from_env
            return devices_list # Successfully loaded

    # If .env path failed or was not set, try default path (absolute)
    path_to_try_default = os.path.join(project_root, default_mapping_path_relative)
    print(f"Attempting to load device mapping from default path: {path_to_try_default}")
    devices_list = _load_device_mapping_from_path(path_to_try_default)

    if devices_list:
        os.environ["ACTUAL_DEVICE_MAPPING_PATH_USED"] = path_to_try_default
    elif path_to_try_from_env: # .env path was tried and failed, default also failed
        os.environ["ACTUAL_DEVICE_MAPPING_PATH_USED"] = "Nenhum caminho válido encontrado"
    else: # .env path was not set, and default failed
        os.environ["ACTUAL_DEVICE_MAPPING_PATH_USED"] = path_to_try_default # Show the default path that was tried as the last attempt

    if not devices_list:
        print("Error: Device mapping file could not be loaded from .env path or default path.")
        return [] # Ensure it always returns a list

    return devices_list if devices_list else []

@st.cache_data(ttl=60) # Cache device status for 60 seconds, or until invalidated
def get_device_status(device_id):
    """Gets the current status of a specific device."""
    openapi = get_tuya_openapi()
    # Endpoint from documentation: /v2.0/cloud/thing/{device_id}/shadow/properties
    response = openapi.get(f"/v2.0/cloud/thing/{device_id}/shadow/properties")
    # Assuming the response contains properties in 'result.properties'
    if response and response.get('success'):
        return response.get('result', {}).get('properties', [])
    else:
        # Handle API error or empty response
        print(f"Error getting device status for {device_id}: {response.get('msg', 'Unknown error')}")
        return []

def send_device_command(device_id, code, value):
    """Sends a command to a specific device."""
    openapi = get_tuya_openapi()
    # Endpoint from documentation: /v1.0/iot-03/devices/{device_id}/commands
    commands = {"commands": [{"code": code, "value": value}]}
    response = openapi.post(f"/v1.0/iot-03/devices/{device_id}/commands", commands)
    # Assuming success is indicated by 'success' field
    if response and response.get('success'):
        # Invalidate the cache for all device statuses
        get_device_status.clear()
        return True
    else:
        # Handle API error
        print(f"Error sending command to {device_id}: {response.get('msg', 'Unknown error')}")
        return False

def execute_scene(scene_actions):
    """Executes a scene by sending commands to multiple devices."""
    success = True
    for device_id, action in scene_actions.items():
        code = action.get("code")
        value = action.get("value")
        if not send_device_command(device_id, code, value):
            success = False # If any command fails, the scene execution failed
            # Optionally, break or log the specific device failure
    return success

# Scene management functions will be added later
