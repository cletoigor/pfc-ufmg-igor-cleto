"""
The Dagster side of scene automation: an op that checks every minute whether
any stored scene is due, and fires the ones that are.

Kept out of `app/assets/` because a scene run is not a data asset — it has no
materialized output and its effect is on the house, not on the warehouse.

Two things to know before relying on this in a demo:

  * A `* * * * *` schedule only fires while the Dagster **daemon** is running
    (`dagster dev` starts one; a bare webserver does not). If the daemon is not
    up, scenes still work — the Actuations page's "Run now" button calls the
    same `run_scene` — they simply are not triggered automatically.
  * Execution is dry-run unless `SCENE_EXECUTION_DRY_RUN=0`. See the safety
    note in `app/scenes/executor.py` for why that gate is separate from the
    dashboard's ARMED switch.
"""
from datetime import datetime, timedelta, timezone

from dagster import ScheduleDefinition, OpExecutionContext, job, op

from app.assets.marts import LOCAL_UTC_OFFSET_HOURS
from app.scenes.executor import run_scene, scene_is_due, scenes_dry_run_default
from app.scenes.store import load_scenes, mark_executed

# The same fixed offset the gold layer uses. Brazil abolished DST in 2019, so a
# constant offset is exact — and a scene set for "22:30" must mean 22:30 on the
# clock in the house, not in whatever timezone the machine happens to be in.
LOCAL_TZ = timezone(timedelta(hours=-LOCAL_UTC_OFFSET_HOURS))


@op
def check_and_trigger_scenes_op(context: OpExecutionContext) -> dict:
    """Fires every scene whose scheduled minute is now."""
    now_local = datetime.now(LOCAL_TZ)
    dry_run = scenes_dry_run_default()

    scenes = load_scenes()
    due = [scene for scene in scenes if scene_is_due(scene, now_local)]

    if not due:
        context.log.debug(
            f"No scenes due at {now_local:%Y-%m-%d %H:%M} ({len(scenes)} stored)."
        )
        return {"checked": len(scenes), "triggered": 0, "dry_run": dry_run, "results": []}

    if dry_run:
        context.log.info(
            f"{len(due)} scene(s) due at {now_local:%H:%M}, running in DRY RUN. "
            f"Set {'SCENE_EXECUTION_DRY_RUN'}=0 to let scheduled scenes actuate devices."
        )

    results = []
    for scene in due:
        context.log.info(f"Triggering scene {scene.get('name')!r} (dry_run={dry_run}).")
        outcome = run_scene(scene, dry_run=dry_run)
        for entry in outcome["results"]:
            if entry.get("error"):
                context.log.warning(
                    f"  {entry['device']}: {entry['action']} failed — {entry['error']}"
                )
            else:
                context.log.info(f"  {entry['device']}: {entry['action']} ok.")
        # Recorded even for a dry run: the point of `last_executed_at` is to
        # stop the same minute from firing twice, which applies either way.
        mark_executed(scene["id"], when=now_local.replace(tzinfo=None))
        results.append(outcome)

    return {
        "checked": len(scenes),
        "triggered": len(due),
        "dry_run": dry_run,
        "results": results,
    }


@job
def scene_scheduler_job():
    check_and_trigger_scenes_op()


scene_execution_schedule = ScheduleDefinition(
    job=scene_scheduler_job,
    cron_schedule="* * * * *",  # every minute — scene times have minute resolution
)
