"""Purifier dialects for the three observed speed layouts.

Each dialect owns its speed report and its speed command so the pair cannot
drift. The shared night-light, display and lock registers are implemented on
the base because the existing handler applies them to every purifier SKU.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..command import (
    ACTION_DISPLAY,
    ACTION_LOCK,
    ACTION_NIGHT_LIGHT,
    ACTION_PURIFIER_MODE,
    ACTION_PURIFIER_SPEED,
    Command,
)
from .base import FamilyDialect
from .generic import frame_command

if TYPE_CHECKING:
    from ...profiles import DeviceProfile

# Speed pairs for the 0x3A purifier family: (mode, first byte, second byte).
PURIFIER_3A_SPEEDS: tuple[tuple[str, int, int], ...] = (
    ("sleep", 0x05, 0x00),
    ("low", 0x01, 0x01),
    ("medium", 0x01, 0x02),
    ("high", 0x01, 0x03),
    ("auto", 0x03, 0x00),
)

# H7120/H7121 gear values: 25 % sends the special sleep gear 0x10.
PURIFIER_H7120_GEARS = (0x10, 0x01, 0x02, 0x03)


class PurifierDialect(FamilyDialect):
    """Registers every purifier handler shares, plus decode hooks."""

    name = "purifier"
    source = "verified purifier handler"
    confidence = "medium"

    def encode(
        self,
        profile: DeviceProfile,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_NIGHT_LIGHT:
            return frame_command(0x18, [1 if parameters["on"] else 0, 0x32])
        if action == ACTION_DISPLAY:
            return frame_command(0x16, [1 if parameters["on"] else 0])
        if action == ACTION_LOCK:
            return frame_command(0x10, [1 if parameters["on"] else 0])
        return None

    def decode_frame(
        self,
        profile: DeviceProfile,
        register: int,
        payload: bytes,
        result: dict[str, Any],
    ) -> bool:
        if register == 0x05 and payload:
            self.decode_speed(profile, payload, result)
            return True
        if register == 0x18 and payload:
            result["night_light"] = payload[0] != 0
            return True
        if register == 0x19 and payload:
            result["air_quality"] = payload[0]
            return True
        return False

    def decode_speed(self, profile: DeviceProfile, payload: bytes, result: dict[str, Any]) -> None:
        """Decode this variant's speed report (overridden per family)."""
        result["fan_speed"] = payload[0]
        result["percentage"] = _gear_percentage(profile, payload[0])


class Purifier3ADialect(PurifierDialect):
    """H7122/H7123/H7124: five steps on the 0x3A opcode."""

    name = "purifier_3a"
    source = "verified 0x3A purifier handler"
    confidence = "medium"

    def encode(
        self,
        profile: DeviceProfile,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_PURIFIER_SPEED:
            percent = max(0, min(100, int(parameters["percent"])))
            index = min(4, max(0, (percent - 1) // 20))
            _, mode, value = PURIFIER_3A_SPEEDS[index]
            return frame_command(0x05, [mode, value], opcode=0x3A)
        if action == ACTION_PURIFIER_MODE:
            mode = str(parameters["mode"]).lower()
            for name, first, second in PURIFIER_3A_SPEEDS:
                if name == mode:
                    return frame_command(0x05, [first, second], opcode=0x3A)
            return self.encode(profile, ACTION_PURIFIER_SPEED, {"percent": 100})
        return super().encode(profile, action, parameters)

    def decode_speed(self, profile: DeviceProfile, payload: bytes, result: dict[str, Any]) -> None:
        pair = (payload[0], payload[1] if len(payload) > 1 else 0)
        for index, (mode, first, second) in enumerate(PURIFIER_3A_SPEEDS, start=1):
            if pair == (first, second):
                result["mode"] = mode
                result["percentage"] = index * 20
                return


class PurifierH7120Dialect(PurifierDialect):
    """H7120/H7121: four gears with sleep as 0x10."""

    name = "purifier_h7120"
    source = "verified H7120 gear handler"
    confidence = "medium"

    def encode(
        self,
        profile: DeviceProfile,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_PURIFIER_SPEED:
            percent = max(0, min(100, int(parameters["percent"])))
            index = min(3, max(0, (percent - 1) // 25))
            return frame_command(0x05, [PURIFIER_H7120_GEARS[index]])
        if action == ACTION_PURIFIER_MODE:
            return self.encode(profile, ACTION_PURIFIER_SPEED, {"percent": 100})
        return super().encode(profile, action, parameters)

    def decode_speed(self, profile: DeviceProfile, payload: bytes, result: dict[str, Any]) -> None:
        # Reports put the gear in byte 3 or byte 4 depending on firmware.
        gear = payload[1] if len(payload) > 1 and payload[1] else payload[0]
        gear = max(1, min(4, gear))
        result["fan_speed"] = gear
        result["percentage"] = gear * 25
        result["mode"] = ("sleep", "low", "medium", "high")[gear - 1]


class PurifierH7126Dialect(PurifierDialect):
    """H7126 family: three levels under sub-command 0x01."""

    name = "purifier_h7126"
    source = "verified H7126 speed handler"
    confidence = "medium"

    def encode(
        self,
        profile: DeviceProfile,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_PURIFIER_SPEED:
            percent = max(0, min(100, int(parameters["percent"])))
            level = 1 if percent <= 33 else 2 if percent <= 66 else 3
            return frame_command(0x05, [0x01, level])
        if action == ACTION_PURIFIER_MODE:
            return self.encode(profile, ACTION_PURIFIER_SPEED, {"percent": 100})
        return super().encode(profile, action, parameters)

    def decode_speed(self, profile: DeviceProfile, payload: bytes, result: dict[str, Any]) -> None:
        level = payload[1] if payload[0] == 0x01 and len(payload) > 1 else payload[0]
        level = max(1, min(3, level))
        result["fan_speed"] = level
        result["percentage"] = level * 33
        result["mode"] = ("sleep", "low", "high")[level - 1]


def _gear_percentage(profile: DeviceProfile, gear: int) -> int:
    if profile.fan_speeds <= 0:
        return gear
    return max(0, min(100, round(gear * 100 / profile.fan_speeds)))
