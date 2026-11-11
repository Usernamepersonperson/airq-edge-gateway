"""Derived values and simple indoor-air advice.

Thresholds are common rules of thumb (see comments), not a compliance check
against any standard. Do not use this as a safety device.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from airq.models import Reading

# Magnus formula coefficients (Sonntag 1990), valid roughly -45..60 degC over water.
MAGNUS_A = 17.62
MAGNUS_B = 243.12  # degC


def dew_point_c(temperature_c: float, humidity_pct: float) -> float:
    """Dew point in degC via the Magnus formula."""
    if not 0 < humidity_pct <= 100:
        raise ValueError("humidity_pct must be in (0, 100]")
    gamma = math.log(humidity_pct / 100.0) + MAGNUS_A * temperature_c / (MAGNUS_B + temperature_c)
    return MAGNUS_B * gamma / (MAGNUS_A - gamma)


def absolute_humidity_gm3(temperature_c: float, humidity_pct: float) -> float:
    """Water vapour density in g/m3 (ideal gas, Magnus saturation pressure)."""
    sat_hpa = 6.112 * math.exp(MAGNUS_A * temperature_c / (MAGNUS_B + temperature_c))
    vapour_pa = humidity_pct / 100.0 * sat_hpa * 100.0
    return vapour_pa / (461.5 * (temperature_c + 273.15)) * 1000.0  # R_v = 461.5 J/(kg K)


class RollingMean:
    """Time-windowed mean (default 24 h). Samples older than the window drop out."""

    def __init__(self, window_s: float = 24 * 3600.0) -> None:
        self.window_s = window_s
        self._samples: deque[tuple[float, float]] = deque()
        self._sum = 0.0

    def add(self, ts: float, value: float) -> float:
        self._samples.append((ts, value))
        self._sum += value
        while self._samples and self._samples[0][0] <= ts - self.window_s:
            self._sum -= self._samples.popleft()[1]
        return self._sum / len(self._samples)


def advice(
    co2_ppm: float | None = None,
    pm2_5: float | None = None,
    pm2_5_24h: float | None = None,
    humidity_pct: float | None = None,
    temperature_c: float | None = None,
    voc_index: float | None = None,
) -> list[str]:
    """Short human-readable hints. Empty list means nothing to flag."""
    out: list[str] = []
    # CO2: ~1000 ppm is a widely used "ventilate" rule of thumb for occupied rooms;
    # above ~1500 ppm air is clearly stale. Rules of thumb, not a legal limit.
    if co2_ppm is not None:
        if co2_ppm > 1500:
            out.append("CO2 above 1500 ppm: ventilate now")
        elif co2_ppm > 1000:
            out.append("CO2 above 1000 ppm: ventilate")
    # PM2.5: WHO 2021 air quality guideline is 15 ug/m3 as a 24 h mean.
    if pm2_5_24h is not None and pm2_5_24h > 15:
        out.append("PM2.5 24h mean above WHO 2021 guideline (15 ug/m3)")
    elif pm2_5 is not None and pm2_5 > 35:
        out.append("PM2.5 high right now: check sources, consider a filter")
    # Relative humidity: 30..60 % is the commonly cited comfort band.
    if humidity_pct is not None:
        if humidity_pct < 30:
            out.append("Air is dry (RH < 30%): consider humidifying")
        elif humidity_pct > 60:
            out.append("Air is humid (RH > 60%): ventilate to limit mould risk")
    if temperature_c is not None and not 18 <= temperature_c <= 26:
        out.append("Temperature outside 18-26 C comfort range")
    # The VOC index is relative: 100 = the sensor's recent average.
    if voc_index is not None and voc_index > 250:
        out.append("VOC index well above its recent average: check for sources")
    return out


@dataclass
class Deriver:
    """Holds rolling state and turns a Reading into a flat record for sinks."""

    pm_window: RollingMean = field(default_factory=RollingMean)

    def process(self, r: Reading) -> dict[str, object]:
        rec: dict[str, object] = {}
        for name in (
            "pm1_0", "pm2_5", "pm4_0", "pm10", "temperature_c",
            "humidity_pct", "voc_index", "nox_index", "co2_ppm",
        ):
            value = getattr(r, name)
            if value is not None:
                rec[name] = round(value, 2)
        t, rh = r.temperature_c, r.humidity_pct
        if t is not None and rh is not None and rh > 0:
            rec["dew_point_c"] = round(dew_point_c(t, min(rh, 100.0)), 2)
            rec["abs_humidity_gm3"] = round(absolute_humidity_gm3(t, rh), 2)
        pm24 = self.pm_window.add(r.ts, r.pm2_5) if r.pm2_5 is not None else None
        if pm24 is not None:
            rec["pm2_5_24h_mean"] = round(pm24, 2)
        rec["advice"] = advice(r.co2_ppm, r.pm2_5, pm24, rh, t, r.voc_index)
        return rec
