"""
Unit tests for app/agent/tuya_control.py.

`send_device_command` is only ever exercised with `dry_run=True` here — this
module must NEVER hit the real Tuya API or import tuya_connector at module
load time (it's imported lazily inside the non-dry-run branch).
"""
from app.agent.tuya_control import (
    reverse_device_registry,
    resolve_device_id,
    send_device_command,
)

FIXTURE_REGISTRY = {
    "device-abc": "Living Room Lamp",
    "device-def": "Bedroom Fan",
}


def test_reverse_device_registry_is_case_insensitive_lookup():
    reverse = reverse_device_registry(FIXTURE_REGISTRY)
    assert reverse["living room lamp"] == "device-abc"
    assert reverse["bedroom fan"] == "device-def"


def test_resolve_device_id_matches_case_insensitively():
    assert resolve_device_id("Living Room Lamp", FIXTURE_REGISTRY) == "device-abc"
    assert resolve_device_id("LIVING ROOM LAMP", FIXTURE_REGISTRY) == "device-abc"
    assert resolve_device_id("  bedroom fan  ", FIXTURE_REGISTRY) == "device-def"


def test_resolve_device_id_unknown_name_returns_none():
    assert resolve_device_id("Nonexistent Device", FIXTURE_REGISTRY) is None


def test_send_device_command_dry_run_payload_shape():
    commands = [{"code": "switch_1", "value": True}]

    result = send_device_command("device-abc", commands, dry_run=True)

    assert result["dry_run"] is True
    assert result["device_id"] == "device-abc"
    assert result["endpoint"] == "/v1.0/iot-03/devices/device-abc/commands"
    assert result["payload"] == {"commands": commands}
    assert result["success"] is None
    assert result["response"] is None


def test_send_device_command_dry_run_never_hits_network(monkeypatch):
    # Ensure importing tuya_connector inside send_device_command would blow up
    # if reached, so we know the dry-run path returns before it gets there.
    import builtins

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "tuya_connector":
            raise AssertionError("tuya_connector must not be imported in dry-run mode")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    result = send_device_command(
        "device-abc", [{"code": "switch_1", "value": False}], dry_run=True
    )
    assert result["dry_run"] is True
