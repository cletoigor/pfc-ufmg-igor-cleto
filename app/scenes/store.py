"""
Persistence for scheduled scenes (app/data/scheduled_scenes.json).

Two processes touch this file: the web API, when a user creates, deletes or
runs a scene, and the Dagster scene scheduler, once a minute, when it marks a
one-shot scene as executed. So every write goes through this module and lands
atomically — written to a temporary file in the same directory and renamed over
the target, which is atomic on POSIX — rather than being truncated in place
where a badly timed read would see half a document.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENES_PATH = os.path.join(_APP_DIR, "data", "scheduled_scenes.json")

VALID_ACTIONS = ("on", "off")
_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# 0 = Monday .. 6 = Sunday, matching datetime.date.weekday().
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class SceneValidationError(ValueError):
    """A scene definition the store refuses to persist."""


def _scenes_path(path: str | None = None) -> str:
    return path or SCENES_PATH


def load_scenes(path: str | None = None) -> list[dict]:
    """Every stored scene, oldest first. Never raises.

    A missing file is simply an empty list — the common case on a fresh clone.
    A corrupt file is also treated as empty rather than taking the whole
    Actuations page down with it; the file is small and user-authored, and a
    page that still works is more useful than a stack trace.
    """
    target = _scenes_path(path)
    try:
        with open(target, "r", encoding="utf-8") as f:
            document = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

    scenes = document.get("scenes") if isinstance(document, dict) else document
    return scenes if isinstance(scenes, list) else []


def save_scenes(scenes: list[dict], path: str | None = None) -> None:
    """Replaces the stored scene list atomically."""
    target = _scenes_path(path)
    os.makedirs(os.path.dirname(target), exist_ok=True)

    directory = os.path.dirname(target)
    handle, temp_path = tempfile.mkstemp(dir=directory, prefix=".scenes-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            json.dump({"scenes": scenes}, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, target)
    except BaseException:
        # Never leave a half-written temp file behind on a failed save.
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def get_scene(scene_id: str, path: str | None = None) -> dict | None:
    for scene in load_scenes(path):
        if scene.get("id") == scene_id:
            return scene
    return None


def validate_scene(payload: dict, known_devices=None) -> dict:
    """Checks a user-supplied scene and returns it in canonical form.

    Raises `SceneValidationError` with a message meant to be shown to the user,
    since the API surfaces it directly as a 400.
    """
    if not isinstance(payload, dict):
        raise SceneValidationError("A scene must be an object.")

    name = str(payload.get("name") or "").strip()
    if not name:
        raise SceneValidationError("A scene needs a name.")

    raw_actions = payload.get("actions") or {}
    if not isinstance(raw_actions, dict) or not raw_actions:
        raise SceneValidationError("A scene needs at least one device action.")

    actions = {}
    for device, action in raw_actions.items():
        action = str(action).strip().lower()
        if action not in VALID_ACTIONS:
            raise SceneValidationError(
                f"Unknown action {action!r} for {device!r}; expected one of {', '.join(VALID_ACTIONS)}."
            )
        if known_devices is not None and device not in known_devices:
            raise SceneValidationError(f"Unknown device: {device!r}.")
        actions[str(device)] = action

    schedule = payload.get("schedule") or {}
    if not isinstance(schedule, dict):
        raise SceneValidationError("`schedule` must be an object.")

    # A scene with no time is legitimate: the monograph's wizard makes the
    # schedule step optional, and such a scene is simply run by hand.
    time_of_day = schedule.get("time")
    if time_of_day not in (None, ""):
        time_of_day = str(time_of_day).strip()
        if not _TIME_PATTERN.match(time_of_day):
            raise SceneValidationError(f"Invalid time {time_of_day!r}; expected HH:mm, 24-hour.")
    else:
        time_of_day = None

    days = schedule.get("days_of_week")
    if days in (None, ""):
        days = []
    if not isinstance(days, (list, tuple)):
        raise SceneValidationError("`days_of_week` must be a list of integers, 0 (Monday) to 6.")
    day_numbers = []
    for day in days:
        try:
            day_number = int(day)
        except (TypeError, ValueError) as exc:
            raise SceneValidationError(f"Invalid day of week: {day!r}.") from exc
        if not 0 <= day_number <= 6:
            raise SceneValidationError(f"Day of week out of range: {day_number} (expected 0-6).")
        day_numbers.append(day_number)

    if time_of_day and not day_numbers:
        raise SceneValidationError("A scheduled scene needs at least one day of the week.")

    return {
        "name": name,
        "actions": actions,
        "devices": sorted(actions),
        "schedule": {
            "time": time_of_day,
            "days_of_week": sorted(set(day_numbers)),
            "recurring": bool(schedule.get("recurring", True)),
        },
        "enabled": bool(payload.get("enabled", True)),
    }


def create_scene(payload: dict, known_devices=None, path: str | None = None) -> dict:
    """Validates, stamps and appends a scene. Returns the stored record."""
    scene = validate_scene(payload, known_devices=known_devices)
    scene.update(
        {
            "id": uuid.uuid4().hex,
            "created_at": datetime.now().replace(microsecond=0).isoformat(),
            "last_executed_at": None,
            "executed": False,
        }
    )

    scenes = load_scenes(path)
    scenes.append(scene)
    save_scenes(scenes, path)
    return scene


def delete_scene(scene_id: str, path: str | None = None) -> bool:
    """Removes a scene. Returns False if there was nothing with that id."""
    scenes = load_scenes(path)
    remaining = [scene for scene in scenes if scene.get("id") != scene_id]
    if len(remaining) == len(scenes):
        return False
    save_scenes(remaining, path)
    return True


def mark_executed(scene_id: str, when: datetime | None = None, path: str | None = None) -> dict | None:
    """Records that a scene ran.

    A non-recurring scene is also flagged `executed`, which is what stops the
    scheduler from firing it again every minute for the rest of the day.
    """
    scenes = load_scenes(path)
    updated = None
    for scene in scenes:
        if scene.get("id") == scene_id:
            stamp = (when or datetime.now()).replace(microsecond=0)
            scene["last_executed_at"] = stamp.isoformat()
            if not scene.get("schedule", {}).get("recurring", True):
                scene["executed"] = True
            updated = scene
            break

    if updated is not None:
        save_scenes(scenes, path)
    return updated
