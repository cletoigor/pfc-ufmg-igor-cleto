"""
Payload builders for the energy pages of the web UI.

A sibling of `data_access.py` rather than more of it: this module answers "how
much did it draw" from the energy marts, while `data_access.py` answers "when
was it on" from the duration marts. Both are framework-free — no Starlette, no
Streamlit — so the API, the dashboard and the tests can all import them, and
both go through `data_access.load_metrics()` so the warehouse -> marts ->
staging fallback has exactly one definition.

Every builder follows the conventions the API contract already sets:
timestamps are local wall-clock ISO strings with no timezone suffix, an absent
data layer produces an `empty: true` payload rather than an exception, and
nothing here raises.
"""
from __future__ import annotations

import math
from datetime import timedelta

import pandas as pd

from app.analysis.cusum import DEFAULT_H, DEFAULT_K, multichannel_cusum
from app.api.data_access import _iso, load_device_mapping, load_metrics

# The dataset is a fixed historical window, so "today" means the most recent
# day present in the data, not the wall-clock date. Anchoring to
# `datetime.now()` would make every "today" tile read zero — see the module
# docstring in data_access.py for the same distinction.
DAY_KEYS = (("today", 1), ("last_7_days", 7), ("this_month", 30))

# Outlier lists exist to show the shape of a distribution, not to enumerate it.
MAX_OUTLIERS_RETURNED = 60


def _empty(reason: str, **extra) -> dict:
    return {"empty": True, "empty_reason": reason, "source": None, **extra}


def _latest(frame: pd.DataFrame | None, column: str):
    if frame is None or frame.empty or column not in frame.columns:
        return None
    value = pd.Timestamp(frame[column].max())
    return None if pd.isna(value) else value


def _window(frame: pd.DataFrame, column: str, days, latest) -> pd.DataFrame:
    """Trims a frame to the last `days` days, measured back from `latest`."""
    if days is None or frame.empty or latest is None:
        return frame
    start = pd.Timestamp(latest).normalize() - pd.Timedelta(days=days - 1)
    return frame[pd.to_datetime(frame[column]) >= start]


def _apply_window(frame: pd.DataFrame, column: str, days, start, end, latest) -> pd.DataFrame:
    """Trims a frame to either an explicit date range or a trailing window.

    Two shapes are needed because the monograph's period filter offers both:
    "Last 7 days" is a trailing window, while "Yesterday" and a custom range are
    absolute. An explicit `start`/`end` wins over `days` when both are given.

    Both bounds are inclusive whole local days — `end` is pushed to the end of
    its day, so selecting a single date returns that date's readings rather
    than only those at exactly midnight.
    """
    if frame.empty:
        return frame
    if start is None and end is None:
        return _window(frame, column, days, latest)

    times = pd.to_datetime(frame[column])
    mask = pd.Series(True, index=frame.index)
    if start is not None:
        mask &= times >= pd.Timestamp(start).normalize()
    if end is not None:
        mask &= times < pd.Timestamp(end).normalize() + pd.Timedelta(days=1)
    return frame[mask]


def _window_description(days, start, end) -> dict:
    return {
        "days": None if (start or end) else days,
        "start": _iso(pd.Timestamp(start).normalize()) if start else None,
        "end": _iso(pd.Timestamp(end).normalize()) if end else None,
    }


def _filter_devices(frame: pd.DataFrame, devices) -> pd.DataFrame:
    if not devices or frame.empty:
        return frame
    return frame[frame["device_name"].isin(set(devices))]


def _round(value, digits=3):
    """JSON-safe rounding: NaN and infinity are not valid JSON numbers."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, digits)


def boxplot_stats(values) -> dict | None:
    """Five-number summary plus Tukey fences, for the distribution charts.

    Computed here rather than in the browser: pandas already has the quantile
    machinery, and shipping quartiles instead of thousands of raw readings keeps
    the payload small.
    """
    series = pd.Series(list(values), dtype="float64").dropna()
    if series.empty:
        return None

    q1, median, q3 = (float(series.quantile(q)) for q in (0.25, 0.5, 0.75))
    iqr = q3 - q1
    lower_fence, upper_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = series[(series >= lower_fence) & (series <= upper_fence)]
    outliers = series[(series < lower_fence) | (series > upper_fence)]

    if len(outliers) > MAX_OUTLIERS_RETURNED:
        # Keep the extremes — they are the ones worth seeing — and thin the rest.
        outliers = pd.concat(
            [
                outliers.nsmallest(MAX_OUTLIERS_RETURNED // 2),
                outliers.nlargest(MAX_OUTLIERS_RETURNED // 2),
            ]
        )

    return {
        "count": int(series.size),
        "min": _round(series.min(), 2),
        "q1": _round(q1, 2),
        "median": _round(median, 2),
        "q3": _round(q3, 2),
        "max": _round(series.max(), 2),
        "whisker_low": _round(inside.min() if not inside.empty else series.min(), 2),
        "whisker_high": _round(inside.max() if not inside.empty else series.max(), 2),
        "mean": _round(series.mean(), 2),
        "outliers": [_round(v, 2) for v in sorted(outliers.unique())],
    }


def _energy_totals(daily: pd.DataFrame, latest_day) -> list[dict]:
    """kWh over the monograph's three reference periods."""
    totals = []
    for key, days in DAY_KEYS:
        window = _window(daily, "event_day", days, latest_day)
        totals.append(
            {
                "key": key,
                "days": days,
                "energy_kwh": _round(window["energy_kwh"].sum() if not window.empty else 0.0),
            }
        )
    return totals


def _hourly_profile(hourly: pd.DataFrame) -> list[dict]:
    """Mean power by hour of day — the device's typical shape of a day.

    Hours the device never ran in are returned explicitly with a null rather
    than omitted, so the chart draws a 24-hour axis rather than a ragged one.
    """
    if hourly.empty:
        return [{"hour": hour, "power_w": None, "energy_kwh": 0.0} for hour in range(24)]

    frame = hourly.copy()
    frame["hour"] = pd.to_datetime(frame["event_hour"]).dt.hour
    grouped = frame.groupby("hour").agg(
        power_w=("power_w_mean", "mean"),
        energy_kwh=("energy_kwh", "mean"),
    )
    return [
        {
            "hour": hour,
            "power_w": _round(grouped.loc[hour, "power_w"], 1) if hour in grouped.index else None,
            "energy_kwh": _round(grouped.loc[hour, "energy_kwh"], 4) if hour in grouped.index else 0.0,
        }
        for hour in range(24)
    ]


# ---------------------------------------------------------------------------
# House summary
# ---------------------------------------------------------------------------


def build_house_summary(days=7, devices=None, start=None, end=None) -> dict:
    """The consolidated view: totals, biggest consumers, whole-house day shape."""
    metrics = load_metrics()
    daily = metrics.get("power_daily")
    hourly = metrics.get("power_hourly")

    if daily is None or daily.empty:
        return _empty(
            "No energy data yet. Run scripts/seed_synthetic_data.py, then "
            "materialize staging_tuya_logs and gold_energy_metrics."
        )

    latest_day = _latest(daily, "event_day")
    selected_daily = _filter_devices(daily, devices)
    windowed = _apply_window(selected_daily, "event_day", days, start, end, latest_day)

    by_device = (
        windowed.groupby("device_name")["energy_kwh"].sum().sort_values(ascending=False)
        if not windowed.empty
        else pd.Series(dtype="float64")
    )
    total_kwh = float(by_device.sum()) if not by_device.empty else 0.0

    top_consumers = [
        {
            "device": name,
            "energy_kwh": _round(value),
            # Share of the window's total, which is what makes a ranked bar
            # chart readable — 0.9 kWh means nothing without the denominator.
            "share": _round((value / total_kwh) if total_kwh else 0.0, 4),
        }
        for name, value in by_device.head(5).items()
    ]

    hourly_windowed = _apply_window(
        _filter_devices(hourly if hourly is not None else pd.DataFrame(), devices),
        "event_hour",
        days,
        start,
        end,
        _latest(hourly, "event_hour"),
    )
    # The house profile sums devices within an hour, then averages those hourly
    # totals across days: averaging first would divide the house total by the
    # number of devices reporting.
    if hourly_windowed.empty:
        house_profile = _hourly_profile(pd.DataFrame(columns=["event_hour", "power_w_mean", "energy_kwh"]))
    else:
        per_hour = (
            hourly_windowed.groupby("event_hour")
            .agg(power_w_mean=("power_w_mean", "sum"), energy_kwh=("energy_kwh", "sum"))
            .reset_index()
        )
        house_profile = _hourly_profile(per_hour)

    daily_series = (
        windowed.groupby("event_day")["energy_kwh"].sum().sort_index()
        if not windowed.empty
        else pd.Series(dtype="float64")
    )

    return {
        "empty": False,
        "empty_reason": None,
        "source": metrics["source"],
        "latest_day": _iso(latest_day),
        "window": {**_window_description(days, start, end), "devices": sorted(devices) if devices else None},
        "totals": _energy_totals(_filter_devices(daily, devices), latest_day),
        "total_kwh": _round(total_kwh),
        "top_consumers": top_consumers,
        "daily_energy": [
            {"day": _iso(day), "energy_kwh": _round(value)}
            for day, value in daily_series.items()
        ],
        "hourly_profile": house_profile,
    }


# ---------------------------------------------------------------------------
# Device detail
# ---------------------------------------------------------------------------


def build_device_detail(device_name: str, days=7, start=None, end=None) -> dict:
    """Everything the Device Details page shows for one device."""
    metrics = load_metrics()
    daily = metrics.get("power_daily")
    hourly = metrics.get("power_hourly")
    mapping = load_device_mapping()
    known = set(mapping.values())

    if device_name not in known:
        return _empty(f"Unknown device: {device_name!r}.", device=device_name, known=sorted(known))

    if daily is None or daily.empty or hourly is None or hourly.empty:
        return _empty("No energy data yet.", device=device_name)

    device_daily = daily[daily["device_name"] == device_name]
    device_hourly = hourly[hourly["device_name"] == device_name]

    if device_daily.empty and device_hourly.empty:
        return _empty(f"{device_name} has not reported any electrical readings.", device=device_name)

    latest_day = _latest(daily, "event_day")
    latest_hour = _latest(hourly, "event_hour")
    windowed_daily = _apply_window(device_daily, "event_day", days, start, end, latest_day)
    windowed_hourly = _apply_window(device_hourly, "event_hour", days, start, end, latest_hour)

    def _stat(column, aggregate):
        if windowed_hourly.empty or column not in windowed_hourly.columns:
            return None
        return getattr(windowed_hourly[column], aggregate)()

    return {
        "empty": False,
        "empty_reason": None,
        "source": metrics["source"],
        "device": device_name,
        "window": {**_window_description(days, start, end), "latest_day": _iso(latest_day)},
        "totals": _energy_totals(device_daily, latest_day),
        "power": {
            "mean_w": _round(_stat("power_w_mean", "mean"), 1),
            "max_w": _round(_stat("power_w_max", "max"), 1),
            "min_w": _round(_stat("power_w_min", "min"), 1),
            "energy_kwh": _round(windowed_daily["energy_kwh"].sum() if not windowed_daily.empty else 0.0),
        },
        "power_series": [
            {"time": _iso(row.event_hour), "power_w": _round(row.power_w_mean, 1)}
            for row in windowed_hourly.sort_values("event_hour").itertuples()
        ],
        "daily_energy": [
            {"day": _iso(row.event_day), "energy_kwh": _round(row.energy_kwh)}
            for row in windowed_daily.sort_values("event_day").itertuples()
        ],
        "hourly_profile": _hourly_profile(windowed_hourly),
        "voltage": _measurement_block(windowed_hourly, "voltage_v", "V"),
        "current": _measurement_block(windowed_hourly, "current_ma", "mA"),
    }


def _measurement_block(hourly: pd.DataFrame, prefix: str, unit: str) -> dict:
    """Metrics, a time series and a distribution for voltage or current.

    The distribution is built from the hourly means rather than from raw
    samples: the raw readings are not in the gold layer, and an hourly mean is
    the right granularity for spotting a sagging supply anyway.
    """
    mean_col, max_col, min_col = f"{prefix}_mean", f"{prefix}_max", f"{prefix}_min"
    if hourly.empty or mean_col not in hourly.columns:
        return {"unit": unit, "mean": None, "max": None, "min": None, "series": [], "distribution": None}

    ordered = hourly.sort_values("event_hour")
    return {
        "unit": unit,
        "mean": _round(ordered[mean_col].mean(), 1),
        "max": _round(ordered[max_col].max(), 1),
        "min": _round(ordered[min_col].min(), 1),
        "series": [
            {"time": _iso(row.event_hour), "value": _round(getattr(row, mean_col), 1)}
            for row in ordered.itertuples()
        ],
        "distribution": boxplot_stats(ordered[mean_col]),
    }


# ---------------------------------------------------------------------------
# Advanced analysis: CUSUM, profiles, peaks
# ---------------------------------------------------------------------------


def build_cusum(device_name: str, k=DEFAULT_K, h=DEFAULT_H, days=None, start=None, end=None) -> dict:
    """Phase II of the CUSUM scheme for one device (monograph section 3.3.2)."""
    metrics = load_metrics()
    hourly = metrics.get("power_hourly")
    baseline_df = metrics.get("baseline")
    mapping = load_device_mapping()

    if device_name not in set(mapping.values()):
        return _empty(f"Unknown device: {device_name!r}.", device=device_name)
    if hourly is None or hourly.empty or baseline_df is None or baseline_df.empty:
        return _empty(
            "No CUSUM baseline yet — materialize gold_energy_metrics first.",
            device=device_name,
        )

    device_hourly = hourly[hourly["device_name"] == device_name].sort_values("event_hour")
    device_baseline = baseline_df[baseline_df["device_name"] == device_name]

    if device_hourly.empty or device_baseline.empty:
        return _empty(
            f"{device_name} has no baseline to monitor against.", device=device_name
        )

    windowed = _apply_window(
        device_hourly, "event_hour", days, start, end, _latest(device_hourly, "event_hour")
    )

    baseline = {
        int(row.hour_of_day): (row.mu0, row.sigma0, int(row.n_obs))
        for row in device_baseline.itertuples()
    }
    observations = [
        (pd.Timestamp(row.event_hour), int(pd.Timestamp(row.event_hour).hour), float(row.energy_kwh))
        for row in windowed.itertuples()
    ]

    result = multichannel_cusum(observations, baseline, k=k, h=h)

    return {
        "empty": False,
        "empty_reason": None,
        "source": metrics["source"],
        "device": device_name,
        "k": k,
        "h": h,
        "monitored_variable": "energy_kwh",
        "monitored_count": result.monitored_count,
        "skipped_count": result.skipped_count,
        "points": [
            {
                "time": _iso(point.timestamp),
                "hour": point.hour_of_day,
                "value": _round(point.value, 4),
                "mu0": _round(point.mu0, 4),
                "s_hi": _round(point.s_hi, 4),
                "s_lo": _round(point.s_lo, 4),
                "limit": _round(point.decision_limit, 4),
                "signal": point.signal,
                "monitored": point.monitored,
            }
            for point in result.points
        ],
        "faults": [
            {
                "time": _iso(fault.timestamp),
                "hour": fault.hour_of_day,
                "direction": fault.direction,
                "value": _round(fault.value, 4),
                "expected": _round(fault.expected, 4),
                "cusum": _round(fault.cusum_value, 4),
                "limit": _round(fault.decision_limit, 4),
                "excess": _round(fault.excess, 4),
            }
            for fault in result.faults
        ],
        "baseline": [
            {
                "hour": int(row.hour_of_day),
                "mu0": _round(row.mu0, 4),
                "sigma0": _round(row.sigma0, 5),
                "n_obs": int(row.n_obs),
            }
            for row in device_baseline.sort_values("hour_of_day").itertuples()
        ],
    }


WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def build_profiles(devices=None, days=None, start=None, end=None) -> dict:
    """Day-of-week profiles, and recent weeks against the historical mean.

    The monograph shows the second of these as a 3D surface (figure 4.18). It is
    delivered here as an overlay in two dimensions — one line per week against a
    bold historical mean — which carries the same comparison without a fake
    projection the reader cannot rotate.
    """
    metrics = load_metrics()
    hourly = metrics.get("power_hourly")

    if hourly is None or hourly.empty:
        return _empty("No energy data yet.")

    frame = _filter_devices(hourly, devices)
    frame = _apply_window(frame, "event_hour", days, start, end, _latest(hourly, "event_hour"))
    if frame.empty:
        return _empty("No readings for the selected devices and period.")

    frame = frame.copy()
    times = pd.to_datetime(frame["event_hour"])
    frame["hour"] = times.dt.hour
    frame["weekday"] = times.dt.weekday
    frame["date"] = times.dt.normalize()
    # Weeks are labelled by their Monday, so a label is a real date the reader
    # can locate rather than an ISO week number.
    frame["week_start"] = frame["date"] - pd.to_timedelta(frame["weekday"], unit="D")
    frame["hour_of_week"] = frame["weekday"] * 24 + frame["hour"]

    # Sum across devices within an hour first, then average across days, for the
    # same reason as the house profile above.
    per_hour = frame.groupby(["date", "weekday", "hour", "hour_of_week", "week_start"], as_index=False).agg(
        power_w=("power_w_mean", "sum"), energy_kwh=("energy_kwh", "sum")
    )

    daily_profiles = []
    for weekday in range(7):
        subset = per_hour[per_hour["weekday"] == weekday]
        grouped = subset.groupby("hour")["power_w"].mean() if not subset.empty else pd.Series(dtype="float64")
        daily_profiles.append(
            {
                "weekday": weekday,
                "label": WEEKDAY_NAMES[weekday],
                "points": [
                    {"hour": hour, "power_w": _round(grouped.get(hour), 1) if hour in grouped.index else None}
                    for hour in range(24)
                ],
            }
        )

    historical = per_hour.groupby("hour_of_week")["power_w"].mean()
    weeks = []
    for week_start, subset in sorted(per_hour.groupby("week_start"), key=lambda item: item[0]):
        grouped = subset.groupby("hour_of_week")["power_w"].mean()
        weeks.append(
            {
                "week_start": _iso(week_start),
                "points": [
                    {"hour_of_week": how, "power_w": _round(grouped.get(how), 1) if how in grouped.index else None}
                    for how in range(168)
                ],
            }
        )

    return {
        "empty": False,
        "empty_reason": None,
        "source": metrics["source"],
        "window": {**_window_description(days, start, end), "devices": sorted(devices) if devices else None},
        "daily_profiles": daily_profiles,
        "weekly": {
            "historical_mean": [
                {"hour_of_week": how, "power_w": _round(historical.get(how), 1) if how in historical.index else None}
                for how in range(168)
            ],
            "weeks": weeks[-4:],  # the last four weeks; older ones crowd the chart
        },
    }


def build_peaks(devices=None, days=None, limit=10, start=None, end=None) -> dict:
    """The highest-power hours in the window, across the selected devices."""
    metrics = load_metrics()
    hourly = metrics.get("power_hourly")

    if hourly is None or hourly.empty:
        return _empty("No energy data yet.", peaks=[])

    frame = _filter_devices(hourly, devices)
    frame = _apply_window(frame, "event_hour", days, start, end, _latest(hourly, "event_hour"))
    if frame.empty:
        return _empty("No readings for the selected devices and period.", peaks=[])

    top = frame.nlargest(max(1, min(int(limit), 100)), "power_w_max")

    return {
        "empty": False,
        "empty_reason": None,
        "source": metrics["source"],
        "window": {**_window_description(days, start, end), "devices": sorted(devices) if devices else None},
        "peaks": [
            {
                "device": row.device_name,
                "time": _iso(row.event_hour),
                "peak_w": _round(row.power_w_max, 1),
                "mean_w": _round(row.power_w_mean, 1),
                "energy_kwh": _round(row.energy_kwh, 4),
            }
            for row in top.sort_values("power_w_max", ascending=False).itertuples()
        ],
    }
