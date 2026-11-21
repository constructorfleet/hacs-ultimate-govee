"""Humidifier dialects, including the first concrete H7141/H7142 pair.

H7141 and H7142 are individual dialect entries because the profile differences
are real: H7142 adds UVC and the 0x1B night light and reports nine mist levels.
The shared mode, target and mist register bytes come from the verified handler
the integration already shipped; H7142 overrides the extra registers instead of
sharing them implicitly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..codec import build_frame_b64
from ..command import (
    ACTION_HUMIDIFIER_MODE,
    ACTION_HUMIDIFIER_TARGET,
    ACTION_MIST_LEVEL,
    ACTION_NIGHT_LIGHT,
    ACTION_UV,
    Command,
    frames_command,
)
from .base import FamilyDialect
from .common import (
    apply_humidity_reading,
    apply_night_light,
    decode_humidifier_register_05,
)
from .generic import HUMIDIFIER_MODE_AUTO, HUMIDIFIER_MODES, frame_command

if TYPE_CHECKING:
    from ...profiles import DeviceProfile


class HumidifierDialect(FamilyDialect):
    """The mode/target/mist register set shared by the H714x handlers."""

    name = "humidifier"
    source = "verified H714x handler"
    confidence = "medium"

    def encode(
        self,
        profile: DeviceProfile,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_MIST_LEVEL:
            return frame_command(0x05, [0x01, max(1, min(9, int(parameters["level"])))])
        if action == ACTION_HUMIDIFIER_MODE:
            value = HUMIDIFIER_MODES.get(str(parameters["mode"]).lower(), HUMIDIFIER_MODE_AUTO)
            return frame_command(0x05, [0x00, value])
        if action == ACTION_HUMIDIFIER_TARGET:
            target = max(1, min(100, int(parameters["target"])))
            return frame_command(0x05, [HUMIDIFIER_MODE_AUTO, target])
        return None

    def decode_frame(
        self,
        profile: DeviceProfile,
        register: int,
        payload: bytes,
        result: dict[str, Any],
    ) -> bool:
        if register == 0x05 and payload:
            decode_humidifier_register_05(profile, payload, result)
            return True
        if register == 0x10 and len(payload) >= 4:
            apply_humidity_reading(payload, result)
            return True
        return False


class H7141Dialect(HumidifierDialect):
    """H7141: manual/auto/program and eight mist levels, no UVC."""

    name = "humidifier_h7141"
    source = "verified H7141 handler"
    confidence = "medium"


class H7142Dialect(HumidifierDialect):
    """H7142: H7141 bytes plus UVC and the 0x1B night light."""

    name = "humidifier_h7142"
    source = "verified H7142 handler (UV/night-light overrides)"
    confidence = "medium"

    def encode(
        self,
        profile: DeviceProfile,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_UV:
            return frame_command(0x1A, [1 if parameters["on"] else 0])
        if action == ACTION_NIGHT_LIGHT:
            return self._night_light(parameters)
        return super().encode(profile, action, parameters)

    def decode_frame(
        self,
        profile: DeviceProfile,
        register: int,
        payload: bytes,
        result: dict[str, Any],
    ) -> bool:
        if register == 0x1A and payload:
            result["uv"] = payload[0] != 0
            return True
        if register == 0x1B and payload:
            apply_night_light(payload, result)
            return True
        return super().decode_frame(profile, register, payload, result)

    @staticmethod
    def _night_light(parameters: dict[str, Any]) -> Command:
        if not parameters["on"]:
            return frame_command(0x1B, [0])
        level = max(0, min(100, int(parameters.get("brightness", 100))))
        red, green, blue = (
            max(0, min(255, int(value))) for value in parameters.get("rgb", (255, 255, 255))
        )
        return frames_command([build_frame_b64(0x1B, [1, level, red, green, blue])])
