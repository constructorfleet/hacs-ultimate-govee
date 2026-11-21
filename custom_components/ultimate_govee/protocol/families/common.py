"""Small decode helpers shared by family dialects.

These are report layouts, not SKU assignments. A dialect calls them for the
registers it owns; the generic decoder uses the same helper so a report cannot
decode differently depending on which path reached it.
"""

from __future__ import annotations

from typing import Any


def apply_humidity_reading(payload: bytes, result: dict[str, Any]) -> None:
    """Decode ``AA 10 <flags> <3-byte reading>``.

    The low 24 bits pack the humidity as tenths of a percent; the high bits
    carry the temperature in tenths of a degree.
    """
    flags = payload[0]
    if not flags & 0x81:
        return
    reading = (payload[1] << 16) | (payload[2] << 8) | payload[3]
    if reading == 0xFFFFFF:
        return
    result["humidity"] = round((reading & 0x7FFFFF) % 1000 / 10, 1)
    temperature = (reading // 1000) / 10
    if temperature:
        result["temperature"] = temperature


def apply_night_light(payload: bytes, result: dict[str, Any]) -> None:
    """Decode the ``0x1B`` night-light report shared by heaters and fans."""
    result["night_light"] = payload[0] != 0
    if len(payload) > 1:
        result["night_light_brightness"] = payload[1]
    if len(payload) > 4:
        result["night_light_color"] = (payload[2], payload[3], payload[4])
