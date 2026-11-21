"""Ice-maker dialects.

The two observed variants differ only in the ice-size direction: H8121/H8122
send small..large in ascending register values, the older handler reverses the
order. H8120 also powers on register 0x01 instead of the ``turn`` verb. Each
SKU is assigned individually even where the bytes match the shipped handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..command import (
    ACTION_ICE_POWER,
    ACTION_ICE_SIZE,
    ACTION_POWER,
    Command,
)
from .base import FamilyDialect
from .generic import frame_command

if TYPE_CHECKING:
    from ...profiles import DeviceProfile

ICE_SIZES = ("small", "medium", "large")


class IceMakerDialect(FamilyDialect):
    """The older ice-size direction, with power on the ``turn`` verb."""

    name = "ice_maker"
    source = "verified ice-maker handler"
    confidence = "medium"
    ascending = False
    power_register = False

    def encode(
        self,
        profile: DeviceProfile,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_ICE_POWER:
            return self._power(parameters)
        if action == ACTION_ICE_SIZE:
            return frame_command(0x05, [self._size_value(profile, parameters["size"])])
        return None

    def decode_frame(
        self,
        profile: DeviceProfile,
        register: int,
        payload: bytes,
        result: dict[str, Any],
    ) -> bool:
        if register == 0x05 and payload:
            index = payload[0] if payload[0] <= 3 else payload[-1]
            sizes = profile.ice_sizes or ICE_SIZES
            size_index = index - 1 if self.ascending else len(sizes) - index
            if 0 <= size_index < len(sizes):
                result["ice_size"] = sizes[size_index]
            return True
        if register == 0x19 and payload:
            result["basket_full"] = payload[0] != 0
            return True
        return False

    def _power(self, parameters: dict[str, Any]) -> Command:
        if self.power_register:
            return frame_command(0x01, [1 if parameters["on"] else 0])
        if not parameters["on"]:
            return frame_command(0x19, [0])
        return Command(ACTION_POWER, {"on": True})

    def _size_value(self, profile: DeviceProfile, size: str) -> int:
        sizes = profile.ice_sizes or ICE_SIZES
        try:
            index = sizes.index(str(size).lower()) + 1
        except ValueError:
            index = 1
        if not self.ascending:
            index = len(sizes) + 1 - index
        return index


class IceMakerAscendingDialect(IceMakerDialect):
    """H8121/H8122: ice size ascends with the register value."""

    name = "ice_maker_ascending"
    source = "verified H8121/H8122 ice-size handler"
    confidence = "medium"
    ascending = True


class IceMakerH8120Dialect(IceMakerDialect):
    """H8120: power is register 0x01; the off frame is not 0x19."""

    name = "ice_maker_h8120"
    source = "verified H8120 power handler"
    confidence = "medium"
    power_register = True
