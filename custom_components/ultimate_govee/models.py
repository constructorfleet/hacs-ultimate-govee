"""Device and state models for the Ultimate Govee integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any

_LOGGER = logging.getLogger(__name__)

_COLOUR_FIELDS = frozenset({"color", "night_light_color"})


@dataclass(slots=True)
class DeviceState:
    """The last known state of a device.

    Govee devices are not consistent about which fields they report, so every
    field is optional. Entities only expose a control when the device profile
    says the device understands it. ``None`` means "not reported"; merges never
    clear a value that is not present in the incoming state.
    """

    online: bool | None = None
    power: bool | None = None
    brightness: int | None = None
    color: tuple[int, int, int] | None = None
    color_temp: int | None = None
    effect: str | None = None
    mode: str | None = None
    target_humidity: int | None = None
    humidity: float | None = None
    temperature: float | None = None
    fan_speed: int | None = None
    percentage: int | None = None
    oscillation: bool | None = None
    night_light: bool | None = None
    night_light_brightness: int | None = None
    night_light_color: tuple[int, int, int] | None = None
    display: bool | None = None
    lock: bool | None = None
    uv: bool | None = None
    filter_life: int | None = None
    water_shortage: bool | None = None
    # Reserved: kept in the vocabulary for devices that may report them, but
    # no decoder writes or reads them yet.
    tank_empty: bool | None = None
    timer_enabled: bool | None = None
    timer_minutes: int | None = None
    battery: int | None = None
    co2: int | None = None
    pm25: float | None = None
    air_quality: int | None = None
    voltage: float | None = None
    current: float | None = None
    power_usage: float | None = None
    gangs: tuple[bool, ...] | None = None
    leak: bool | None = None
    presence: bool | None = None
    contact: bool | None = None
    ice_size: str | None = None
    basket_full: bool | None = None
    target_temperature: float | None = None
    # Reserved: the appliance temperature readings are not reported yet.
    current_temperature: float | None = None

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> DeviceState:
        """Build a state from a decoded or optimistic mapping.

        Unknown keys are ignored so a payload typo from firmware (or a caller)
        can never add attributes to the state; they are logged at debug level
        to make such cases discoverable.
        """
        state = cls()
        known = {field_info.name for field_info in fields(cls)}
        for key, value in mapping.items():
            if key not in known:
                _LOGGER.debug("Ignoring unknown device state field %r", key)
                continue
            if value is None:
                continue
            setattr(state, key, _coerce_value(key, value))
        return state

    def merge_from(self, other: DeviceState) -> None:
        """Merge the fields set on ``other`` into this state.

        ``None`` marks a field as unreported for every field, so a partial
        update leaves previously known values untouched.
        """
        for field_info in fields(self):
            value = getattr(other, field_info.name)
            if value is None:
                continue
            setattr(self, field_info.name, _coerce_value(field_info.name, value))


def _coerce_value(key: str, value: Any) -> Any:
    """Normalise values that are safe to accept in more than one shape."""
    if key in _COLOUR_FIELDS and isinstance(value, (list, tuple)) and len(value) == 3:
        return (int(value[0]), int(value[1]), int(value[2]))
    return value


@dataclass(slots=True)
class GoveeDevice:
    """A Govee device known to the integration."""

    device_id: str
    sku: str
    name: str
    iot_topic: str | None
    firmware: str | None
    hardware: str | None
    settings: dict[str, Any]
    profile: Any
    state: DeviceState = field(default_factory=DeviceState)
    lan_ip: str | None = None
    lan_last_seen: float = 0.0
    raw_settings: dict[str, Any] = field(default_factory=dict)
    profile_inputs_warned: bool = False

    @property
    def available(self) -> bool:
        """Return whether the device can currently be reached."""
        return self.state.online or self.lan_ip is not None

    @property
    def lan_reachable(self) -> bool:
        """Return whether the device has been seen on the LAN recently."""
        return self.lan_ip is not None

    def observed_lan(self, ip: str, seen_at: float) -> None:
        """Record that the device answered on the local network."""
        self.lan_ip = ip
        self.lan_last_seen = seen_at
        self.state.online = True

    def lan_failed(self) -> None:
        """Forget a LAN endpoint that did not accept a command."""
        self.lan_ip = None
        self.lan_last_seen = 0.0
