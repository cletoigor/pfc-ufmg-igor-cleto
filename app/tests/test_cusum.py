"""
Tests for the multichannel CUSUM implementation (app/analysis/cusum.py).

Every expected number here is computed by hand from the recurrences in section
3.3.2 of the monograph, so a change in the arithmetic fails the test rather than
quietly changing what the Advanced Analysis page reports.

The fixtures use mu0 = 100 and sigma0 = 10 with the default k = 0.5, h = 5,
which makes the allowance K = 5 and the decision limit H = 50 — round numbers
that can be followed on paper.
"""
import pytest

from app.analysis.cusum import (
    DEFAULT_H,
    DEFAULT_K,
    cusum,
    multichannel_cusum,
)

MU0 = 100.0
SIGMA0 = 10.0
K = DEFAULT_K * SIGMA0   # 5.0
H = DEFAULT_H * SIGMA0   # 50.0


def test_allowance_and_decision_limit_are_multiples_of_sigma():
    result = cusum([MU0] * 3, MU0, SIGMA0)
    point = result.points[0]
    assert point.allowance == pytest.approx(K)
    assert point.decision_limit == pytest.approx(H)


def test_a_process_sitting_on_its_mean_never_signals():
    result = cusum([MU0] * 50, MU0, SIGMA0)

    assert result.signal_count == 0
    assert all(p.s_hi == 0.0 and p.s_lo == 0.0 for p in result.points)


def test_small_deviations_inside_the_allowance_are_absorbed():
    """Anything within K of the mean is common-cause noise and must not accumulate."""
    result = cusum([104.0, 96.0] * 25, MU0, SIGMA0)

    assert result.signal_count == 0
    assert all(p.s_hi == 0.0 and p.s_lo == 0.0 for p in result.points)


def test_upward_shift_accumulates_and_signals_on_the_expected_observation():
    # x = 120 contributes 120 - (100 + 5) = 15 per observation, so the sum runs
    # 15, 30, 45, 60 and first exceeds H = 50 on the fourth shifted observation.
    values = [MU0] * 3 + [120.0] * 5
    result = cusum(values, MU0, SIGMA0)

    assert [p.s_hi for p in result.points[:7]] == pytest.approx(
        [0.0, 0.0, 0.0, 15.0, 30.0, 45.0, 60.0]
    )
    assert [p.signal for p in result.points[:7]] == [False] * 6 + [True]
    assert result.points[6].direction == "high"

    fault = result.faults[0]
    assert fault.direction == "high"
    assert fault.value == pytest.approx(120.0)
    assert fault.expected == pytest.approx(MU0)
    assert fault.cusum_value == pytest.approx(60.0)
    assert fault.decision_limit == pytest.approx(H)
    assert fault.excess == pytest.approx(10.0)


def test_downward_shift_signals_on_the_lower_sum():
    # x = 80 contributes (100 - 5) - 80 = 15 per observation: same cadence,
    # opposite direction.
    result = cusum([80.0] * 4, MU0, SIGMA0)

    assert [p.s_lo for p in result.points] == pytest.approx([15.0, 30.0, 45.0, 60.0])
    assert [p.s_hi for p in result.points] == pytest.approx([0.0] * 4)
    assert result.points[3].direction == "low"


def test_sums_are_floored_at_zero_rather_than_going_negative():
    """A run below the mean must not build up credit against a later rise."""
    result = cusum([60.0] * 5 + [120.0] * 4, MU0, SIGMA0)

    # The upper sum stayed pinned at zero through the low run...
    assert [p.s_hi for p in result.points[:5]] == pytest.approx([0.0] * 5)
    # ...so the rise afterwards starts accumulating from zero, not from a deficit.
    assert result.points[5].s_hi == pytest.approx(15.0)


def test_the_offending_sum_resets_after_a_signal():
    result = cusum([120.0] * 8, MU0, SIGMA0)

    signalling = [i for i, p in enumerate(result.points) if p.signal]
    assert signalling[0] == 3                      # 15, 30, 45, 60 -> signal
    assert result.points[4].s_hi == pytest.approx(15.0)  # reset, then re-accumulate


def test_signalling_can_be_left_latched_when_reset_is_disabled():
    result = cusum([120.0] * 8, MU0, SIGMA0, reset_after_signal=False)

    assert result.points[7].s_hi == pytest.approx(15.0 * 8)
    assert all(p.signal for p in result.points[3:])


def test_zero_spread_channel_is_skipped_instead_of_alarming_on_everything():
    result = cusum([500.0] * 10, MU0, 0.0)

    assert result.signal_count == 0
    assert result.monitored_count == 0
    assert result.skipped_count == 10
    assert all(p.monitored is False for p in result.points)


def test_thin_baseline_channel_is_skipped():
    observations = [(i, 9, 500.0) for i in range(10)]
    baseline = {9: (MU0, SIGMA0, 2)}  # only two historical observations

    result = multichannel_cusum(observations, baseline)

    assert result.signal_count == 0
    assert result.skipped_count == 10


def test_hour_with_no_baseline_at_all_is_carried_through_unmonitored():
    observations = [(0, 9, 120.0), (1, 3, 999.0), (2, 9, 120.0)]
    baseline = {9: (MU0, SIGMA0, 20)}  # nothing for hour 3

    result = multichannel_cusum(observations, baseline)

    assert result.points[1].monitored is False
    assert result.points[1].signal is False
    # The 03:00 observation must not disturb what the 09:00 channel accumulated.
    assert result.points[0].s_hi == pytest.approx(15.0)
    assert result.points[2].s_hi == pytest.approx(30.0)


def test_each_hour_is_compared_against_its_own_channel():
    """The point of the multichannel structure: 03:00 is judged against 03:00."""
    baseline = {3: (10.0, 1.0, 20), 19: (200.0, 20.0, 20)}
    observations = [(0, 3, 10.0), (1, 19, 200.0)]

    result = multichannel_cusum(observations, baseline)

    assert result.points[0].mu0 == pytest.approx(10.0)
    assert result.points[1].mu0 == pytest.approx(200.0)
    # 200 W at 19:00 is entirely normal; the same reading at 03:00 would not be.
    assert result.signal_count == 0


def test_channels_accumulate_independently():
    """A drift confined to one hour must not push another hour's sum."""
    baseline = {9: (MU0, SIGMA0, 20), 10: (MU0, SIGMA0, 20)}
    observations = []
    for day in range(4):
        observations.append((f"d{day}-09", 9, 120.0))  # drifting
        observations.append((f"d{day}-10", 10, MU0))   # steady

    result = multichannel_cusum(observations, baseline)

    drifting = [p for p in result.points if p.hour_of_day == 9]
    steady = [p for p in result.points if p.hour_of_day == 10]

    assert [p.s_hi for p in drifting] == pytest.approx([15.0, 30.0, 45.0, 60.0])
    assert [p.s_hi for p in steady] == pytest.approx([0.0] * 4)
    assert all(f.hour_of_day == 9 for f in result.faults)


def test_larger_h_delays_the_alarm_and_larger_k_suppresses_it():
    values = [120.0] * 6

    assert cusum(values, MU0, SIGMA0, h=5).points[3].signal is True
    # H = 80 needs 15 per step to reach past 80: six observations, not four.
    assert cusum(values, MU0, SIGMA0, h=8).points[3].signal is False
    assert cusum(values, MU0, SIGMA0, h=8).points[5].signal is True
    # An allowance of 2 sigma swallows a 2 sigma shift entirely.
    assert cusum(values, MU0, SIGMA0, k=2.0).signal_count == 0


@pytest.mark.parametrize("k,h", [(-0.1, 5.0), (0.5, 0.0), (0.5, -1.0)])
def test_invalid_parameters_are_rejected(k, h):
    with pytest.raises(ValueError):
        cusum([1.0, 2.0], MU0, SIGMA0, k=k, h=h)


def test_points_align_one_to_one_with_the_input_series():
    observations = [(i, 9, 100.0 + i) for i in range(12)]
    result = multichannel_cusum(observations, {9: (MU0, SIGMA0, 20)})

    assert len(result.points) == 12
    assert [p.index for p in result.points] == list(range(12))
    assert [p.timestamp for p in result.points] == list(range(12))
