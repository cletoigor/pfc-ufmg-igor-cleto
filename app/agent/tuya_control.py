"""
Tuya device-control mechanism, lifted from
`app/docs/tuya_api/blink_led_example.ipynb`.

The notebook establishes the working shape for sending a command to a Tuya
device: authenticate a `TuyaOpenAPI` client with `ACCESS_ID` / `ACCESS_SECRET`
/ `API_ENDPOINT`, then POST a `{"commands": [{"code": ..., "value": ...}]}`
payload to `/v1.0/iot-03/devices/{device_id}/commands`.

This module wraps that mechanism in a single, dry-run-safe function plus a
small device-registry helper built on top of `app/device_mapping.json`.
"""
import json
import os

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEVICE_MAPPING_PATH = os.path.join(_APP_DIR, "device_mapping.json")

TUYA_COMMANDS_ENDPOINT_TEMPLATE = "/v1.0/iot-03/devices/{device_id}/commands"


def load_device_registry(file_path: str = DEVICE_MAPPING_PATH) -> dict:
    """Loads the device_id -> friendly name registry from device_mapping.json.

    Returns an empty dict (rather than raising) if the file is missing or
    malformed, so callers can degrade gracefully.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as mapping_file:
            return json.load(mapping_file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def reverse_device_registry(registry: dict | None = None) -> dict:
    """Builds a case-insensitive friendly-name -> device_id lookup.

    Keys are lower-cased friendly names; values are the original device_id.
    """
    if registry is None:
        registry = load_device_registry()
    return {name.strip().lower(): device_id for device_id, name in registry.items()}


def resolve_device_id(device_name: str, registry: dict | None = None) -> str | None:
    """Case-insensitive friendly name -> device_id lookup. Returns None if unknown."""
    reverse = reverse_device_registry(registry)
    return reverse.get(device_name.strip().lower())


def send_device_command(
    device_id: str,
    commands: list[dict],
    *,
    dry_run: bool = True,
) -> dict:
    """Sends (or simulates sending) a Tuya `commands` payload to a device.

    Args:
        device_id: The Tuya device ID (e.g. "ebb50554f386a6d20fvbwv").
        commands: A list of command dicts, e.g.
            [{"code": "switch_1", "value": True}].
        dry_run: When True (the default), the Tuya API is never called — the
            payload and endpoint that WOULD be sent are returned instead, so
            demos/tests/agent runs are safe by default.

    Returns:
        A dict describing the outcome:
            {
                "dry_run": bool,
                "device_id": str,
                "endpoint": str,
                "payload": {"commands": [...]},
                "success": bool | None,   # None when dry_run
                "response": dict | None,  # Tuya API response, when not dry_run
            }
    """
    endpoint = TUYA_COMMANDS_ENDPOINT_TEMPLATE.format(device_id=device_id)
    payload = {"commands": commands}

    if dry_run:
        return {
            "dry_run": True,
            "device_id": device_id,
            "endpoint": endpoint,
            "payload": payload,
            "success": None,
            "response": None,
        }

    # Imported lazily so importing this module never requires the
    # tuya-connector-python package or Tuya credentials to be present.
    from tuya_connector import TuyaOpenAPI

    access_id = os.environ["ACCESS_ID"]
    access_secret = os.environ["ACCESS_SECRET"]
    api_endpoint = os.environ["API_ENDPOINT"]

    openapi = TuyaOpenAPI(api_endpoint, access_id, access_secret)
    openapi.connect()

    response = openapi.post(endpoint, payload)

    return {
        "dry_run": False,
        "device_id": device_id,
        "endpoint": endpoint,
        "payload": payload,
        "success": bool(response.get("success", False)),
        "response": response,
    }
