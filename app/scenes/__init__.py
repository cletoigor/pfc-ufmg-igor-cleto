"""
Scheduled scenes: named sets of device actions that can be run on demand or on
a schedule.

`store` owns the JSON file; `executor` decides when a scene is due and turns it
into Tuya commands. Both are framework-free so the Starlette API and the Dagster
op call the same code rather than each keeping their own copy.
"""
from app.scenes.executor import SCENE_DRY_RUN_ENV, run_scene, scene_is_due, scenes_dry_run_default
from app.scenes.store import (
    SCENES_PATH,
    SceneValidationError,
    create_scene,
    delete_scene,
    get_scene,
    load_scenes,
    mark_executed,
    save_scenes,
)

__all__ = [
    "SCENES_PATH",
    "SCENE_DRY_RUN_ENV",
    "SceneValidationError",
    "create_scene",
    "delete_scene",
    "get_scene",
    "load_scenes",
    "mark_executed",
    "run_scene",
    "save_scenes",
    "scene_is_due",
    "scenes_dry_run_default",
]
