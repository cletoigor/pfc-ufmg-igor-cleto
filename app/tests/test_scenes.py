"""
Tests for scene storage, scheduling and execution (app/scenes/).

The safety tests here are the important ones. Scene execution is the only
unattended path in this project that can send a real command to a physical
device, so "it stays in dry-run unless explicitly armed" is pinned by tests
rather than left to inspection.
"""
import json
from datetime import datetime

import pytest

from app.scenes.executor import (
    SCENE_DRY_RUN_ENV,
    run_scene,
    scene_is_due,
    scenes_dry_run_default,
)
from app.scenes.store import (
    SceneValidationError,
    create_scene,
    delete_scene,
    get_scene,
    load_scenes,
    mark_executed,
    save_scenes,
    validate_scene,
)

KNOWN_DEVICES = {"LED Strip", "Living Room Switch", "Office Lamp"}


@pytest.fixture
def scenes_file(tmp_path):
    return str(tmp_path / "scheduled_scenes.json")


def _payload(**overrides):
    base = {
        "name": "Evening wind-down",
        "actions": {"LED Strip": "off", "Living Room Switch": "off"},
        "schedule": {"time": "22:30", "days_of_week": [0, 1, 2, 3, 4], "recurring": True},
    }
    base.update(overrides)
    return base


# --- storage ----------------------------------------------------------------


def test_a_missing_file_reads_as_no_scenes(scenes_file):
    assert load_scenes(scenes_file) == []


def test_a_corrupt_file_reads_as_no_scenes_rather_than_raising(scenes_file, tmp_path):
    with open(scenes_file, "w", encoding="utf-8") as f:
        f.write("{not json at all")

    assert load_scenes(scenes_file) == []


def test_create_then_read_back_round_trips(scenes_file):
    created = create_scene(_payload(), known_devices=KNOWN_DEVICES, path=scenes_file)

    stored = load_scenes(scenes_file)
    assert len(stored) == 1
    assert stored[0]["name"] == "Evening wind-down"
    assert stored[0]["actions"] == {"LED Strip": "off", "Living Room Switch": "off"}
    assert get_scene(created["id"], scenes_file) == created


def test_a_new_scene_is_stamped_with_an_id_and_a_clean_history(scenes_file):
    scene = create_scene(_payload(), known_devices=KNOWN_DEVICES, path=scenes_file)

    assert scene["id"]
    assert scene["created_at"]
    assert scene["last_executed_at"] is None
    assert scene["executed"] is False


def test_deleting_returns_false_for_an_unknown_id(scenes_file):
    create_scene(_payload(), known_devices=KNOWN_DEVICES, path=scenes_file)

    assert delete_scene("does-not-exist", scenes_file) is False
    assert len(load_scenes(scenes_file)) == 1


def test_deleting_removes_only_the_named_scene(scenes_file):
    first = create_scene(_payload(name="One"), known_devices=KNOWN_DEVICES, path=scenes_file)
    create_scene(_payload(name="Two"), known_devices=KNOWN_DEVICES, path=scenes_file)

    assert delete_scene(first["id"], scenes_file) is True
    remaining = load_scenes(scenes_file)
    assert [scene["name"] for scene in remaining] == ["Two"]


def test_the_file_is_written_as_a_whole_document(scenes_file):
    save_scenes([{"id": "a", "name": "A"}], scenes_file)

    with open(scenes_file, "r", encoding="utf-8") as f:
        document = json.load(f)
    assert document == {"scenes": [{"id": "a", "name": "A"}]}


# --- validation -------------------------------------------------------------


def test_a_scene_needs_a_name():
    with pytest.raises(SceneValidationError, match="name"):
        validate_scene(_payload(name="   "))


def test_a_scene_needs_at_least_one_action():
    with pytest.raises(SceneValidationError, match="action"):
        validate_scene(_payload(actions={}))


def test_unknown_actions_are_rejected():
    with pytest.raises(SceneValidationError, match="Unknown action"):
        validate_scene(_payload(actions={"LED Strip": "explode"}))


def test_unknown_devices_are_rejected_when_a_registry_is_supplied():
    with pytest.raises(SceneValidationError, match="Unknown device"):
        validate_scene(_payload(actions={"Toaster": "on"}), known_devices=KNOWN_DEVICES)


@pytest.mark.parametrize("bad_time", ["25:00", "7:5", "22:60", "evening", "2230"])
def test_malformed_times_are_rejected(bad_time):
    with pytest.raises(SceneValidationError, match="time"):
        validate_scene(_payload(schedule={"time": bad_time, "days_of_week": [0]}))


@pytest.mark.parametrize("bad_day", [7, -1, "monday"])
def test_out_of_range_days_are_rejected(bad_day):
    with pytest.raises(SceneValidationError):
        validate_scene(_payload(schedule={"time": "22:30", "days_of_week": [bad_day]}))


def test_a_scheduled_scene_needs_at_least_one_day():
    with pytest.raises(SceneValidationError, match="day of the week"):
        validate_scene(_payload(schedule={"time": "22:30", "days_of_week": []}))


def test_a_scene_with_no_time_is_valid_and_manual_only():
    """The monograph's wizard makes the schedule step optional."""
    scene = validate_scene(_payload(schedule={}))

    assert scene["schedule"]["time"] is None
    assert scene_is_due(scene, datetime(2026, 9, 7, 22, 30)) is False


# --- scheduling -------------------------------------------------------------


def test_a_scene_fires_on_its_minute_and_day():
    scene = validate_scene(_payload())  # 22:30, Mon-Fri

    monday_2230 = datetime(2026, 9, 7, 22, 30)
    assert monday_2230.weekday() == 0
    assert scene_is_due(scene, monday_2230) is True


def test_a_scene_does_not_fire_a_minute_early_or_late():
    scene = validate_scene(_payload())

    assert scene_is_due(scene, datetime(2026, 9, 7, 22, 29)) is False
    assert scene_is_due(scene, datetime(2026, 9, 7, 22, 31)) is False


def test_a_scene_does_not_fire_on_an_excluded_day():
    scene = validate_scene(_payload())  # weekdays only
    saturday = datetime(2026, 9, 12, 22, 30)

    assert saturday.weekday() == 5
    assert scene_is_due(scene, saturday) is False


def test_a_disabled_scene_never_fires():
    scene = validate_scene(_payload(enabled=False))

    assert scene_is_due(scene, datetime(2026, 9, 7, 22, 30)) is False


def test_a_one_shot_scene_does_not_fire_again_once_executed():
    scene = validate_scene(_payload(schedule={"time": "22:30", "days_of_week": [0], "recurring": False}))
    assert scene_is_due(scene, datetime(2026, 9, 7, 22, 30)) is True

    scene["executed"] = True
    assert scene_is_due(scene, datetime(2026, 9, 7, 22, 30)) is False


def test_a_recurring_scene_does_not_fire_twice_in_the_same_minute():
    """The scheduler runs every minute and Dagster can retry a run."""
    scene = validate_scene(_payload())
    now = datetime(2026, 9, 7, 22, 30)

    scene["last_executed_at"] = now.isoformat()
    assert scene_is_due(scene, now) is False
    # ...but it is due again next week.
    assert scene_is_due(scene, datetime(2026, 9, 14, 22, 30)) is True


def test_marking_executed_records_the_time_and_latches_one_shot_scenes(scenes_file):
    recurring = create_scene(_payload(name="Weekly"), known_devices=KNOWN_DEVICES, path=scenes_file)
    one_shot = create_scene(
        _payload(name="Once", schedule={"time": "07:00", "days_of_week": [0], "recurring": False}),
        known_devices=KNOWN_DEVICES,
        path=scenes_file,
    )

    mark_executed(recurring["id"], when=datetime(2026, 9, 7, 22, 30), path=scenes_file)
    mark_executed(one_shot["id"], when=datetime(2026, 9, 7, 7, 0), path=scenes_file)

    stored = {scene["name"]: scene for scene in load_scenes(scenes_file)}
    assert stored["Weekly"]["last_executed_at"] == "2026-09-07T22:30:00"
    assert stored["Weekly"]["executed"] is False   # recurring scenes stay armed
    assert stored["Once"]["executed"] is True      # one-shot scenes latch off


# --- execution and the safety gate ------------------------------------------


def test_running_a_scene_defaults_to_dry_run(monkeypatch):
    """The default must be safe even if a caller forgets to pass dry_run."""
    sent = []

    def _spy(device_id, commands, *, dry_run=True):
        sent.append((device_id, commands, dry_run))
        return {"dry_run": dry_run, "payload": {"commands": commands}}

    monkeypatch.setattr("app.scenes.executor.send_device_command", _spy)
    monkeypatch.setattr("app.scenes.executor.resolve_switch_code", lambda _id: "switch_led")
    monkeypatch.setattr(
        "app.scenes.executor.load_device_registry", lambda: {"dev-1": "LED Strip"}
    )

    outcome = run_scene({"id": "s1", "name": "S", "actions": {"LED Strip": "off"}})

    assert outcome["dry_run"] is True
    assert sent == [("dev-1", [{"code": "switch_led", "value": False}], True)]


def test_running_a_scene_resolves_each_devices_own_switch_code(monkeypatch):
    """A command addressed to a hardcoded switch_1 silently does nothing on
    devices that report through switch_led or switch."""
    sent = []
    codes = {"dev-strip": "switch_led", "dev-room": "switch_1"}

    monkeypatch.setattr(
        "app.scenes.executor.send_device_command",
        lambda device_id, commands, *, dry_run=True: sent.append((device_id, commands)) or {},
    )
    monkeypatch.setattr("app.scenes.executor.resolve_switch_code", lambda device_id: codes[device_id])
    monkeypatch.setattr(
        "app.scenes.executor.load_device_registry",
        lambda: {"dev-strip": "LED Strip", "dev-room": "Living Room Switch"},
    )

    run_scene({"id": "s", "name": "S", "actions": {"LED Strip": "on", "Living Room Switch": "off"}})

    assert ("dev-strip", [{"code": "switch_led", "value": True}]) in sent
    assert ("dev-room", [{"code": "switch_1", "value": False}]) in sent


def test_one_unreachable_device_does_not_abort_the_rest_of_the_scene(monkeypatch):
    monkeypatch.setattr(
        "app.scenes.executor.send_device_command",
        lambda device_id, commands, *, dry_run=True: {"payload": {"commands": commands}},
    )
    monkeypatch.setattr("app.scenes.executor.resolve_switch_code", lambda _id: "switch_1")
    monkeypatch.setattr(
        "app.scenes.executor.load_device_registry", lambda: {"dev-1": "LED Strip"}
    )

    outcome = run_scene({"id": "s", "name": "S", "actions": {"LED Strip": "off", "Ghost": "off"}})

    by_device = {result["device"]: result for result in outcome["results"]}
    assert by_device["LED Strip"]["ok"] is True
    assert by_device["Ghost"]["ok"] is False
    assert "Unknown device" in by_device["Ghost"]["error"]
    assert outcome["ok"] is False


def test_unattended_execution_is_dry_run_unless_explicitly_armed(monkeypatch):
    """The gate that keeps a scheduled scene from actuating the house at 03:00."""
    monkeypatch.delenv(SCENE_DRY_RUN_ENV, raising=False)
    assert scenes_dry_run_default() is True

    for value in ("1", "true", "yes", "", "anything"):
        monkeypatch.setenv(SCENE_DRY_RUN_ENV, value)
        assert scenes_dry_run_default() is True, f"{value!r} must not arm the scheduler"

    for value in ("0", "false", "no"):
        monkeypatch.setenv(SCENE_DRY_RUN_ENV, value)
        assert scenes_dry_run_default() is False


def test_the_scheduler_gate_is_independent_of_the_interactive_one(monkeypatch):
    """Arming the dashboard must not arm the unattended scheduler."""
    monkeypatch.delenv(SCENE_DRY_RUN_ENV, raising=False)
    sent = []

    monkeypatch.setattr(
        "app.scenes.executor.send_device_command",
        lambda device_id, commands, *, dry_run=True: sent.append(dry_run) or {},
    )
    monkeypatch.setattr("app.scenes.executor.resolve_switch_code", lambda _id: "switch_1")
    monkeypatch.setattr(
        "app.scenes.executor.load_device_registry", lambda: {"dev-1": "LED Strip"}
    )

    # An interactive caller explicitly arming itself...
    run_scene({"id": "s", "name": "S", "actions": {"LED Strip": "on"}}, dry_run=False)
    assert sent == [False]

    # ...changes nothing about what the scheduler would do on its own.
    assert scenes_dry_run_default() is True
