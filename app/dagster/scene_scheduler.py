from dagster import op, job, ScheduleDefinition, Definitions, EnvVar, resource as dagster_resource
from datetime import datetime, time as dt_time, timezone
import json
import os

# Assuming 'app' is on the PYTHONPATH or discoverable by Dagster,
# e.g., when running 'dagster dev' from the project root.
from app.streamlit.utils.tuya_api_helpers import execute_scene, get_tuya_openapi


# Path to the scenes file
# Default assumes this scene_scheduler.py is in app/dagster/
# So, os.path.dirname(__file__) is app/dagster/
# ".." goes to app/
# "data" goes into app/data/
SCHEDULED_SCENES_FILE_PATH_DEFAULT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "streamlit", "app", "data", "scheduled_scenes.json")
)
SCHEDULED_SCENES_FILE_ENV_VAR = "SCHEDULED_SCENES_FILE_PATH" # Store the env var name

# EnvVar definition without default_value
SCHEDULED_SCENES_FILE = EnvVar(SCHEDULED_SCENES_FILE_ENV_VAR)


# Helper to convert day names to weekday numbers (Monday=0, Sunday=6)
DAY_MAP = {"Segunda": 0, "Terça": 1, "Quarta": 2, "Quinta": 3, "Sexta": 4, "Sábado": 5, "Domingo": 6}

@dagster_resource
def tuya_api_resource(context):
    """
    Dagster resource to ensure Tuya API is configured and provide a client.
    """
    access_id = os.getenv("ACCESS_ID")
    access_key = os.getenv("ACCESS_SECRET") # Note: Tuya often calls this "secret" or "key"
    api_endpoint = os.getenv("API_ENDPOINT")

    if not (access_id and access_key and api_endpoint):
        context.log.error("Tuya API environment variables (ACCESS_ID, ACCESS_SECRET, API_ENDPOINT) not fully set for Dagster.")
        raise Exception("Tuya API credentials not configured for Dagster.")
    
    try:
        openapi = get_tuya_openapi() # Uses env vars internally
        openapi.connect() 
        context.log.info("Tuya API connection test successful for Dagster resource.")
        return openapi # Could return the client if ops need it directly
    except Exception as e:
        context.log.error(f"Tuya API connection test failed for Dagster resource: {e}")
        raise

@op(required_resource_keys={"tuya_api"})
def check_and_trigger_scenes_op(context):
    """
    Checks scheduled scenes and triggers them if they are due.
    """
    # Retrieve the file path using os.getenv to provide a default,
    # as EnvVar's default_value is not supported in this Dagster version.
    scenes_file_path = os.getenv(SCHEDULED_SCENES_FILE_ENV_VAR, SCHEDULED_SCENES_FILE_PATH_DEFAULT)
    context.log.info(f"Checking for scheduled scenes in: {scenes_file_path}")

    if not os.path.exists(scenes_file_path):
        context.log.info(f"Scheduled scenes file not found at '{scenes_file_path}'. No scenes to check.")
        return

    try:
        with open(scenes_file_path, 'r') as f:
            saved_scenes = json.load(f)
    except json.JSONDecodeError:
        context.log.error(f"Error decoding JSON from {scenes_file_path}.")
        return
    except Exception as e:
        context.log.error(f"Error reading scenes file '{scenes_file_path}': {e}")
        return

    # IMPORTANT: Timezone handling. Assume current time is UTC for robust comparison.
    # Scheduled times from UI are naive; assume they are local to where Streamlit runs (e.g., user's local).
    # This needs a proper timezone strategy. For now, let's assume naive comparison
    # and highlight this as a major point for improvement.
    # A better way: Store scheduled times in UTC or with timezone info.
    now = datetime.now() # This is server's local time where Dagster daemon runs.
    context.log.info(f"Current time (Dagster server local): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    triggered_scenes_count = 0
    scenes_to_persist = saved_scenes.copy() # To manage updates for one-time triggers

    for scene_name, scene_data in saved_scenes.items():
        schedule = scene_data.get("schedule")
        actions = scene_data.get("actions")

        if not schedule or not actions or not schedule.get("time"):
            context.log.debug(f"Scene '{scene_name}' is missing schedule/actions/time, skipping.")
            continue

        try:
            scheduled_time_str = schedule["time"] # "HH:MM"
            scheduled_dt_time = dt_time.fromisoformat(scheduled_time_str)
            
            scheduled_days_names = schedule.get("days", []) 
            is_recurring = schedule.get("recurring", False)
            was_triggered_one_time = scene_data.get("triggered_one_time", False)

            if not is_recurring and was_triggered_one_time:
                context.log.debug(f"Non-recurring scene '{scene_name}' already triggered. Skipping.")
                continue

            time_matches = (now.hour == scheduled_dt_time.hour and now.minute == scheduled_dt_time.minute)
            if not time_matches:
                continue

            day_matches = False
            if not scheduled_days_names: # No specific days selected
                if not is_recurring: # One-time, any day (triggers if time matches today)
                    day_matches = True 
                # else: recurring but no days? Ambiguous. Treat as "doesn't match specific days".
            else: # Specific days selected
                current_day_of_week_num = now.weekday() # Monday is 0 and Sunday is 6
                if any(DAY_MAP.get(day_name) == current_day_of_week_num for day_name in scheduled_days_names):
                    day_matches = True
            
            if not day_matches:
                continue

            context.log.info(f"Time and day match for scene: '{scene_name}'. Triggering.")
            
            # Execute the scene
            # The 'execute_scene' function expects actions directly.
            if execute_scene(actions): 
                context.log.info(f"Scene '{scene_name}' executed successfully.")
                triggered_scenes_count += 1
                if not is_recurring:
                    # Mark as triggered for non-recurring scenes
                    if scene_name in scenes_to_persist: # Should always be true
                       scenes_to_persist[scene_name]["triggered_one_time"] = True
            else:
                context.log.error(f"Failed to execute scene '{scene_name}'.")

        except Exception as e:
            context.log.error(f"Error processing schedule for scene '{scene_name}': {e}")
            continue
            
    # Persist changes if any non-recurring scenes were triggered
    if scenes_to_persist != saved_scenes:
        try:
            with open(scenes_file_path, 'w') as f:
                json.dump(scenes_to_persist, f, indent=2)
            context.log.info("Updated scenes file with one-time trigger status.")
        except Exception as e:
            context.log.error(f"Failed to update scenes file with one-time trigger status: {e}")

    if triggered_scenes_count > 0:
        context.log.info(f"Finished scene check. Triggered {triggered_scenes_count} scenes.")
    else:
        context.log.info("Finished scene check. No scenes were due at this minute.")

@job
def scene_scheduler_job():
    check_and_trigger_scenes_op()

scene_execution_schedule = ScheduleDefinition(
    job=scene_scheduler_job,
    cron_schedule="*/1 * * * *",  # Every minute
    description="Checks and executes scheduled scenes.",
)

# To make these definitions available to Dagster, add them to your main Definitions object
# e.g., in your workspace.yaml or a central definitions file:
# dagster_defs = Definitions(
#     assets=[...],
#     jobs=[..., scene_scheduler_job],
#     schedules=[..., scene_execution_schedule],
#     resources={..., "tuya_api": tuya_api_resource}
# )
