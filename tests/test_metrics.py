"""TRIMP and the ATL/CTL/TSB load curves."""

import pandas as pd
import pytest

from garmin_sync.metrics import load_curves, trimp_from_average, trimp_from_samples


def test_trimp_at_rest_is_zero_and_grows_with_hr():
    assert trimp_from_average(3600, 50, hr_max=190, hr_rest=50) == 0
    easy = trimp_from_average(3600, 130, hr_max=190, hr_rest=50)
    hard = trimp_from_average(3600, 170, hr_max=190, hr_rest=50)
    assert 0 < easy < hard


def test_trimp_from_constant_samples_matches_average():
    t = [float(i) for i in range(0, 3601, 5)]
    hr = [150.0] * len(t)
    assert trimp_from_samples(t, hr, 190, 50) == pytest.approx(trimp_from_average(3600, 150, 190, 50))


def test_trimp_skips_pauses_and_missing_hr():
    t, hr = [0.0, 5.0, 600.0, 605.0], [150.0, 150.0, 150.0, None]
    assert trimp_from_samples(t, hr, 190, 50) == pytest.approx(trimp_from_average(5, 150, 190, 50))


def test_load_curves_fill_rest_days_until_today():
    today = pd.Timestamp.today().normalize()
    daily = pd.Series([100.0], index=[today - pd.Timedelta(days=9)])
    c = load_curves(daily)
    assert c.index[-1] == today and len(c) == 10
    assert (c["load"].iloc[1:] == 0).all()
    # Fatigue (7 days) fades faster than fitness (42 days), so form turns positive after a rest.
    assert c["atl"].iloc[-1] < c["atl"].iloc[0]
    assert c["tsb"].iloc[-1] > 0
    assert load_curves(pd.Series(dtype=float)).empty
