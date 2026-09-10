#!/usr/bin/env python3
"""
Regenerates the synthetic raw-log dataset under app/data/raw/.

The Tuya Cloud subscription behind this project has lapsed, so `raw_tuya_logs`
can no longer fetch real device history. This script stands in for that asset:
it writes JSON files in exactly the shape `raw_tuya_logs` produces, so the rest
of the pipeline (`staging_tuya_logs` -> `gold_device_metrics`) runs unmodified
on top of it.

Every record is stamped `ingested_by = "synthetic_seed_script"`, so synthetic
rows stay distinguishable from real ones by a simple query.

Unlike the earlier ad-hoc seed (uniform random events, every device statistically
identical), each device here follows a distinct daily rhythm — office devices on
weekday work hours, the mosquito repellent dusk-to-dawn, the LED strip in the
evening with a brightness ramp. A few "left on overnight" incidents are planted
deliberately so anomaly questions have a real answer to find.

Each device also reports the electrical datapoints a BL0937 smart plug does —
`cur_power`, `cur_voltage`, `cur_current` — every 15 minutes while it is drawing
current, which is what the energy marts and the CUSUM page are built on. One
device carries a small persistent power drift (see POWER_DRIFT_DEVICE) so the
statistical process control page has a genuine anomaly to detect.

Usage:
    python scripts/seed_synthetic_data.py [--days 30] [--seed 20260910]

Then materialize the downstream assets (skipping `raw_tuya_logs`, which needs
live Tuya credentials):

    dagster asset materialize -m app.definitions \\
        --select 'staging_tuya_logs,gold_device_metrics'
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import zlib
from collections import defaultdict
from datetime import datetime, date, time, timedelta, timezone

# The house is in Belo Horizonte (UTC-3). Profiles below are written in local
# wall-clock time and converted on the way out, so the hour-of-day rhythm
# survives into the warehouse instead of being smeared across the date line.
LOCAL_TZ = timezone(timedelta(hours=-3))

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_DIR = os.path.join(_REPO_ROOT, "app")
DEVICE_MAPPING_PATH = os.path.join(_APP_DIR, "device_mapping.json")
RAW_DIR = os.path.join(_APP_DIR, "data", "raw")
STAGING_DIR = os.path.join(_APP_DIR, "data", "staging")
MARTS_DIR = os.path.join(_APP_DIR, "data", "marts")

INGESTED_BY = "synthetic_seed_script"

# --- Electrical measurement model -------------------------------------------
#
# The plugs are BL0937-based Tuya smart plugs, which report three datapoints
# alongside the switch state. Tuya's scaling for this chipset:
#
#   cur_power    0.1 W units  ("1740" -> 174.0 W)
#   cur_voltage  0.1 V units  ("1272" -> 127.2 V)
#   cur_current  mA           ("1450" -> 1450 mA)
#
# The house is served by CEMIG in Belo Horizonte, whose residential
# distribution in Minas Gerais is 127 V (not the 220 V used in much of Brazil).
NOMINAL_VOLTAGE_V = 127.0

# Readings are emitted on this cadence for as long as a device is drawing
# current. Tuya pushes consumption to the cloud roughly hourly, but the plugs
# themselves report the DPs far more often; 15 minutes gives four samples per
# hourly CUSUM channel, which is enough to average without bloating the raw
# JSON.
POWER_SAMPLE_INTERVAL = timedelta(minutes=15)

# Per-device electrical signature while the device is on.
#
#   watts         nominal draw at full output
#   power_factor  cos(phi) — resistive loads sit near 1, the fan motor lower
#   scales_with   a datapoint code (0..100) that modulates the draw, so the
#                 electrical story agrees with the mechanical one instead of
#                 being an independent random walk
#   floor         fraction of nominal drawn at the bottom of that 0..100 range
#                 (an LED driver at 15% brightness still draws more than 15%)
POWER_PROFILES = {
    "Device F - Lamp": {"watts": 11.0, "power_factor": 0.95, "scales_with": None, "floor": 1.0},
    "Device E - Outlet": {"watts": 140.0, "power_factor": 0.92, "scales_with": None, "floor": 1.0},
    "Device D - Fan": {
        "watts": 55.0, "power_factor": 0.82, "scales_with": "fan_speed_percent", "floor": 0.35,
    },
    "Device C - Repellent": {"watts": 5.0, "power_factor": 0.99, "scales_with": None, "floor": 1.0},
    "Device A - LED Strip": {
        "watts": 24.0, "power_factor": 0.90, "scales_with": "bright_value", "floor": 0.15,
    },
    "Device B - Switch": {"watts": 60.0, "power_factor": 0.95, "scales_with": None, "floor": 1.0},
}

# Day-to-day variation in a device's draw. This is the spread the CUSUM Phase I
# baseline measures as sigma0, so the planted drift below is expressed as a
# multiple of it rather than as a bare percentage.
DAY_LEVEL_SPREAD = 0.06     # 6% of nominal, 1 sigma
SAMPLE_NOISE_SPREAD = 0.02  # within-session ripple, deliberately smaller

# Planted power anomaly: the office outlet starts drawing ~10% more than usual
# — a failing power supply, a second monitor left plugged in — for the last
# stretch of the window. At 6% day-to-day spread that is a shift of roughly
# 1.7 sigma: comfortably inside a Shewhart 3-sigma chart's limits, and so
# invisible to one, but a persistent bias that CUSUM accumulates past h=5
# within about a day of readings. That contrast is the argument section 3.3.2
# of the monograph makes for CUSUM, so the demo dataset has to contain it.
POWER_DRIFT_DEVICE = "Device E - Outlet"
POWER_DRIFT_DAYS_AGO = 8
POWER_DRIFT_FACTOR = 1.10

# Device profiles, keyed by the friendly name in device_mapping.json.
#
#   switch_code   the Tuya DP code this device reports its on/off state on
#   sessions      callable(day, rng) -> list of (start_local, end_local) datetimes
#   extras        callable(session_start, session_end, rng) -> list of
#                 (datetime, code, value) auxiliary readings inside the session
#
# `sessions` may return a session whose end falls on the following day; that is
# intentional (the fan and the repellent both run through the night) and the
# downstream interval mart handles it via LEAD over the event stream.


def _jitter(rng: random.Random, minutes: float) -> timedelta:
    return timedelta(minutes=rng.uniform(-minutes, minutes))


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=LOCAL_TZ)


def _is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def _office_lamp_sessions(day: date, rng: random.Random):
    """Weekday desk lamp: morning block, lunch gap, afternoon block."""
    if _is_weekend(day):
        # Occasional weekend catch-up session.
        if rng.random() < 0.15:
            start = _at(day, 14) + _jitter(rng, 90)
            return [(start, start + timedelta(hours=rng.uniform(1.5, 3.5)))]
        return []
    morning_start = _at(day, 8, 30) + _jitter(rng, 20)
    lunch_start = _at(day, 12, 0) + _jitter(rng, 20)
    afternoon_start = _at(day, 13, 15) + _jitter(rng, 20)
    evening_end = _at(day, 18, 30) + _jitter(rng, 40)
    return [(morning_start, lunch_start), (afternoon_start, evening_end)]


def _office_outlet_sessions(day: date, rng: random.Random):
    """Monitor/charger outlet: one uninterrupted weekday block."""
    if _is_weekend(day):
        if rng.random() < 0.2:
            start = _at(day, 15) + _jitter(rng, 90)
            return [(start, start + timedelta(hours=rng.uniform(1, 3)))]
        return []
    start = _at(day, 8, 15) + _jitter(rng, 20)
    end = _at(day, 19, 0) + _jitter(rng, 40)
    return [(start, end)]


def _bedroom_fan_sessions(day: date, rng: random.Random):
    """Runs overnight; hotter stretches make it more likely and faster."""
    heat = _heat_index(day)
    if heat < 0.35:
        return []
    start = _at(day, 22, 15) + _jitter(rng, 40)
    end = _at(day + timedelta(days=1), 6, 10) + _jitter(rng, 30)
    return [(start, end)]


def _bedroom_fan_extras(start: datetime, end: datetime, rng: random.Random):
    """fan_speed_percent set at switch-on, sometimes stepped down overnight."""
    heat = _heat_index(start.date())
    initial = int(40 + heat * 55)
    readings = [(start + timedelta(seconds=30), "fan_speed_percent", str(initial))]
    if rng.random() < 0.6:
        step_at = start + timedelta(hours=rng.uniform(1.5, 3.5))
        if step_at < end:
            readings.append(
                (step_at, "fan_speed_percent", str(max(20, initial - rng.randint(10, 30))))
            )
    return readings


def _mosquito_sessions(day: date, rng: random.Random):
    """Dusk to dawn, nearly every night."""
    if rng.random() < 0.08:
        return []
    start = _at(day, 18, 30) + _jitter(rng, 25)
    end = _at(day + timedelta(days=1), 5, 45) + _jitter(rng, 25)
    return [(start, end)]


def _led_strip_sessions(day: date, rng: random.Random):
    """Ambient evening lighting."""
    if rng.random() < 0.12:
        return []
    start = _at(day, 19, 10) + _jitter(rng, 30)
    end = _at(day, 23, 20) + _jitter(rng, 40)
    return [(start, end)]


def _led_strip_extras(start: datetime, end: datetime, rng: random.Random):
    """Brightness ramps down over the evening."""
    readings = []
    level = rng.randint(80, 100)
    steps = rng.randint(2, 4)
    span = (end - start) / (steps + 1)
    for i in range(steps):
        at = start + span * i + timedelta(seconds=30)
        readings.append((at, "bright_value", str(level)))
        level = max(15, level - rng.randint(15, 30))
    return readings


def _living_room_sessions(day: date, rng: random.Random):
    """Evenings, plus weekend daytime."""
    sessions = []
    if _is_weekend(day) and rng.random() < 0.7:
        start = _at(day, 10, 0) + _jitter(rng, 60)
        sessions.append((start, start + timedelta(hours=rng.uniform(2, 4))))
    if rng.random() < 0.9:
        start = _at(day, 18, 45) + _jitter(rng, 30)
        end = _at(day, 22, 40) + _jitter(rng, 40)
        sessions.append((start, end))
    return sessions


def _heat_index(day: date) -> float:
    """Deterministic 0..1 'how warm was it' signal, smooth across the month.

    Derived from the ordinal date rather than the RNG so the same day always
    scores the same regardless of call order — the fan's session decision and
    its speed reading have to agree with each other.
    """
    import math

    seasonal = 0.5 + 0.35 * math.sin(day.toordinal() / 6.0)
    wobble = ((day.toordinal() * 2654435761) % 1000) / 1000.0
    return max(0.0, min(1.0, 0.7 * seasonal + 0.3 * wobble))


def _day_level_watts(device_name: str, day: date, base_seed: int, drift_days: set) -> float:
    """The device's average draw for one local day, before within-session noise.

    Drawn from a seed derived from (base_seed, device, day) rather than from the
    shared session RNG, so power generation cannot shift the random sequence the
    on/off sessions are drawn from — the switch-event stream stays byte-for-byte
    identical to the dataset that existed before power was modelled — and a
    day's level is the same however many times it is asked for.
    """
    profile = POWER_PROFILES[device_name]
    seed = (base_seed * 1000003) ^ (day.toordinal() * 131) ^ zlib.crc32(device_name.encode())
    level = profile["watts"] * (1 + random.Random(seed).gauss(0, DAY_LEVEL_SPREAD))
    if device_name == POWER_DRIFT_DEVICE and day in drift_days:
        level *= POWER_DRIFT_FACTOR
    return max(0.1, level)


def _modulation_at(extras: list, code: str, at: datetime, floor: float) -> float:
    """Scales the draw by the most recent 0..100 reading of `code` before `at`.

    A fan on 40% or a strip dimmed to 20% genuinely draws less, but not
    proportionally less — both have a fixed overhead — hence the floor.
    """
    level = None
    for dt, reading_code, value in extras:
        if reading_code == code and dt <= at:
            level = float(value)
    if level is None:
        return 1.0
    return floor + (1.0 - floor) * max(0.0, min(100.0, level)) / 100.0


def _power_readings(
    device_name: str,
    start: datetime,
    end: datetime,
    extras: list,
    base_seed: int,
    drift_days: set,
):
    """Emits (datetime, code, value) triples of cur_power/cur_voltage/cur_current.

    The three are not sampled independently: voltage wanders around the grid
    nominal, power follows the device's own profile, and current is *derived*
    from the two via P = V * I * cos(phi). A reviewer who checks that the three
    columns are physically consistent should find that they are.
    """
    profile = POWER_PROFILES[device_name]
    scales_with = profile["scales_with"]
    device_salt = zlib.crc32(device_name.encode())
    readings = []

    at = start
    while at < end:
        day_level = _day_level_watts(device_name, at.date(), base_seed, drift_days)
        # Per-sample RNG, seeded by the timestamp, so a sample's value does not
        # depend on how many samples happened to be drawn before it.
        srng = random.Random((base_seed * 31 + int(at.timestamp())) ^ device_salt)

        modulation = 1.0
        if scales_with:
            modulation = _modulation_at(extras, scales_with, at, profile["floor"])

        power_w = max(0.1, day_level * modulation * (1 + srng.gauss(0, SAMPLE_NOISE_SPREAD)))
        voltage_v = NOMINAL_VOLTAGE_V * (1 + srng.gauss(0, 0.012))
        current_ma = power_w / (voltage_v * profile["power_factor"]) * 1000

        readings.append((at, "cur_power", str(round(power_w * 10))))
        readings.append((at, "cur_voltage", str(round(voltage_v * 10))))
        readings.append((at, "cur_current", str(round(current_ma))))
        at += POWER_SAMPLE_INTERVAL

    return readings


PROFILES = {
    "Device F - Lamp": {
        "switch_code": "switch_led",
        "sessions": _office_lamp_sessions,
        "extras": None,
    },
    "Device E - Outlet": {
        "switch_code": "switch_1",
        "sessions": _office_outlet_sessions,
        "extras": None,
    },
    "Device D - Fan": {
        "switch_code": "switch",
        "sessions": _bedroom_fan_sessions,
        "extras": _bedroom_fan_extras,
    },
    "Device C - Repellent": {
        "switch_code": "switch_1",
        "sessions": _mosquito_sessions,
        "extras": None,
    },
    "Device A - LED Strip": {
        "switch_code": "switch_led",
        "sessions": _led_strip_sessions,
        "extras": _led_strip_extras,
    },
    "Device B - Switch": {
        "switch_code": "switch_1",
        "sessions": _living_room_sessions,
        "extras": None,
    },
}

# Planted anomalies: the office lamp forgotten overnight. Expressed as an offset
# in days back from the last generated day, so they always land inside the
# window and stay in the "last two weeks" range that demo questions ask about.
OVERNIGHT_ANOMALY_DAYS_AGO = (3, 9, 16)
ANOMALY_DEVICE = "Device F - Lamp"


def load_device_mapping() -> dict:
    with open(DEVICE_MAPPING_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_events(
    device_name: str,
    days: list[date],
    rng: random.Random,
    anomaly_days: set[date],
    now_local: datetime,
    base_seed: int,
    drift_days: set[date],
):
    """Returns a list of (datetime_utc, code, value) for one device.

    Sessions on the final day routinely run into the next morning (the fan and
    the repellent both do), so events are clipped at `now_local`: a warehouse
    holding readings from the future is an obvious tell, and it would make the
    dashboard's "latest event" tile show a timestamp that hasn't happened yet.
    """
    profile = PROFILES[device_name]
    switch_code = profile["switch_code"]
    events = []

    for day in days:
        sessions = profile["sessions"](day, rng)

        # Anomaly: stretch the day's last session through to the next morning.
        if device_name == ANOMALY_DEVICE and day in anomaly_days and sessions:
            start, _ = sessions[-1]
            sessions[-1] = (start, _at(day + timedelta(days=1), 7, 20) + _jitter(rng, 25))

        for start, end in sessions:
            if end <= start:
                continue
            events.append((start, switch_code, "true"))
            events.append((end, switch_code, "false"))
            extras = profile["extras"](start, end, rng) if profile["extras"] else []
            events.extend(extras)
            # Electrical readings come last and off a separate RNG, so adding
            # them leaves the session/extras draws above untouched.
            events.extend(
                _power_readings(device_name, start, end, extras, base_seed, drift_days)
            )

    events = [e for e in events if e[0] <= now_local]
    events.sort(key=lambda e: e[0])
    return [(dt.astimezone(timezone.utc), code, value) for dt, code, value in events]


def write_raw_files(device_id: str, events, ingestion_time_utc: str) -> int:
    """Writes events grouped by UTC day, mirroring raw_tuya_logs' file layout."""
    by_day = defaultdict(list)
    for dt_utc, code, value in events:
        by_day[dt_utc.date()].append(
            {
                "code": code,
                "value": value,
                "event_time": int(dt_utc.timestamp() * 1000),
                "device_id": device_id,
                "ingestion_timestamp_utc": ingestion_time_utc,
                "ingested_by": INGESTED_BY,
            }
        )

    written = 0
    for day, records in sorted(by_day.items()):
        out_dir = os.path.join(RAW_DIR, device_id, day.strftime("%Y-%m-%d"))
        os.makedirs(out_dir, exist_ok=True)
        first = datetime.fromtimestamp(records[0]["event_time"] / 1000, timezone.utc)
        file_name = f"{device_id}_{first.strftime('%Y%m%d%H%M%S')}_logs.json"
        with open(os.path.join(out_dir, file_name), "w", encoding="utf-8") as f:
            json.dump(records, f, indent=4, ensure_ascii=False)
        written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30, help="days of history to generate")
    parser.add_argument("--seed", type=int, default=20260910, help="RNG seed (reproducible)")
    parser.add_argument(
        "--keep-derived",
        action="store_true",
        help="leave data/staging and data/marts in place (default: clear them, "
             "so stale partitions from a previous seed can't survive)",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    mapping = load_device_mapping()
    name_to_id = {name: device_id for device_id, name in mapping.items()}

    missing = set(PROFILES) - set(name_to_id)
    if missing:
        raise SystemExit(f"device_mapping.json has no entry for: {', '.join(sorted(missing))}")

    now_local = datetime.now(LOCAL_TZ)
    today_local = now_local.date()
    days = [today_local - timedelta(days=n) for n in range(args.days - 1, -1, -1)]
    anomaly_days = {today_local - timedelta(days=n) for n in OVERNIGHT_ANOMALY_DAYS_AGO}
    drift_days = {today_local - timedelta(days=n) for n in range(POWER_DRIFT_DAYS_AGO + 1)}

    # Wipe previous output so a re-seed is a clean replacement, not a merge.
    if os.path.isdir(RAW_DIR):
        shutil.rmtree(RAW_DIR)
    if not args.keep_derived:
        for derived in (STAGING_DIR, MARTS_DIR):
            if os.path.isdir(derived):
                shutil.rmtree(derived)

    ingestion_time_utc = datetime.now(timezone.utc).isoformat()

    total_events = 0
    total_files = 0
    for device_name in PROFILES:
        device_id = name_to_id[device_name]
        events = build_events(
            device_name, days, rng, anomaly_days, now_local, args.seed, drift_days
        )
        files = write_raw_files(device_id, events, ingestion_time_utc)
        total_events += len(events)
        total_files += files
        print(f"  {device_name:<20} {len(events):>5} events  ->  {files} files")

    print(
        f"\nWrote {total_events} events across {total_files} files to {RAW_DIR}\n"
        f"Window: {days[0]} .. {days[-1]} (local {LOCAL_TZ})\n"
        f"Planted overnight anomalies on {ANOMALY_DEVICE}: "
        f"{', '.join(str(d) for d in sorted(anomaly_days))}\n"
        f"Planted power drift on {POWER_DRIFT_DEVICE}: "
        f"x{POWER_DRIFT_FACTOR} from {min(drift_days)} onwards "
        f"(~{(POWER_DRIFT_FACTOR - 1) / DAY_LEVEL_SPREAD:.1f} sigma — invisible to a "
        f"3-sigma Shewhart chart, detected by CUSUM)\n\n"
        "Next: dagster asset materialize -m app.definitions "
        "--select 'staging_tuya_logs,gold_device_metrics'"
    )


if __name__ == "__main__":
    main()
