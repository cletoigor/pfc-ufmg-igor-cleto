"""
Deciding when a scene is due, and turning it into Tuya commands.

Shared by the web API's "run now" button and the Dagster scene scheduler, so
there is one definition of what running a scene means.

Safety
------
This is the only unattended path in the project that can send a real command to
a physical device, and it is deliberately harder to arm than the interactive
one. Two independent gates exist:

  * The interactive gate — the dashboard's SAFE/ARMED switch, passed through as
    `dry_run` on each API request. It covers what a person does while watching.
  * The unattended gate — the `SCENE_EXECUTION_DRY_RUN` environment variable,
    read by the Dagster scheduler. It defaults to dry-run, and only setting it
    to "0" lets a scheduled scene actuate anything.

They are separate on purpose: arming the panel to try a command by hand must
not also arm a job that fires at 03:00 with nobody watching. Underneath both,
`send_device_command` still refuses to reach Tuya without credentials, so a
misconfiguration fails closed rather than open.
"""
from __future__ import annotations

import os
from datetime import datetime

from app.agent.tools import resolve_switch_code
from app.agent.tuya_control import load_device_registry, resolve_device_id, send_device_command

SCENE_DRY_RUN_ENV = "SCENE_EXECUTION_DRY_RUN"


def scenes_dry_run_default() -> bool:
    """Whether unattended scene execution is in dry-run. Defaults to True."""
    raw = os.environ.get(SCENE_DRY_RUN_ENV, "1").strip().lower()
    return raw not in ("0", "false", "no")


def scene_is_due(scene: dict, now: datetime) -> bool:
    """Whether a scene should fire at this minute.

    Matching is to the minute, which is why the scheduler runs every minute: a
    coarser cadence would step over a scene's slot entirely.
    """
    if not scene.get("enabled", True):
        return False

    schedule = scene.get("schedule") or {}
    time_of_day = schedule.get("time")
    if not time_of_day:
        return False  # manual-only scene

    if time_of_day != now.strftime("%H:%M"):
        return False

    days = schedule.get("days_of_week") or []
    if days and now.weekday() not in days:
        return False

    recurring = schedule.get("recurring", True)
    if not recurring and scene.get("executed"):
        return False

    # A recurring scene must not fire twice within the same minute — the
    # scheduler can be re-run, and Dagster can retry a failed run.
    last = scene.get("last_executed_at")
    if last:
        try:
            if datetime.fromisoformat(last).strftime("%Y-%m-%d %H:%M") == now.strftime(
                "%Y-%m-%d %H:%M"
            ):
                return False
        except ValueError:
            pass  # unparseable stamp: treat as never run rather than blocking

    return True


def run_scene(scene: dict, dry_run: bool = True) -> dict:
    """Applies every action in a scene.

    `dry_run` defaults to True here as it does everywhere else in this project:
    a caller that forgets to pass it gets the safe behaviour, not the live one.

    One device failing does not abort the rest — a scene that turns off four
    things should turn off the three it can reach and report the fourth.
    """
    registry = load_device_registry()
    results = []

    for device_name, action in (scene.get("actions") or {}).items():
        device_id = resolve_device_id(device_name, registry)
        if device_id is None:
            results.append(
                {
                    "device": device_name,
                    "action": action,
                    "ok": False,
                    "dry_run": dry_run,
                    "error": f"Unknown device: {device_name!r}.",
                }
            )
            continue

        commands = [{"code": resolve_switch_code(device_id), "value": action == "on"}]
        try:
            outcome = send_device_command(device_id, commands, dry_run=dry_run)
            results.append(
                {
                    "device": device_name,
                    "action": action,
                    "ok": not outcome.get("error"),
                    "dry_run": dry_run,
                    "payload": outcome.get("payload", {"commands": commands}),
                    "error": outcome.get("error"),
                }
            )
        except Exception as exc:  # pylint: disable=broad-except
            results.append(
                {
                    "device": device_name,
                    "action": action,
                    "ok": False,
                    "dry_run": dry_run,
                    "error": str(exc),
                }
            )

    return {
        "scene_id": scene.get("id"),
        "scene": scene.get("name"),
        "dry_run": dry_run,
        "ok": all(result["ok"] for result in results) if results else False,
        "results": results,
    }
