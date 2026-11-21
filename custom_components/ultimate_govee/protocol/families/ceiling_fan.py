"""Ceiling-fan dialect (H1310, H1370, R1310).

These SKUs carry an H1/R1 prefix but are ceiling fans. They share the 0x31
speed register and report the main zone on 0x36; the dialect is assigned by
exact SKU so the prefix collision cannot select it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..command import ACTION_FAN_POWER, ACTION_FAN_SPEED, Command
from .base import FamilyDialect
from .generic import frame_command

if TYPE_CHECKING:
    from ...profiles import DeviceProfile


class CeilingFanDialect(FamilyDialect):
    """The 0x31 ceiling-fan handler."""

    name = "ceiling_fan"
    source = "verified ceiling-fan handler"
    confidence = "medium"

    def encode(
        self,
        profile: DeviceProfile,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_FAN_POWER:
            level = max(1, min(profile.fan_speeds or 6, int(parameters.get("level", 1))))
            return frame_command(0x31, [1 if parameters["on"] else 0, level])
        if action == ACTION_FAN_SPEED:
            level = max(1, min(profile.fan_speeds or 6, int(parameters["level"])))
            return frame_command(0x31, [0x01, level])
        return None

    def decode_frame(
        self,
        profile: DeviceProfile,
        register: int,
        payload: bytes,
        result: dict[str, Any],
    ) -> bool:
        if register == 0x31 and payload:
            # AA 31 <running> <speed> <direction>. Oscillation is OpenAPI-only.
            result["power"] = payload[0] != 0
            if len(payload) > 1:
                result["fan_speed"] = payload[1]
                if profile.fan_speeds:
                    result["percentage"] = round(payload[1] * 100 / profile.fan_speeds)
            return True
        if register == 0x36 and payload:
            # The first byte reports whether the main zone is powered. Keep any
            # power already reported by another frame in the same message.
            result.setdefault("power", payload[0] != 0)
            result["night_light"] = payload[0] != 0
            return True
        return False
