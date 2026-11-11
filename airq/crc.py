"""CRC-8 as used on the wire by common I2C sensor chips.

Polynomial 0x31 (x^8 + x^5 + x^4 + 1), init 0xFF, no reflection, no final XOR,
computed over each 2-byte word. Documented example: crc8(0xBE 0xEF) == 0x92.
Implemented here (rather than imported) because the mock bus must *produce*
CRCs; the real driver verifies them independently.
"""

from __future__ import annotations

POLY = 0x31
INIT = 0xFF


def crc8(data: bytes) -> int:
    crc = INIT
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ POLY) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def add_crcs(payload: bytes) -> bytes:
    """Append a CRC after every 2-byte word: b'\xbe\xef' -> b'\xbe\xef\x92'."""
    if len(payload) % 2:
        raise ValueError("payload must be a whole number of 2-byte words")
    out = bytearray()
    for i in range(0, len(payload), 2):
        word = payload[i : i + 2]
        out += word
        out.append(crc8(word))
    return bytes(out)
