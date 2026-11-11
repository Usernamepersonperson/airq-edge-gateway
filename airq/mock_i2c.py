"""A simulated I2C bus carrying a PM/VOC/NOx sensor (0x69) and a CO2 sensor (0x62).

This plugs in at the lowest layer the sensor driver library exposes: the
``I2cTransceiverV1`` interface (see ``sensirion_i2c_driver``). The real
``Sen5xI2cDevice`` / ``Scd4xI2cDevice`` driver classes build the command bytes, and
verify and decode the replies, exactly as they would on hardware. All that is
simulated is the chip: it parses the 16-bit command word and answers with
big-endian words, each followed by a CRC-8 (see ``airq.crc``).

Command IDs below come from the command tables of the public drivers.
Signals are synthetic (a slow "occupancy" wave plus noise), not recorded data.
"""

from __future__ import annotations

import math
import random
import time
from typing import Callable

from airq.crc import add_crcs

PM_ADDR = 0x69
CO2_ADDR = 0x62

# PM/VOC/NOx sensor commands
_PM_START = 0x0021
_PM_STOP = 0x0104
_PM_READY = 0x0202
_PM_READ = 0x03C4
_PM_RESET = 0xD304
_PM_PRODUCT = 0xD014
_PM_SERIAL = 0xD033
# CO2 sensor commands
_CO2_START = 0x21B1
_CO2_STOP = 0x3F86
_CO2_READY = 0xE4B8
_CO2_READ = 0xEC05
_CO2_SERIAL = 0x3682

_STATUS_OK = 0  # I2cTransceiverV1.STATUS_OK
_STATUS_NACK = 2  # I2cTransceiverV1.STATUS_NACK


def _u16(value: float) -> bytes:
    return int(max(0, min(0xFFFF, round(value)))).to_bytes(2, "big")


def _i16(value: float) -> bytes:
    return int(max(-0x8000, min(0x7FFF, round(value)))).to_bytes(2, "big", signed=True)


def _text(value: str, rx_length: int) -> bytes:
    """ASCII string, zero padded, laid out as CRC'd words filling rx_length bytes."""
    words = rx_length // 3
    raw = value.encode("ascii").ljust(words * 2, b"\0")[: words * 2]
    return add_crcs(raw)


class MockI2cTransceiver:
    """Implements the I2cTransceiverV1 interface (API_VERSION 1, single channel)."""

    API_VERSION = 1
    STATUS_OK = _STATUS_OK

    def __init__(self, seed: int = 1, clock: Callable[[], float] = time.time) -> None:
        self._rng = random.Random(seed)
        self._clock = clock
        self._t0 = clock()
        self.pm_measuring = False
        self.co2_measuring = False
        self.log: list[tuple[int, int]] = []  # (address, command), for tests

    @property
    def description(self) -> str:
        return "airq mock I2C bus (PM sensor@0x69, CO2 sensor@0x62)"

    @property
    def channel_count(self) -> None:
        return None

    # -- simulated physics ------------------------------------------------
    def _world(self) -> dict[str, float]:
        """Room state: an occupancy wave (~10 min period) drives CO2, PM, RH."""
        t = self._clock() - self._t0
        occ = 0.5 + 0.5 * math.sin(2 * math.pi * t / 600.0)
        n = self._rng.gauss
        pm25 = max(0.5, 6 + 14 * occ + n(0, 0.6))
        return {
            "co2": 480 + 1100 * occ + n(0, 12),
            "temp": 21.5 + 2.0 * occ + n(0, 0.05),
            "rh": 42 + 14 * occ + n(0, 0.3),
            "pm25": pm25,
            "pm1": pm25 * 0.7,
            "pm4": pm25 * 1.15,
            "pm10": pm25 * 1.35,
            "voc": 90 + 90 * occ + n(0, 2),
            "nox": 1 + 0.5 * occ,
        }

    # -- I2cTransceiverV1.transceive --------------------------------------
    def transceive(
        self,
        slave_address: int,
        tx_data: bytes | None,
        rx_length: int | None,
        read_delay: float,
        timeout: float,
    ) -> tuple[int, Exception | None, bytes]:
        if slave_address not in (PM_ADDR, CO2_ADDR) or not tx_data or len(tx_data) < 2:
            return _STATUS_NACK, OSError("no ACK from mock bus"), b""
        cmd = int.from_bytes(tx_data[:2], "big")
        self.log.append((slave_address, cmd))
        handler = self._pm if slave_address == PM_ADDR else self._co2
        reply = handler(cmd, rx_length or 0)
        if reply is None:
            return _STATUS_NACK, OSError(f"unsupported command 0x{cmd:04X}"), b""
        return _STATUS_OK, None, reply

    def _pm(self, cmd: int, rx_length: int) -> bytes | None:
        if cmd == _PM_START:
            self.pm_measuring = True
            return b""
        if cmd == _PM_RESET:
            self.pm_measuring = False
            return b""
        if cmd == _PM_STOP:
            self.pm_measuring = False
            return b""
        if cmd == _PM_READY:
            return add_crcs(b"\x00" + (b"\x01" if self.pm_measuring else b"\x00"))
        if cmd == _PM_READ:
            if not self.pm_measuring:  # datasheet: unknown values read as upper limit
                return add_crcs(b"\xff\xff" * 4 + b"\x7f\xff" * 4)
            w = self._world()
            return add_crcs(
                _u16(w["pm1"] * 10)
                + _u16(w["pm25"] * 10)
                + _u16(w["pm4"] * 10)
                + _u16(w["pm10"] * 10)
                + _i16(w["rh"] * 100)
                + _i16(w["temp"] * 200)
                + _i16(w["voc"] * 10)
                + _i16(w["nox"] * 10)
            )
        if cmd == _PM_PRODUCT:
            return _text("MOCK-PM-SENSOR", rx_length)
        if cmd == _PM_SERIAL:
            return _text("MOCK0001", rx_length)
        return None

    def _co2(self, cmd: int, rx_length: int) -> bytes | None:
        if cmd == _CO2_START:
            self.co2_measuring = True
            return b""
        if cmd == _CO2_STOP:
            self.co2_measuring = False
            return b""
        if cmd == _CO2_READY:
            return add_crcs(b"\x80\x01" if self.co2_measuring else b"\x80\x00")
        if cmd == _CO2_READ:
            w = self._world()
            return add_crcs(
                _u16(w["co2"])
                + _u16((w["temp"] + 45) * 65536 / 175)
                + _u16(w["rh"] * 65536 / 100)
            )
        if cmd == _CO2_SERIAL:
            return add_crcs(b"\x00\x00\x00\x01\x00\x02")
        return None
