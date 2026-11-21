"""Family dialect contract.

A dialect owns both directions for one observed SKU variant: the register
frames it sends and the reports those frames must round-trip. Dialects are
selected per SKU by :mod:`..profiles` and never inferred from kind, category or
model prefix (ADR 0001).

Each dialect records where its assignment comes from so a low-confidence
wrapper of older behaviour is visible rather than implied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..command import Command

if TYPE_CHECKING:
    from ...profiles import DeviceProfile


class FamilyDialect:
    """Encode and decode the registers one family variant uses."""

    name = "generic"
    # Where the assignment comes from and how much evidence supports it.
    source = "unassigned"
    confidence = "low"

    def encode(
        self,
        profile: DeviceProfile,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        """Return the command for ``action`` or ``None`` when unowned."""
        return None

    def decode_frame(
        self,
        profile: DeviceProfile,
        register: int,
        payload: bytes,
        result: dict[str, Any],
    ) -> bool:
        """Decode a register this dialect owns and return whether it did."""
        return False
