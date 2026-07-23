"""Wire-level protocol for Viatom / Wellue pulse-oximeter rings.

Pure module: no I/O, safe to import on any platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

SERVICE_UUID = "14839ac4-7d7e-415c-9a42-167340cf2339"

# The write-capable characteristic within SERVICE_UUID begins with this prefix.
# In observed devices the same characteristic also supports notify; the client
# falls back to any notify-capable characteristic in the service if this differs.
WRITE_CHAR_UUID_PREFIX = "8b00ace7"

# Magic payload the ring expects on the write characteristic to elicit a reading.
REQUEST_BYTES = b"\xaa\x17\xe8\x00\x00\x00\x00\x1b"

# Byte offsets within each notification packet.
_IDX_SPO2 = 7
_IDX_HR = 8
_IDX_BATTERY = 14
_IDX_MOVEMENT = 16
_IDX_PI = 17
_IDX_WORN = 18

_MIN_PACKET_LEN = _IDX_WORN + 1


@dataclass(frozen=True)
class Reading:
    """A single decoded notification from the ring."""

    spo2: int
    heart_rate: int
    battery: int
    movement: int
    perfusion_index: int
    worn: bool
    calibrating: bool
    raw: bytes
    received_at: datetime


def parse_notification(data: bytes, received_at: datetime | None = None) -> Reading | None:
    """Decode a raw notification payload into a Reading.

    Returns None if the packet is too short to contain the expected fields.
    """
    if data is None or len(data) < _MIN_PACKET_LEN:
        return None

    worn_byte = data[_IDX_WORN]
    spo2 = data[_IDX_SPO2]
    hr = data[_IDX_HR]

    worn = worn_byte != 0
    calibrating = worn and spo2 == 0 and hr == 0

    return Reading(
        spo2=spo2,
        heart_rate=hr,
        battery=data[_IDX_BATTERY],
        movement=data[_IDX_MOVEMENT],
        perfusion_index=data[_IDX_PI],
        worn=worn,
        calibrating=calibrating,
        raw=bytes(data),
        received_at=received_at or datetime.now(),
    )
