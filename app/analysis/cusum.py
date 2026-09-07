"""
Multichannel CUSUM control charts (monograph section 3.3.2).

Pure functions over plain Python values — no DuckDB, no Dagster, no Starlette —
so the statistics can be unit-tested against hand-computed numbers and reused by
both the web API and the Streamlit dashboard.

The scheme has two phases:

  Phase I  establishes a baseline. For each *channel* — one hour of the day, the
           daily-periodic structure at one-hour resolution — the mean (mu0) and
           the sample standard deviation (sigma0, with the m-1 denominator of
           equation 3.2) of the monitored variable are estimated from historical
           observations of that same hour. That work happens in SQL, in
           `app/assets/energy_marts.py`; this module consumes its output.

  Phase II monitors new observations. Two cumulative sums accumulate evidence of
           a shift away from mu0, one in each direction:

               K    = k * sigma0                       (the allowance, or slack)
               H    = h * sigma0                       (the decision limit)
               S_hi = max(0, S_hi_prev + (x - (mu0 + K)))
               S_lo = max(0, S_lo_prev + ((mu0 - K) - x))

           starting from zero, and an out-of-control signal is raised when
           either sum exceeds H. Defaults are k = 0.5 and h = 5, the values the
           monograph adopts.

Because each observation is compared against *its own hour's* mu0 and sigma0,
consumption at 03:00 is judged against other nights rather than against the
evening peak — which is the entire point of the multichannel structure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

DEFAULT_K = 0.5
DEFAULT_H = 5.0

# A channel estimated from one or two observations has a standard deviation that
# is mostly noise; monitoring against it produces alarms that say more about the
# baseline than about the process.
MIN_BASELINE_OBSERVATIONS = 3


@dataclass
class CusumPoint:
    """One monitored observation and the state of both sums after it."""

    index: int
    timestamp: object  # whatever the caller keyed observations by; often a datetime
    hour_of_day: int | None
    value: float
    mu0: float | None
    sigma0: float | None
    allowance: float | None      # K
    decision_limit: float | None  # H
    s_hi: float
    s_lo: float
    signal: bool
    direction: str | None  # "high" | "low" | None
    monitored: bool        # False when the channel had no usable baseline


@dataclass
class CusumFault:
    """One crossing of the decision limit — a row of the monograph's fault log."""

    timestamp: object
    hour_of_day: int | None
    direction: str          # "high" (consuming more) | "low" (consuming less)
    value: float
    expected: float         # mu0 for the channel
    cusum_value: float      # the sum at the moment it crossed
    decision_limit: float   # H for the channel
    excess: float           # how far past H it went


@dataclass
class CusumResult:
    points: list[CusumPoint] = field(default_factory=list)
    faults: list[CusumFault] = field(default_factory=list)
    k: float = DEFAULT_K
    h: float = DEFAULT_H
    monitored_count: int = 0
    skipped_count: int = 0

    @property
    def signal_count(self) -> int:
        return len(self.faults)


def _validate(k: float, h: float) -> None:
    if k < 0:
        raise ValueError("k (allowance multiplier) must be >= 0")
    if h <= 0:
        raise ValueError("h (decision limit multiplier) must be > 0")


def multichannel_cusum(
    observations: Iterable[tuple],
    baseline: Mapping[int, tuple],
    *,
    k: float = DEFAULT_K,
    h: float = DEFAULT_H,
    min_observations: int = MIN_BASELINE_OBSERVATIONS,
    reset_after_signal: bool = True,
) -> CusumResult:
    """Runs Phase II over a time-ordered series against a per-hour baseline.

    Args:
        observations: `(timestamp, hour_of_day, value)` triples, in time order.
        baseline: `hour_of_day -> (mu0, sigma0, n_obs)`. Hours missing from the
            mapping, or whose channel is too thin to trust (`n_obs <
            min_observations`) or degenerate (`sigma0 <= 0`), are carried
            through the series unmonitored rather than alarmed on: a device that
            has never run at 04:00 has no normal behaviour at 04:00 to deviate
            from, and dividing by a zero spread would flag every reading.
        reset_after_signal: return the offending sum to zero once it has
            signalled. This is the usual practice — the chart is telling you to
            go and investigate, and without a reset a single shift pins the sum
            above the limit forever, turning every later observation into a
            duplicate alarm.

    Returns a `CusumResult` whose `points` align one-to-one with the input.
    """
    _validate(k, h)

    result = CusumResult(k=k, h=h)
    # One pair of accumulators *per channel*, not one pair for the whole series.
    #
    # This is what "a análise estatística é realizada intra-canais" means: the
    # 11:00 channel accumulates evidence from 11:00 on successive days and from
    # nothing else. Pooling every hour into a single running sum looks simpler
    # but is wrong for this data — consumption at every hour of one day shares
    # that day's conditions, so a single warm day pushes ten consecutive
    # observations the same way and a shared accumulator reads that correlated
    # noise as a sustained shift. Per-channel sums see one observation per day,
    # which is the near-independent sequence CUSUM's ARL properties assume.
    sums: dict[object, list[float]] = {}

    for index, observation in enumerate(observations):
        timestamp, hour_of_day, value = observation
        value = float(value)
        channel = baseline.get(hour_of_day) if hour_of_day is not None else None

        # A channel estimated from a single observation has a NULL sample
        # standard deviation, so neither field can be assumed present.
        mu0: float | None = None
        sigma0: float | None = None
        n_obs = 0
        if channel is not None:
            if channel[0] is not None:
                mu0 = float(channel[0])
            if channel[1] is not None:
                sigma0 = float(channel[1])
            n_obs = int(channel[2])

        usable = mu0 is not None and sigma0 is not None and sigma0 > 0 and n_obs >= min_observations

        if not usable:
            result.skipped_count += 1
            channel_sums = sums.get(hour_of_day, [0.0, 0.0])
            result.points.append(
                CusumPoint(
                    index=index,
                    timestamp=timestamp,
                    hour_of_day=hour_of_day,
                    value=value,
                    mu0=mu0,
                    sigma0=sigma0,
                    allowance=None,
                    decision_limit=None,
                    s_hi=channel_sums[0],
                    s_lo=channel_sums[1],
                    signal=False,
                    direction=None,
                    monitored=False,
                )
            )
            continue

        # Past the `usable` guard both are known floats; rebinding them under
        # non-optional names keeps that obvious to a reader and to a type checker.
        mu: float = mu0  # type: ignore[assignment]
        sigma: float = sigma0  # type: ignore[assignment]
        allowance = k * sigma
        decision_limit = h * sigma

        channel_sums = sums.setdefault(hour_of_day, [0.0, 0.0])
        s_hi = max(0.0, channel_sums[0] + (value - (mu + allowance)))
        s_lo = max(0.0, channel_sums[1] + ((mu - allowance) - value))

        direction = None
        if s_hi > decision_limit:
            direction = "high"
        elif s_lo > decision_limit:
            direction = "low"

        if direction is not None:
            crossing_sum = s_hi if direction == "high" else s_lo
            result.faults.append(
                CusumFault(
                    timestamp=timestamp,
                    hour_of_day=hour_of_day,
                    direction=direction,
                    value=value,
                    expected=mu,
                    cusum_value=crossing_sum,
                    decision_limit=decision_limit,
                    excess=crossing_sum - decision_limit,
                )
            )

        result.monitored_count += 1
        result.points.append(
            CusumPoint(
                index=index,
                timestamp=timestamp,
                hour_of_day=hour_of_day,
                value=value,
                mu0=mu,
                sigma0=sigma,
                allowance=allowance,
                decision_limit=decision_limit,
                s_hi=s_hi,
                s_lo=s_lo,
                signal=direction is not None,
                direction=direction,
                monitored=True,
            )
        )

        if direction is not None and reset_after_signal:
            if direction == "high":
                s_hi = 0.0
            else:
                s_lo = 0.0

        channel_sums[0] = s_hi
        channel_sums[1] = s_lo

    return result


def cusum(
    values: Sequence[float],
    mu0: float,
    sigma0: float,
    *,
    k: float = DEFAULT_K,
    h: float = DEFAULT_H,
    timestamps: Sequence | None = None,
    reset_after_signal: bool = True,
) -> CusumResult:
    """Single-channel CUSUM: every observation shares one mu0 and sigma0.

    A thin wrapper over `multichannel_cusum` with a one-channel baseline, kept
    because the textbook form is what the unit tests check the arithmetic
    against, and because a single device-hour series is sometimes all you want.
    """
    stamps = timestamps if timestamps is not None else range(len(values))
    observations = [(stamp, 0, value) for stamp, value in zip(stamps, values)]
    return multichannel_cusum(
        observations,
        {0: (mu0, sigma0, MIN_BASELINE_OBSERVATIONS)},
        k=k,
        h=h,
        reset_after_signal=reset_after_signal,
    )
