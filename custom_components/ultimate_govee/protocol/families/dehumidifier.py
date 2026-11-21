"""Dehumidifier family dialect (H7150/H7151/H7152).

The shipped handler uses the generic 0x05 work-mode and fan-speed registers.
Moving it here keeps the speed command and the speed report in one module now
that the generic fallback no longer owns fan actions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..command import (
    ACTION_DEHUMIDIFIER_MODE,
    ACTION_FAN_POWER,
    ACTION_FAN_SPEED,
    Command,
)
from .base import FamilyDialect
from .common import apply_humidity_reading
from .generic import frame_command

if TYPE_CHECKING:
    from ...profiles import DeviceProfile

DEHUMIDIFIER_MODES: dict[str, int] = {
    "low": 0x01,
    "high": 0x02,
    "auto": 0x03,
    "dryer": 0x08,
}


class DehumidifierDialect(FamilyDialect):
    """The 0x05 mode/speed and 0x10 humidity handler."""

    name = "dehumidifier"
    source = "verified dehumidifier handler"
    confidence = "medium"

    def encode(
        self,
        profile: DeviceProfile,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_DEHUMIDIFIER_MODE:
            value = DEHUMIDIFIER_MODES.get(str(parameters["mode"]).lower(), 0x03)
            return frame_command(0x05, [0x00, value])
        if action == ACTION_FAN_SPEED:
            level = max(1, min(profile.fan_speeds or 8, int(parameters["level"])))
            return frame_command(0x05, [0x01, level])
        if action == ACTION_FAN_POWER:
            return frame_command(0x01, [1 if parameters["on"] else 0])
        return None

    def decode_frame(
        self,
        profile: DeviceProfile,
        register: int,
        payload: bytes,
        result: dict[str, Any],
    ) -> bool:
        if register == 0x05 and payload:
            _decode_register_05(profile, payload, result)
            return True
        if register == 0x10 and len(payload) >= 4:
            apply_humidity_reading(payload, result)
            return True
        return False


def _decode_register_05(profile: DeviceProfile, payload: bytes, result: dict[str, Any]) -> None:
    sub = payload[0]
    if sub == 0x00 and len(payload) >= 2:
        result["mode"] = {1: "low", 2: "high", 3: "auto", 8: "dryer"}.get(
            payload[1], str(payload[1])
        )
    elif sub in (0x01, 0x02) and len(payload) >= 2:
        result["fan_speed"] = payload[1]
        result["percentage"] = _gear_percentage(profile, payload[1])
    elif len(payload) >= 2:
        result["fan_speed"] = payload[1]


def _gear_percentage(profile: DeviceProfile, gear: int) -> int:
    if profile.fan_speeds <= 0:
        return gear
    return max(0, min(100, round(gear * 100 / profile.fan_speeds)))
