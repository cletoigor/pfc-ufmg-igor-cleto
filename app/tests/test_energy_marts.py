"""
Tests for app/assets/energy_marts.py.

Same approach as test_marts.py: `gold_energy_metrics` is bound to a Dagster
context and a DuckDBResource, so the SQL it runs is exercised directly against
tiny hand-built fixtures rather than through a live Dagster run.

The energy figures below are all computable on paper — a constant draw over a
known number of minutes — because the integration rule is the part of this mart
most likely to drift silently.
"""
import os

import duckdb
import pandas as pd
import pytest

from app.assets.energy_marts import (
    _CUSUM_BASELINE_QUERY,
    _ENERGY_DAILY_QUERY,
    _ENERGY_HOURLY_QUERY,
    _READINGS_CTE,
    BASELINE_HOLDOUT_DAYS,
    MAX_SAMPLE_HOLD_MINUTES,
    POWER_SCALE,
    VOLTAGE_SCALE,
    gold_energy_metrics,
)
from app.assets.marts import LOCAL_UTC_OFFSET_HOURS, _LOCAL_EVENT_TIME


def _utc_for_local(local: str) -> pd.Timestamp:
    """Staging holds UTC; the marts bucket in local time. Write tests in local."""
    return pd.Timestamp(local) + pd.Timedelta(hours=LOCAL_UTC_OFFSET_HOURS)


def _reading(local_time, code, value, device="device-1", name="Office Outlet"):
    return {
        "device_id": device,
        "device_name": name,
        "code": code,
        "value": str(value),
        "event_time": _utc_for_local(local_time),
        "event_date": str(pd.Timestamp(local_time).date()),
    }


def _write_staging(tmp_path, rows):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    df = pd.DataFrame(rows)
    conn = duckdb.connect(database=":memory:")
    try:
        conn.register("staging_df", df)
        conn.execute(
            f"""
            COPY staging_df TO '{staging_dir}' (
                FORMAT PARQUET, PARTITION_BY (event_date), OVERWRITE_OR_IGNORE 1
            )
            """
        )
    finally:
        conn.close()
    return staging_dir


def _run_hourly(staging_dir):
    staging_glob = os.path.join(str(staging_dir), "**", "*.parquet")
    readings_cte = _READINGS_CTE.format(
        staging_glob=staging_glob, local_event_time=_LOCAL_EVENT_TIME
    ).strip()
    query = _ENERGY_HOURLY_QUERY.format(
        readings_cte=readings_cte,
        power_scale=POWER_SCALE,
        voltage_scale=VOLTAGE_SCALE,
        hold=MAX_SAMPLE_HOLD_MINUTES,
    )
    conn = duckdb.connect(database=":memory:")
    try:
        return conn.execute(query).fetchdf()
    finally:
        conn.close()


def _power_samples(start_local, count, watts, step_minutes=MAX_SAMPLE_HOLD_MINUTES):
    """`count` power readings at a constant draw, on the normal sampling cadence."""
    start = pd.Timestamp(start_local)
    return [
        _reading(start + pd.Timedelta(minutes=step_minutes * i), "cur_power", int(watts * POWER_SCALE))
        for i in range(count)
    ]


# --- energy integration ------------------------------------------------------


def test_a_full_hour_at_constant_draw_integrates_to_power_times_one_hour(tmp_path):
    # Four 15-minute samples at 100 W fill the 10:00 hour exactly: 0.1 kWh.
    staging = _write_staging(tmp_path, _power_samples("2026-01-05 10:00:00", 4, 100.0))

    result = _run_hourly(staging)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["event_hour"] == pd.Timestamp("2026-01-05 10:00:00")
    assert row["energy_kwh"] == pytest.approx(0.1)
    assert row["sample_count"] == 4
    assert row["power_w_mean"] == pytest.approx(100.0)


def test_a_partial_hour_is_only_charged_for_the_minutes_it_ran(tmp_path):
    # Two samples: 10:00 and 10:15, so the draw is held 10:00-10:30 = half an hour.
    staging = _write_staging(tmp_path, _power_samples("2026-01-05 10:00:00", 2, 100.0))

    result = _run_hourly(staging)

    assert result.iloc[0]["energy_kwh"] == pytest.approx(0.05)


def test_energy_is_not_integrated_across_an_off_period(tmp_path):
    """The regression this rule exists for: a device off overnight draws nothing.

    Without the hold cap, the gap between the last evening reading and the first
    morning one would be integrated as though the device had run all night.
    """
    rows = _power_samples("2026-01-05 18:00:00", 2, 100.0)
    rows += _power_samples("2026-01-06 09:00:00", 2, 100.0)
    staging = _write_staging(tmp_path, rows)

    result = _run_hourly(staging)

    assert result["energy_kwh"].sum() == pytest.approx(0.1)  # 0.05 + 0.05, not 15 hours
    assert set(result["event_hour"]) == {
        pd.Timestamp("2026-01-05 18:00:00"),
        pd.Timestamp("2026-01-06 09:00:00"),
    }


def test_a_hold_crossing_an_hour_boundary_is_split_between_both_hours(tmp_path):
    # A reading at 10:50 held until the 11:05 reading: 10 minutes in the 10:00
    # hour and 5 in the 11:00 hour, at 120 W.
    rows = [
        _reading("2026-01-05 10:50:00", "cur_power", int(120 * POWER_SCALE)),
        _reading("2026-01-05 11:05:00", "cur_power", int(120 * POWER_SCALE)),
    ]
    staging = _write_staging(tmp_path, rows)

    result = _run_hourly(staging).set_index("event_hour")

    hour_10 = result.loc[pd.Timestamp("2026-01-05 10:00:00")]
    hour_11 = result.loc[pd.Timestamp("2026-01-05 11:00:00")]
    assert hour_10["energy_kwh"] == pytest.approx(120 * (10 / 60) / 1000)
    assert hour_11["energy_kwh"] == pytest.approx(120 * (5 / 60) / 1000 + 120 * (15 / 60) / 1000)


def test_a_lone_reading_is_held_for_at_most_one_sampling_interval(tmp_path):
    staging = _write_staging(tmp_path, _power_samples("2026-01-05 10:00:00", 1, 240.0))

    result = _run_hourly(staging)

    expected = 240.0 * (MAX_SAMPLE_HOLD_MINUTES / 60) / 1000
    assert result.iloc[0]["energy_kwh"] == pytest.approx(expected)


# --- scaling and statistics --------------------------------------------------


def test_tuya_scale_factors_are_applied_to_each_datapoint(tmp_path):
    rows = [
        _reading("2026-01-05 10:00:00", "cur_power", 1740),    # 174.0 W
        _reading("2026-01-05 10:00:00", "cur_voltage", 1272),  # 127.2 V
        _reading("2026-01-05 10:00:00", "cur_current", 1450),  # 1450 mA, unscaled
    ]
    staging = _write_staging(tmp_path, rows)

    row = _run_hourly(staging).iloc[0]

    assert row["power_w_mean"] == pytest.approx(174.0)
    assert row["voltage_v_mean"] == pytest.approx(127.2)
    assert row["current_ma_mean"] == pytest.approx(1450.0)


def test_min_max_and_mean_are_reported_per_hour(tmp_path):
    rows = [
        _reading("2026-01-05 10:00:00", "cur_power", int(100 * POWER_SCALE)),
        _reading("2026-01-05 10:15:00", "cur_power", int(200 * POWER_SCALE)),
        _reading("2026-01-05 10:30:00", "cur_power", int(300 * POWER_SCALE)),
    ]
    staging = _write_staging(tmp_path, rows)

    row = _run_hourly(staging).iloc[0]

    assert row["power_w_min"] == pytest.approx(100.0)
    assert row["power_w_max"] == pytest.approx(300.0)
    assert row["power_w_mean"] == pytest.approx(200.0)


def test_switch_events_are_ignored_by_the_energy_mart(tmp_path):
    rows = _power_samples("2026-01-05 10:00:00", 4, 100.0)
    rows.append(_reading("2026-01-05 10:05:00", "switch_1", "true"))
    rows.append(_reading("2026-01-05 10:06:00", "bright_value", "80"))
    staging = _write_staging(tmp_path, rows)

    result = _run_hourly(staging)

    assert result.iloc[0]["sample_count"] == 4
    assert result.iloc[0]["energy_kwh"] == pytest.approx(0.1)


def test_unparseable_values_are_dropped_rather_than_failing_the_mart(tmp_path):
    rows = _power_samples("2026-01-05 10:00:00", 4, 100.0)
    rows.append(_reading("2026-01-05 10:07:00", "cur_power", "n/a"))
    staging = _write_staging(tmp_path, rows)

    result = _run_hourly(staging)

    assert result.iloc[0]["sample_count"] == 4


def test_staging_utc_is_converted_to_local_buckets(tmp_path):
    """Same timezone contract as the other marts: staging UTC in, local out."""
    rows = [
        {
            "device_id": "device-1",
            "device_name": "Office Outlet",
            "code": "cur_power",
            "value": "1000",
            "event_time": pd.Timestamp("2026-01-05 02:30:00"),  # UTC
            "event_date": "2026-01-05",
        }
    ]
    staging = _write_staging(tmp_path, rows)

    result = _run_hourly(staging)

    # 02:30 UTC is 23:30 local on the previous day.
    assert result.iloc[0]["event_hour"] == pd.Timestamp("2026-01-04 23:00:00")


# --- daily rollup and CUSUM baseline ----------------------------------------


def _hourly_frame(rows):
    """Builds a device_power_hourly-shaped frame for the downstream queries."""
    return pd.DataFrame(
        [
            {
                "device_id": "device-1",
                "device_name": "Office Outlet",
                "event_hour": pd.Timestamp(hour),
                "sample_count": 4,
                "power_w_mean": power,
                "power_w_max": power,
                "power_w_min": power,
                "voltage_v_mean": 127.0,
                "voltage_v_max": 127.0,
                "voltage_v_min": 127.0,
                "current_ma_mean": 1000.0,
                "current_ma_max": 1000.0,
                "current_ma_min": 1000.0,
                "energy_kwh": energy,
            }
            for hour, power, energy in rows
        ]
    )


def _run_on_hourly(query, frame, **kwargs):
    conn = duckdb.connect(database=":memory:")
    try:
        conn.register("hourly_fixture", frame)
        return conn.execute(query.format(hourly_table="hourly_fixture", **kwargs)).fetchdf()
    finally:
        conn.close()


def test_daily_rollup_sums_energy_and_keeps_the_peak_hour():
    frame = _hourly_frame(
        [
            ("2026-01-05 09:00:00", 100.0, 0.1),
            ("2026-01-05 10:00:00", 300.0, 0.3),  # the day's peak
            ("2026-01-05 11:00:00", 200.0, 0.2),
        ]
    )

    result = _run_on_hourly(_ENERGY_DAILY_QUERY, frame)

    row = result.iloc[0]
    assert row["event_day"] == pd.Timestamp("2026-01-05")
    assert row["energy_kwh"] == pytest.approx(0.6)
    assert row["power_w_max"] == pytest.approx(300.0)
    assert row["peak_hour"] == pd.Timestamp("2026-01-05 10:00:00")


def test_baseline_uses_the_sample_standard_deviation():
    """Equation 3.2 divides by m-1. The population form would understate sigma0
    and manufacture false alarms, so the denominator is pinned by a test."""
    # Four observations of the same hour-of-day on four different days.
    frame = _hourly_frame(
        [
            ("2026-01-01 10:00:00", 100.0, 1.0),
            ("2026-01-02 10:00:00", 100.0, 2.0),
            ("2026-01-03 10:00:00", 100.0, 3.0),
            ("2026-01-04 10:00:00", 100.0, 4.0),
        ]
    )
    # A later day, outside the baseline window, to give the holdout something
    # to exclude.
    frame = pd.concat(
        [frame, _hourly_frame([("2026-01-30 10:00:00", 100.0, 99.0)])], ignore_index=True
    )

    result = _run_on_hourly(
        _CUSUM_BASELINE_QUERY, frame, holdout=BASELINE_HOLDOUT_DAYS
    )

    row = result[result["hour_of_day"] == 10].iloc[0]
    assert row["n_obs"] == 4
    assert row["mu0"] == pytest.approx(2.5)
    assert row["sigma0"] == pytest.approx(1.2909944, rel=1e-6)   # sample, m-1
    assert row["sigma0"] != pytest.approx(1.1180340, rel=1e-6)   # not population


def test_baseline_excludes_the_most_recent_days():
    """Phase I must describe the process before the period under test."""
    frame = _hourly_frame(
        [
            ("2026-01-01 10:00:00", 100.0, 1.0),
            ("2026-01-02 10:00:00", 100.0, 1.0),
            ("2026-01-03 10:00:00", 100.0, 1.0),
            # Inside the holdout window relative to the latest hour below.
            ("2026-01-28 10:00:00", 900.0, 9.0),
            ("2026-01-30 10:00:00", 900.0, 9.0),
        ]
    )

    result = _run_on_hourly(
        _CUSUM_BASELINE_QUERY, frame, holdout=BASELINE_HOLDOUT_DAYS
    )

    row = result[result["hour_of_day"] == 10].iloc[0]
    assert row["n_obs"] == 3
    assert row["mu0"] == pytest.approx(1.0)


def test_baseline_channels_are_per_hour_of_day():
    frame = _hourly_frame(
        [
            ("2026-01-01 03:00:00", 5.0, 0.005),
            ("2026-01-02 03:00:00", 5.0, 0.005),
            ("2026-01-03 03:00:00", 5.0, 0.005),
            ("2026-01-01 19:00:00", 500.0, 0.5),
            ("2026-01-02 19:00:00", 500.0, 0.5),
            ("2026-01-03 19:00:00", 500.0, 0.5),
            # Recent enough to define "now" for the holdout window, and far
            # enough from the rows above to leave them all inside the baseline.
            ("2026-01-20 12:00:00", 50.0, 0.05),
        ]
    )

    result = _run_on_hourly(
        _CUSUM_BASELINE_QUERY, frame, holdout=BASELINE_HOLDOUT_DAYS
    ).set_index("hour_of_day")

    assert result.loc[3, "mu0"] == pytest.approx(0.005)
    assert result.loc[19, "mu0"] == pytest.approx(0.5)


def test_gold_energy_metrics_is_importable_dagster_asset():
    # As in test_marts.py: the asset itself needs a Dagster context and a
    # DuckDBResource, so this only checks the wiring and leaves the logic to
    # the SQL tests above, which run the very same query templates.
    assert gold_energy_metrics.key.to_user_string() == "gold_energy_metrics"
