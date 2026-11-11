"""Plain data containers shared across the gateway."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reading:
    """One raw sample. Fields a sensor cannot provide are None."""

    ts: float  # unix seconds
    pm1_0: float | None = None  # ug/m3
    pm2_5: float | None = None
    pm4_0: float | None = None
    pm10: float | None = None
    temperature_c: float | None = None
    humidity_pct: float | None = None
    voc_index: float | None = None  # VOC index, 1..500
    nox_index: float | None = None  # NOx index, 1..500
    co2_ppm: float | None = None
