"""Sensor access: the real vendor I2C drivers on a real or mock I2C bus.

``open_sensor("mock")`` builds a ``MockI2cTransceiver`` and hands it to
the driver's unmodified ``I2cConnection``; ``open_sensor("i2c")`` hands it a
``LinuxI2cTransceiver`` for e.g. /dev/i2c-1. Everything above the transceiver
is driver code in both cases.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from sensirion_i2c_driver import I2cConnection
from sensirion_i2c_scd.scd4x.device import Scd4xI2cDevice
from sensirion_i2c_sen5x import Sen5xI2cDevice

from airq.mock_i2c import MockI2cTransceiver
from airq.models import Reading

log = logging.getLogger(__name__)


def _num(value: float) -> float | None:
    """The driver reports unavailable values as NaN."""
    return None if value != value else float(value)


class AirQualitySensor:
    """PM/T/RH/VOC/NOx sensor plus optional CO2 sensor, both over I2C."""

    def __init__(self, transceiver: Any, with_co2: bool = True, warmup_s: float = 0.0) -> None:
        self._conn = I2cConnection(transceiver)
        self.pm_sensor = Sen5xI2cDevice(self._conn)
        self.co2_sensor = Scd4xI2cDevice(self._conn) if with_co2 else None
        self._warmup_s = warmup_s
        self._started = False

    def start(self) -> str:
        """Start measuring; returns the PM sensor product name as reported by the chip."""
        self.pm_sensor.device_reset()
        self.pm_sensor.start_measurement()
        if self.co2_sensor:
            self.co2_sensor.start_periodic_measurement()
        self._started = True
        time.sleep(self._warmup_s)
        return str(self.pm_sensor.get_product_name())

    def stop(self) -> None:
        if not self._started:
            return
        self.pm_sensor.stop_measurement()
        if self.co2_sensor:
            self.co2_sensor.stop_periodic_measurement()
        self._started = False

    def read(self, ts: float | None = None, tries: int = 20) -> Reading:
        if not self._started:
            self.start()
        for _ in range(tries):
            if self.pm_sensor.read_data_ready():
                break
            time.sleep(0.1 if self._warmup_s else 0)
        else:
            raise TimeoutError("PM sensor reported no data ready")
        v = self.pm_sensor.read_measured_values()
        co2: float | None = None
        if self.co2_sensor and self.co2_sensor.get_data_ready_status():
            co2_val, _temp, _rh = self.co2_sensor.read_measurement()
            co2 = float(co2_val.co2)
        return Reading(
            ts=time.time() if ts is None else ts,
            pm1_0=_num(v.mass_concentration_1p0.physical),
            pm2_5=_num(v.mass_concentration_2p5.physical),
            pm4_0=_num(v.mass_concentration_4p0.physical),
            pm10=_num(v.mass_concentration_10p0.physical),
            temperature_c=_num(v.ambient_temperature.degrees_celsius),
            humidity_pct=_num(v.ambient_humidity.percent_rh),
            voc_index=_num(v.voc_index.scaled),
            nox_index=_num(v.nox_index.scaled),
            co2_ppm=co2,
        )


def open_sensor(backend: str | None = None, with_co2: bool = True) -> AirQualitySensor:
    """backend: 'mock' or 'i2c'; default from AIRQ_BACKEND (default 'mock')."""
    backend = (backend or os.environ.get("AIRQ_BACKEND", "mock")).lower()
    if backend == "mock":
        return AirQualitySensor(MockI2cTransceiver(), with_co2=with_co2)
    if backend == "i2c":
        from sensirion_i2c_driver import LinuxI2cTransceiver  # Linux only

        dev = os.environ.get("AIRQ_I2C_DEVICE", "/dev/i2c-1")
        return AirQualitySensor(LinuxI2cTransceiver(dev), with_co2=with_co2, warmup_s=1.2)
    raise ValueError(f"unknown backend {backend!r} (use 'mock' or 'i2c')")
