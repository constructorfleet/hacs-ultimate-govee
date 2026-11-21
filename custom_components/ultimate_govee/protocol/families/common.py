"""Small encode/decode helpers shared by family dialects.

These are report layouts, not SKU assignments. A dialect calls them for the
registers it owns; the generic dialect uses the same helpers so a report cannot
decode differently depending on which module answered first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...profiles import DeviceProfile


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


def decode_humidifier_register_05(
    profile: DeviceProfile, payload: bytes, result: dict[str, Any]
) -> None:
    """Decode the humidifier mode/speed report registers."""
    sub = payload[0]
    if sub == 0x00 and len(payload) >= 2:
        result["mode"] = {1: "manual", 2: "program", 3: "auto"}.get(payload[1])
        if payload[1] == 0x03 and len(payload) > 2:
            result["target_humidity"] = payload[2]
    elif sub == 0x01 and len(payload) >= 2:
        result["mode"] = "manual"
        result["fan_speed"] = payload[1]
        result["percentage"] = gear_percentage(payload[1], profile.fan_speeds)
    elif sub == 0x02:
        result["mode"] = "program"
    elif sub == 0x03 and len(payload) >= 2:
        result["mode"] = "auto"
        result["target_humidity"] = payload[1]


def decode_light_register_05(payload: bytes, result: dict[str, Any]) -> bool:
    """Decode the light colour/effect sub-registers of ``0x05``."""
    sub = payload[0]
    if sub == 0x03 and len(payload) >= 4:
        result["color"] = (payload[1], payload[2], payload[3])
        return True
    if sub == 0x02 and len(payload) >= 3:
        result["effect"] = f"{(payload[1] << 8) | payload[2]:04x}"
        return True
    if sub == 0x15 and len(payload) >= 4:
        result["color"] = (payload[2], payload[3], payload[4] if len(payload) > 4 else 0)
        return True
    return False


def gear_percentage(gear: int, fan_speeds: int) -> int:
    """Convert a 1-based gear to Home Assistant's percentage."""
    if fan_speeds <= 0:
        return gear
    return max(0, min(100, round(gear * 100 / fan_speeds)))


def scale_brightness(profile: DeviceProfile, value: int) -> int:
    """Scale a raw brightness to Home Assistant's 0-100 range."""
    if profile.brightness_max > 100:
        return max(0, min(100, round(value * 100 / profile.brightness_max)))
    return max(0, min(100, value))


def decode_monitor_frame(frame: bytes, result: dict[str, Any]) -> None:
    """Decode the H5106's heuristic 20-byte air-quality frame."""
    temperature = ((frame[0] << 8) | frame[1]) / 100
    if not -30 <= temperature <= 80:
        return
    result["temperature"] = round(temperature, 1)
    if len(frame) >= 11:
        result["humidity"] = ((frame[9] << 8) | frame[10]) / 100
    if len(frame) >= 20:
        result["pm25"] = (frame[18] << 8) | frame[19]


def decode_co2_frame(payload: bytes, result: dict[str, Any]) -> None:
    """Decode the H5140 ``AA 0A`` little-endian temperature/humidity/CO2 frame."""
    if len(payload) < 6:
        return
    # The frame is AA 0A <temp lo> <temp hi> <rh lo> <rh hi> <co2 lo> <co2 hi>.
    temperature = (payload[0] | (payload[1] << 8)) / 100
    if -40 < temperature < 100:
        result["temperature"] = round(temperature, 2)
    humidity = payload[2] | (payload[3] << 8)
    result["humidity"] = max(0, min(100, round(humidity / 100)))
    co2 = payload[4] | (payload[5] << 8)
    if 0 <= co2 <= 40000:
        result["co2"] = co2


def decode_leak_frame(frame: bytes, result: dict[str, Any]) -> None:
    """Decode the gateway leak frame (``EE 34``) used by newer sensors."""
    if len(frame) < 4:
        return
    # The gateway reports the sensor's alarm bit in the first payload byte.
    result["leak"] = frame[2] != 0
