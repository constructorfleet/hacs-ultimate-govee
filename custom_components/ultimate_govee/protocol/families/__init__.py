"""Family dialect registry.

The registry maps an explicit dialect name to the module that owns its encode
and decode. ``profiles.py`` assigns the name per SKU; nothing here infers a
dialect from kind, category or SKU prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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


def dialect_for(profile: DeviceProfile) -> FamilyDialect:
    """Return the dialect the profile assigned, falling back explicitly."""
    return DIALECTS.get(profile.dialect, GENERIC)
