"""Compact 12-byte uplink payload (for LoRaWAN-style links), big-endian.

| bytes | field        | type | scale          | unknown |
|-------|--------------|------|----------------|---------|
| 0-1   | temperature  | i16  | 0.01 degC      | 0x7FFF  |
| 2-3   | humidity     | u16  | 0.01 %RH       | 0xFFFF  |
| 4-5   | co2          | u16  | 1 ppm          | 0xFFFF  |
| 6-7   | pm2_5        | u16  | 0.1 ug/m3      | 0xFFFF  |
| 8-9   | pm10         | u16  | 0.1 ug/m3      | 0xFFFF  |
| 10    | vocIndex     | u8   | 2 index points | 0xFF    |
| 11    | noxIndex     | u8   | 2 index points | 0xFF    |

The index scale of 2 lets the 1..500 index fit in one byte.
``lorawan/decoder.js`` is the matching decoder (TTN / ChirpStack ``decodeUplink`` style).
"""

from __future__ import annotations

import struct

from airq.models import Reading


def _u16(value: float | None, scale: float) -> int:
    return 0xFFFF if value is None else max(0, min(0xFFFE, round(value * scale)))


def _u8(value: float | None) -> int:
    return 0xFF if value is None else max(0, min(0xFE, round(value / 2)))


def encode(r: Reading) -> bytes:
    temp = 0x7FFF if r.temperature_c is None else max(-0x8000, min(0x7FFE, round(r.temperature_c * 100)))
    return struct.pack(
        ">hHHHHBB",
        temp,
        _u16(r.humidity_pct, 100),
        _u16(r.co2_ppm, 1),
        _u16(r.pm2_5, 10),
        _u16(r.pm10, 10),
        _u8(r.voc_index),
        _u8(r.nox_index),
    )
