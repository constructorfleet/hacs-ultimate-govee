"""Tower-fan dialect (H710x/H711x).

The shipped handler sends every tower fan the same 0x01 power, 0x05 speed and
0x1B night-light registers. H7105/H7107 differ only in the auto-mode byte;
they are explicit SKU assignments to that observed variant rather than a
prefix rule.

The 0x05 speed report is command-only: the integration has no verified
tower-fan speed report layout, so this dialect does not invent one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..codec import build_frame_b64
from ..command import (
    ACTION_FAN_MODE,
    ACTION_FAN_POWER,
    ACTION_FAN_SPEED,
    ACTION_NIGHT_LIGHT,
    ACTION_OSCILLATION,
    Command,
    frames_command,
)
from .base import FamilyDialect
from .common import apply_night_light
from .generic import frame_command

if TYPE_CHECKING:
    from ...profiles import DeviceProfile

FAN_NIGHT_LIGHT_OPCODE = 0x3A


class FanDialect(FamilyDialect):
    """The tower-fan register set."""

    name = "fan"
    source = "verified tower-fan handler"
    confidence = "medium"
    auto_mode_byte = 0x03

    def encode(
        self,
        profile: DeviceProfile,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_FAN_POWER:
            return frame_command(0x01, [1 if parameters["on"] else 0])
        if action == ACTION_FAN_SPEED:
            level = max(1, min(profile.fan_speeds or 8, int(parameters["level"])))
            return frame_command(0x05, [0x01, level])
        if action == ACTION_FAN_MODE:
            automatic = str(parameters["mode"]).lower() == "auto"
            return frame_command(0x05, [0x00, self.auto_mode_byte if automatic else 0x01])
        if action == ACTION_NIGHT_LIGHT:
            return self._night_light(parameters)
        if action == ACTION_OSCILLATION:
            return frame_command(0x1F, [0x01, 1 if parameters["on"] else 0])
        return None

    def decode_frame(
        self,
        profile: DeviceProfile,
        register: int,
        payload: bytes,
        result: dict[str, Any],
    ) -> bool:
        if register == 0x1B and payload:
            apply_night_light(payload, result)
            return True
        if register == 0x1F and len(payload) >= 3:
            result["oscillation"] = payload[1] != 0
            result["lock"] = payload[2] != 0
            return True
        return False

    @staticmethod
    def _night_light(parameters: dict[str, Any]) -> Command:
        level = max(0, min(100, int(parameters.get("brightness", 100))))
        red, green, blue = (
            max(0, min(255, int(value))) for value in parameters.get("rgb", (255, 255, 255))
        )
        if not parameters["on"]:
            return frame_command(0x1B, [0x01, 0x01, 0x00], opcode=FAN_NIGHT_LIGHT_OPCODE)
        return frames_command(
            [
                build_frame_b64(0x1B, [0x01, 0x01, 0x01], opcode=FAN_NIGHT_LIGHT_OPCODE),
                build_frame_b64(0x1B, [0x01, 0x02, level], opcode=FAN_NIGHT_LIGHT_OPCODE),
                build_frame_b64(0x05, [0x0D, red, green, blue], opcode=FAN_NIGHT_LIGHT_OPCODE),
            ]
        )


class FanAuto02Dialect(FanDialect):
    """H7105/H7107 use auto-mode byte 0x02 instead of 0x03."""

    name = "fan_h7105"
    source = "verified H7105/H7107 auto-mode handling"
    confidence = "medium"
    auto_mode_byte = 0x02
