import os
import json
import datetime
import random
import time

# Configuration
DEVICE_ID = "ebcf1234567890abcdef12"
DEVICE_NAME = "controle de tomadas"
OUTPUT_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

START_DATE = datetime.date(2025, 4, 18)
END_DATE = datetime.date(2025, 6, 17)

# Power profile (mimicking "Hack Sala" with 10x scaling for cur_power)
# Values are in Watts * 10, as per data_helpers.py scaling
# Example: 1500 means 150W, 500 means 50W
HOURLY_POWER_PROFILE_SCALED = {
    0: 500,   # 00:00 - 00:59 (50W)
    1: 500,   # 01:00 - 01:59 (50W)
    2: 500,   # 02:00 - 02:59 (50W)
    3: 500,   # 03:00 - 03:59 (50W)
    4: 500,   # 04:00 - 04:59 (50W)
    5: 500,   # 05:00 - 05:59 (50W)
    6: 800,   # 06:00 - 06:59 (80W) - Start of activity
    7: 1200,  # 07:00 - 07:59 (120W)
    8: 1500,  # 08:00 - 08:59 (150W)
    9: 1500,  # 09:00 - 09:59 (150W)
    10: 1200, # 10:00 - 10:59 (120W)
    11: 1000, # 11:00 - 11:59 (100W)
    12: 1000, # 12:00 - 12:59 (100W)
    13: 1200, # 13:00 - 13:59 (120W)
    14: 1500, # 14:00 - 14:59 (150W)
    15: 1500, # 15:00 - 15:59 (150W)
    16: 1200, # 16:00 - 16:59 (120W)
    17: 1000, # 17:00 - 17:59 (100W)
    18: 1500, # 18:00 - 18:59 (150W) - Peak evening activity
    19: 1800, # 19:00 - 19:59 (180W)
    20: 1500, # 20:00 - 20:59 (150W)
    21: 1200, # 21:00 - 21:59 (120W)
    22: 800,  # 22:00 - 22:59 (80W)
    23: 500   # 23:00 - 23:59 (50W) - Winding down
}

# Voltage parameters (V*10)
VOLTAGE_MEAN = 1200
VOLTAGE_VARIATION = 50

# Data generation parameters
MINUTES_PER_DATA_POINT = 2
MINUTES_PER_ADD_ELE_REPORT = 60

# Global state for cycle continuity across hours/days
# Initialize based on an arbitrary start point (e.g., midnight of START_DATE)
# to ensure cycle is deterministic.
initial_datetime_for_cycle_calc = datetime.datetime(START_DATE.year, START_DATE.month, START_DATE.day, 0, 0, 0, tzinfo=datetime.timezone.utc)

# Global state for add_ele continuity
# This needs to be managed carefully if we want `add_ele` to be truly continuous
# across hourly files. For simplicity in this script, `add_ele` will be calculated
# based on the hour's consumption and reported once per hour if applicable.
# A more robust solution would pass accumulated_wh state between calls.
# For this version, `add_ele` will represent the sum of Wh for that hour's file,
# reported at the end of the hour's data generation.

def generate_data_for_hour(target_date, target_hour, device_id):
    log_entries = []
    
    start_of_hour_dt = datetime.datetime(target_date.year, target_date.month, target_date.day, target_hour, 0, 0, 0, tzinfo=datetime.timezone.utc)
    end_of_hour_dt = start_of_hour_dt + datetime.timedelta(hours=1)
    
    current_time_dt = start_of_hour_dt
    
    hourly_accumulated_wh = 0.0

    while current_time_dt < end_of_hour_dt:
        event_time_ms = int(current_time_dt.timestamp() * 1000)
        # Use a slightly offset ingestion_timestamp_utc for each batch of logs if desired, or keep it fixed per file.
        # For simplicity, using current generation time.
        ingestion_ts_utc = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='microseconds')

        # Get power from the hourly profile, which is already scaled by 10
        current_power_scaled = HOURLY_POWER_PROFILE_SCALED.get(target_hour, 0) 
        
        current_voltage_scaled = random.randint(VOLTAGE_MEAN - VOLTAGE_VARIATION, VOLTAGE_MEAN + VOLTAGE_VARIATION)
        
        # Calculate current based on scaled power and scaled voltage
        # (current_power_scaled / 10.0) gives actual Watts
        # (current_voltage_scaled / 10.0) gives actual Volts
        # current_milli_amps = (actual_watts / actual_volts) * 1000
        if current_voltage_scaled == 0:
            current_milli_amps = 0
        else:
            current_milli_amps = int(((current_power_scaled / 10.0) / (current_voltage_scaled / 10.0)) * 1000)

        log_entries.append({
            "code": "cur_power", "event_time": event_time_ms, "value": str(current_power_scaled),
            "device_id": device_id, "ingestion_timestamp_utc": ingestion_ts_utc,
            "ingested_by": "manual_test_data_script_v2"
        })
        log_entries.append({
            "code": "cur_voltage", "event_time": event_time_ms, "value": str(current_voltage_scaled),
            "device_id": device_id, "ingestion_timestamp_utc": ingestion_ts_utc,
            "ingested_by": "manual_test_data_script_v2"
        })
        log_entries.append({
            "code": "cur_current", "event_time": event_time_ms, "value": str(current_milli_amps),
            "device_id": device_id, "ingestion_timestamp_utc": ingestion_ts_utc,
            "ingested_by": "manual_test_data_script_v2"
        })
        log_entries.append({ # switch_1 is always true
            "code": "switch_1", "event_time": event_time_ms, "value": "true",
            "device_id": device_id, "ingestion_timestamp_utc": ingestion_ts_utc,
            "ingested_by": "manual_test_data_script_v2"
        })

        # Accumulate actual Wh (current_power_scaled / 10.0 gives actual Watts)
        hourly_accumulated_wh += (current_power_scaled / 10.0) * (MINUTES_PER_DATA_POINT / 60.0)
        
        current_time_dt += datetime.timedelta(minutes=MINUTES_PER_DATA_POINT)

    # Add one 'add_ele' record at the end of the hour's data points
    # This represents the total incremental energy for this hour.
    # Use the timestamp of the last data point for this add_ele record.
    if log_entries: # Ensure there are entries before trying to get the last event_time
        last_event_time_ms = log_entries[-1]["event_time"] 
        final_ingestion_ts_utc = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='microseconds')
        log_entries.append({
            "code": "add_ele", "event_time": last_event_time_ms + 1, # Slightly after last event
            "value": str(int(round(hourly_accumulated_wh))),
            "device_id": device_id, "ingestion_timestamp_utc": final_ingestion_ts_utc,
            "ingested_by": "manual_test_data_script_v2"
        })
        
    return log_entries

def main():
    device_output_dir = os.path.join(OUTPUT_BASE_DIR, DEVICE_ID)
    os.makedirs(device_output_dir, exist_ok=True)

    current_date_tracker = START_DATE
    while current_date_tracker <= END_DATE:
        date_specific_dir = os.path.join(device_output_dir, current_date_tracker.strftime('%Y-%m-%d'))
        os.makedirs(date_specific_dir, exist_ok=True)
        
        for hour in range(24):
            print(f"Generating data for {DEVICE_ID} on {current_date_tracker.strftime('%Y-%m-%d')} at {hour:02d}:00...")
            
            hourly_log_entries = generate_data_for_hour(current_date_tracker, hour, DEVICE_ID)
            
            if not hourly_log_entries:
                print(f"No data generated for {hour:02d}:00. Skipping file creation.")
                continue

            # Sort by event_time
            hourly_log_entries.sort(key=lambda x: x["event_time"])
            
            # Filename: deviceid_YYYYMMDDHHMMSS_logs.json
            # Using HH0000 for MMSS part for hourly logs.
            filename_ts_part = f"{current_date_tracker.strftime('%Y%m%d')}{hour:02d}0000"
            log_filename = f"{DEVICE_ID}_{filename_ts_part}_logs.json"
            log_filepath = os.path.join(date_specific_dir, log_filename)
            
            with open(log_filepath, 'w') as f:
                json.dump(hourly_log_entries, f, indent=4)
                
            # print(f"Saved to {log_filepath}") # Optional: reduce verbosity
            
        current_date_tracker += datetime.timedelta(days=1)

    print(f"Data generation complete for device {DEVICE_ID}.")
    print(f"Output directory: {device_output_dir}")

if __name__ == "__main__":
    main()
