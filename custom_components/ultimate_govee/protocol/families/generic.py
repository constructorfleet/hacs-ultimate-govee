"""Compatibility dialect for SKUs without a moved, evidenced codec.

The encoders here wrap the pre-dialect behaviour for humidifiers other than
H7141/H7142, dehumidifiers and accessory registers no moved family owns. They
are a fallback, not an inference that those SKUs are byte-identical:
:class:`~.base.FamilyDialect` entries for observed variants take precedence and
are assigned per SKU.
"""

from __future__ import annotations

from typing import Any

from ..codec import build_frame_b64
from ..command import (
    ACTION_DISPLAY,
    ACTION_HUMIDIFIER_MODE,
    ACTION_HUMIDIFIER_TARGET,
    ACTION_LOCK,
    ACTION_MIST_LEVEL,
    ACTION_NIGHT_LIGHT,
    ACTION_OSCILLATION,
    ACTION_TIMER,
    ACTION_UV,
    STRATEGY_PT_REAL,
    Command,
    frames_command,
)
from .base import FamilyDialect

HUMIDIFIER_MODE_MANUAL = 0x01
HUMIDIFIER_MODE_PROGRAM = 0x02
HUMIDIFIER_MODE_AUTO = 0x03

HUMIDIFIER_MODES: dict[str, int] = {
    "manual": HUMIDIFIER_MODE_MANUAL,
    "program": HUMIDIFIER_MODE_PROGRAM,
    "auto": HUMIDIFIER_MODE_AUTO,
}

FAN_OSCILLATION_REGISTER = 0x1F


def frame_command(
    register: int,
    values: Any = (),
    *,
    opcode: int = 0x33,
    strategy: str = STRATEGY_PT_REAL,
) -> Command:
    """Build a command from one register frame."""
    return frames_command(
        [build_frame_b64(register, values, opcode=opcode)],
        strategy=strategy,
    )


class GenericDialect(FamilyDialect):
    """The conservative fallback used when no variant was observed."""

    name = "generic"
    source = "pre-dialect behaviour, wrapped"
    confidence = "low"

    def encode(
        self,
        _profile: Any,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_NIGHT_LIGHT:
            return self._night_light(parameters)
        if action == ACTION_DISPLAY:
            return frame_command(0x16, [1 if parameters["on"] else 0])
        if action == ACTION_LOCK:
            return frame_command(0x0A, [1 if parameters["on"] else 0])
        if action == ACTION_UV:
            return frame_command(0x1A, [1 if parameters["on"] else 0])
        if action == ACTION_TIMER:
            minutes = max(0, min(0xFFFF, int(parameters["minutes"])))
            return frame_command(
                0x0A,
                [0x0B, 1 if parameters["enabled"] else 0, minutes >> 8, minutes & 0xFF],
            )
        if action == ACTION_OSCILLATION:
            return frame_command(FAN_OSCILLATION_REGISTER, [0x01, 1 if parameters["on"] else 0])
        if action == ACTION_MIST_LEVEL:
            return frame_command(
                0x05, [HUMIDIFIER_MODE_MANUAL, max(1, min(9, int(parameters["level"])))]
            )
        if action == ACTION_HUMIDIFIER_MODE:
            value = HUMIDIFIER_MODES.get(str(parameters["mode"]).lower(), HUMIDIFIER_MODE_AUTO)
            return frame_command(0x05, [0x00, value])
        if action == ACTION_HUMIDIFIER_TARGET:
            return frame_command(0x05, [HUMIDIFIER_MODE_AUTO, self._humidity(parameters)])
        return None

    def _night_light(self, parameters: dict[str, Any]) -> Command:
        level = max(0, min(100, int(parameters.get("brightness", 100))))
        red, green, blue = (
            max(0, min(255, int(value))) for value in parameters.get("rgb", (255, 255, 255))
        )
        if not parameters["on"]:
            return frame_command(0x1B, [0])
        return frame_command(0x1B, [1, level, red, green, blue])

    @staticmethod
    def _humidity(parameters: dict[str, Any]) -> int:
        return max(1, min(100, int(parameters["target"])))


GENERIC = GenericDialect()
