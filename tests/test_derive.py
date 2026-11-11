import pytest

from airq.derive import Deriver, RollingMean, absolute_humidity_gm3, advice, dew_point_c
from airq.models import Reading


def test_dew_point_hand_values():
    # At 100 % RH the dew point is the air temperature.
    assert dew_point_c(20.0, 100.0) == pytest.approx(20.0, abs=1e-9)
    # 20 degC / 50 % RH: Magnus gives 9.26 degC (tables: 9.3).
    assert dew_point_c(20.0, 50.0) == pytest.approx(9.26, abs=0.02)
    # 25 degC / 60 % RH: ~16.7 degC.
    assert dew_point_c(25.0, 60.0) == pytest.approx(16.69, abs=0.05)


def test_dew_point_rejects_zero_humidity():
    with pytest.raises(ValueError):
        dew_point_c(20.0, 0.0)


def test_absolute_humidity_hand_values():
    # Saturated air at 20 degC holds ~17.3 g/m3; half of that at 50 %.
    assert absolute_humidity_gm3(20.0, 100.0) == pytest.approx(17.3, abs=0.15)
    assert absolute_humidity_gm3(20.0, 50.0) == pytest.approx(8.65, abs=0.1)
    assert absolute_humidity_gm3(30.0, 100.0) == pytest.approx(30.4, abs=0.3)


def test_rolling_mean_window():
    rm = RollingMean(window_s=100)
    assert rm.add(0, 10) == 10
    assert rm.add(50, 20) == 15
    # t=120: sample at t=0 is outside the 100 s window, t=50 stays.
    assert rm.add(120, 30) == pytest.approx(25)
    # t=151: t=50 now drops out too.
    assert rm.add(151, 40) == pytest.approx(35)


def test_advice_thresholds():
    assert advice(co2_ppm=800) == []
    assert advice(co2_ppm=1200) == ["CO2 above 1000 ppm: ventilate"]
    assert "ventilate now" in advice(co2_ppm=1800)[0]
    assert any("dry" in a for a in advice(humidity_pct=25))
    assert any("humid" in a for a in advice(humidity_pct=70))
    assert any("WHO" in a for a in advice(pm2_5_24h=20))


def test_deriver_record_and_missing_values():
    d = Deriver()
    rec = d.process(Reading(ts=0, pm2_5=10, temperature_c=20, humidity_pct=50, co2_ppm=1100))
    assert rec["dew_point_c"] == pytest.approx(9.26, abs=0.02)
    assert rec["pm2_5_24h_mean"] == 10
    assert rec["advice"] == ["CO2 above 1000 ppm: ventilate"]
    rec = d.process(Reading(ts=60, pm2_5=20))
    assert rec["pm2_5_24h_mean"] == 15
    assert "dew_point_c" not in rec and "co2_ppm" not in rec
