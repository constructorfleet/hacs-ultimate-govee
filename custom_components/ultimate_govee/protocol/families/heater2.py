"""Heater2 family dialect (H7131/H7132/H7133/H7134/H7135/H713B).

Heater2 shares H7131's 0x3A auto/fan-only sub-commands and wraps its appliance
commands in ``multiSync``. The other SKUs in the list are kept as individual
assignments to the same observed variant because the integration already
shipped them as one handler; no capture separates them yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..codec import build_frame_b64
from ..command import (
    ACTION_HEATER_POWER,
    ACTION_HEATER_SPEED,
    ACTION_HEATER_TARGET,
    ACTION_LOCK,
    ACTION_NIGHT_LIGHT,
    ACTION_OSCILLATION,
    STRATEGY_MULTI_SYNC,
    Command,
    frames_command,
)
from .base import FamilyDialect
from .common import apply_night_light
from .generic import frame_command
from .heater1 import _decode_target, _target_bytes

if TYPE_CHECKING:
    from ...profiles import DeviceProfile


class Heater2Dialect(FamilyDialect):
    """The ``0x3A`` / ``multiSync`` heater handler."""

    name = "heater2"
    source = "verified H7131 handler; other listed SKUs share the shipped path"
    confidence = "medium"

    def encode(
        self,
        profile: DeviceProfile,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_HEATER_POWER:
            return frame_command(0x01, [1 if parameters["on"] else 0], strategy=STRATEGY_MULTI_SYNC)
        if action == ACTION_HEATER_SPEED:
            level = max(1, min(4, int(parameters["level"])))
            values = [0x09] if level == 1 else [0x01, level - 1]
            return frame_command(0x05, values, opcode=0x3A, strategy=STRATEGY_MULTI_SYNC)
        if action == ACTION_HEATER_TARGET:
            high, low = _target_bytes(parameters["celsius"])
            return frame_command(
                0x05,
                [0x03, 0x01, high, low],
                opcode=0x3A,
                strategy=STRATEGY_MULTI_SYNC,
            )
        if action == ACTION_NIGHT_LIGHT:
            return self._night_light(parameters)
        if action == ACTION_OSCILLATION:
            return frame_command(
                0x1F,
                [0x01, 1 if parameters["on"] else 0],
                strategy=STRATEGY_MULTI_SYNC,
            )
        if action == ACTION_LOCK:
            return frame_command(
                0x1F,
                [0x02, 1 if parameters["on"] else 0],
                strategy=STRATEGY_MULTI_SYNC,
            )
        return None

    def decode_frame(
        self,
        profile: DeviceProfile,
        register: int,
        payload: bytes,
        result: dict[str, Any],
    ) -> bool:
        if register == 0x05 and payload:
            _decode_speed(payload, result)
            return True
        if register == 0x1F and len(payload) >= 3:
            result["oscillation"] = payload[1] != 0
            result["lock"] = payload[2] != 0
            return True
        if register == 0x1B and payload:
            apply_night_light(payload, result)
            return True
        if register == 0x1A and len(payload) >= 4:
            _decode_target(payload, result)
            return True
        return False

    @staticmethod
    def _night_light(parameters: dict[str, Any]) -> Command:
        if not parameters["on"]:
            return frames_command(
                [build_frame_b64(0x1B, [0x01, 0x01, 0])],
                strategy=STRATEGY_MULTI_SYNC,
            )
        level = max(0, min(100, int(parameters.get("brightness", 100))))
        red, green, blue = (
            max(0, min(255, int(value))) for value in parameters.get("rgb", (255, 255, 255))
        )
        return frames_command(
            [
                build_frame_b64(0x1B, [0x01, 0x01, 0x01]),
                build_frame_b64(0x1B, [0x01, 0x02, level]),
                build_frame_b64(0x1B, [0x05, 0x0D, red, green, blue]),
            ],
            strategy=STRATEGY_MULTI_SYNC,
        )


def _decode_speed(payload: bytes, result: dict[str, Any]) -> None:
    sub = payload[0]
    if sub == 0x09:
        result["mode"] = "fan-only"
        result["fan_speed"] = 1
        result["percentage"] = 25
    elif sub == 0x03:
        result["mode"] = "auto"
    elif sub == 0x01 and len(payload) > 1:
        level = max(1, min(3, payload[1])) + 1
        result["fan_speed"] = level
        result["percentage"] = level * 25
        result["mode"] = ("fan-only", "low", "medium", "high")[level - 1]
