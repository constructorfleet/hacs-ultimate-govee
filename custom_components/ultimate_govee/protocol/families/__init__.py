"""Family dialect registry and dispatch.

The registry maps an explicit dialect name to the module that owns its encode
and decode. ``profiles.py`` assigns the name per SKU; nothing here infers a
dialect from kind, category or SKU prefix.

Encoding asks the SKU's dialect first and then the generic fallback; decoding
follows the same rule, with the generic dialect owning the universal registers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...profiles import SKU_ROWS
from .base import FamilyDialect
from .ceiling_fan import CeilingFanDialect
from .dehumidifier import DehumidifierDialect
from .fan import FanAuto02Dialect, FanDialect
from .generic import GENERIC
from .heater1 import Heater1Dialect
from .heater2 import Heater2Dialect
from .humidifier import H7141Dialect, H7142Dialect
from .ice_maker import IceMakerAscendingDialect, IceMakerDialect, IceMakerH8120Dialect
from .purifier import Purifier3ADialect, PurifierH7120Dialect, PurifierH7126Dialect

if TYPE_CHECKING:
    from ...profiles import DeviceProfile

DIALECTS: dict[str, FamilyDialect] = {
    GENERIC.name: GENERIC,
    "ceiling_fan": CeilingFanDialect(),
    "dehumidifier": DehumidifierDialect(),
    "fan": FanDialect(),
    "fan_h7105": FanAuto02Dialect(),
    "heater1": Heater1Dialect(),
    "heater2": Heater2Dialect(),
    "humidifier_h7141": H7141Dialect(),
    "humidifier_h7142": H7142Dialect(),
    "purifier_3a": Purifier3ADialect(),
    "purifier_h7120": PurifierH7120Dialect(),
    "purifier_h7126": PurifierH7126Dialect(),
    "ice_maker": IceMakerDialect(),
    "ice_maker_ascending": IceMakerAscendingDialect(),
    "ice_maker_h8120": IceMakerH8120Dialect(),
}


def _validate_sku_rows() -> None:
    """Fail at import when a SKU row names a dialect nobody implements."""
    missing = {row.dialect for row in SKU_ROWS.values()} - set(DIALECTS)
    if missing:
        raise ValueError(f"SKU rows reference unknown dialects: {sorted(missing)}")


_validate_sku_rows()


def dialect_for(profile: DeviceProfile) -> FamilyDialect:
    """Return the dialect the profile assigned, falling back explicitly."""
    return DIALECTS.get(profile.dialect, GENERIC)


def decode_register(
    profile: DeviceProfile,
    register: int,
    payload: bytes,
    result: dict[str, Any],
) -> None:
    """Decode one register with the SKU's dialect, then the generic fallback."""
    dialect = dialect_for(profile)
    if dialect.decode_frame(profile, register, payload, result):
        return
    if dialect is not GENERIC:
        GENERIC.decode_frame(profile, register, payload, result)


def decode_raw(profile: DeviceProfile, frame: bytes, result: dict[str, Any]) -> bool:
    """Decode a whole-frame report with the SKU's dialect, then the fallback."""
    dialect = dialect_for(profile)
    if dialect.decode_raw(profile, frame, result):
        return True
    return dialect is not GENERIC and GENERIC.decode_raw(profile, frame, result)
