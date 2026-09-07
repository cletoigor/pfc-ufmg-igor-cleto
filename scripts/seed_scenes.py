#!/usr/bin/env python3
"""
Seeds a handful of demo scenes into app/data/scheduled_scenes.json.

`app/data/` is gitignored, so a fresh clone starts with no scenes at all and
the Actuations page's "Saved scenes" section is empty — which makes the scene
wizard, the run-by-hand button and the every-minute scheduler look like
features nobody has used. This is the scenes half of what
`seed_synthetic_data.py` does for the readings.

Every scene goes through `app.scenes.store.create_scene`, so the seeds are
validated and written by exactly the code path the API uses — a seed that the
store would reject fails here rather than in the UI.

Existing scenes are kept and matched by name: re-running the script adds only
what is missing. Pass --replace to drop everything first.

Usage:
    python scripts/seed_scenes.py [--replace]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.data_access import load_device_mapping  # noqa: E402
from app.scenes.store import (  # noqa: E402
    SCENES_PATH,
    SceneValidationError,
    create_scene,
    load_scenes,
    save_scenes,
)

# Weekday numbers match datetime.date.weekday(): 0 = Monday.
WEEKDAYS = [0, 1, 2, 3, 4]
WEEKEND = [5, 6]
EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]

# The demo set covers the three shapes the Actuations page has to show:
# a scheduled weekday scene, a daily one, a weekend one, and a scene with no
# time at all — which is legitimate, and is run by hand from the page.
DEMO_SCENES = [
    {
        "name": "Morning start",
        "actions": {"Office Lamp": "on", "Office Outlet": "on"},
        "schedule": {"time": "07:00", "days_of_week": WEEKDAYS, "recurring": True},
    },
    {
        "name": "Evening wind-down",
        "actions": {"LED Strip": "off", "Living Room Switch": "off"},
        "schedule": {"time": "22:30", "days_of_week": WEEKDAYS, "recurring": True},
    },
    {
        "name": "Dusk defence",
        "actions": {"Mosquito Repellent": "on", "LED Strip": "on"},
        "schedule": {"time": "18:30", "days_of_week": EVERY_DAY, "recurring": True},
    },
    {
        "name": "Weekend lie-in",
        "actions": {"Bedroom Fan": "on", "Office Lamp": "off"},
        "schedule": {"time": "09:30", "days_of_week": WEEKEND, "recurring": True},
    },
    {
        "name": "Leaving the house",
        "actions": {
            "Bedroom Fan": "off",
            "LED Strip": "off",
            "Living Room Switch": "off",
            "Office Lamp": "off",
            "Office Outlet": "off",
        },
        "schedule": {},
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="delete every stored scene before seeding, instead of adding the missing ones",
    )
    args = parser.parse_args()

    known_devices = set(load_device_mapping().values())

    if args.replace:
        save_scenes([])

    existing = {scene.get("name") for scene in load_scenes()}

    added = 0
    for payload in DEMO_SCENES:
        if payload["name"] in existing:
            print(f"  {payload['name']:<20} already present, left alone")
            continue
        try:
            create_scene(payload, known_devices=known_devices)
        except SceneValidationError as exc:
            raise SystemExit(f"{payload['name']}: {exc}") from exc
        schedule = payload["schedule"]
        when = schedule.get("time") or "run by hand"
        print(f"  {payload['name']:<20} added  ({when}, {len(payload['actions'])} actions)")
        added += 1

    print(f"\n{added} scene(s) added; {len(load_scenes())} stored in {SCENES_PATH}")


if __name__ == "__main__":
    main()
