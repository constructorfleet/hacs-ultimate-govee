"""Heater1 family dialect (H7130/H7137/H713A/H713C/H713E)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..command import (
    ACTION_HEATER_POWER,
    ACTION_HEATER_SPEED,
    ACTION_HEATER_TARGET,
    ACTION_LOCK,
    ACTION_OSCILLATION,
    Command,
)
from .base import FamilyDialect
from .generic import frame_command

if TYPE_CHECKING:
    from ...profiles import DeviceProfile


class Heater1Dialect(FamilyDialect):
    """The plain 0x33-opcode heater handler."""

    name = "heater1"
    source = "verified heater1 handler"
    confidence = "medium"

    def encode(
        self,
        profile: DeviceProfile,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_HEATER_POWER:
            return frame_command(0x01, [1 if parameters["on"] else 0])
        if action == ACTION_HEATER_SPEED:
            level = max(1, min(3, int(parameters["level"])))
            return frame_command(0x05, [level])
        if action == ACTION_HEATER_TARGET:
            return frame_command(0x1A, [0x00, 0x00, *_target_bytes(parameters["celsius"])])
        if action == ACTION_OSCILLATION:
            return frame_command(0x18, [1 if parameters["on"] else 0])
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
            level = max(1, min(3, payload[0]))
            result["fan_speed"] = level
            result["percentage"] = (33, 66, 99)[level - 1]
            result["mode"] = ("low", "medium", "high")[level - 1]
            return True
        if register == 0x18 and payload:
            result["oscillation"] = payload[0] != 0
            return True
        if register == 0x1A and len(payload) >= 4:
            _decode_target(payload, result)
            return True
        return False


def _target_bytes(celsius: float) -> tuple[int, int]:
    """Encode Celsius as the heater's hundredths-of-Fahrenheit wire value."""
    fahrenheit = celsius * 9 / 5 + 32
    raw = round(fahrenheit * 100) | 0x8000
    return raw >> 8, raw & 0xFF


def _decode_target(payload: bytes, result: dict[str, Any]) -> None:
    raw = (payload[2] << 8) | payload[3]
    if raw & 0x8000:
        fahrenheit = (raw & 0x7FFF) / 100
        result["target_temperature"] = round((fahrenheit - 32) * 5 / 9, 1)
