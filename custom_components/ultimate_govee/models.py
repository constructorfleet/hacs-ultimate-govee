"""Device and state models for the Ultimate Govee integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DeviceState:
    """The last known state of a device.

    Govee devices are not consistent about which fields they report, so every
    field is optional. Entities only expose a control when the device profile
    says the device understands it.
    """

    online: bool = False
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
    display: bool | None = None
    lock: bool | None = None
    uv: bool | None = None
    filter_life: int | None = None
    water_shortage: bool | None = None
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
    current_temperature: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def update_from(self, data: dict[str, Any]) -> None:
        """Merge a decoded partial state into this state."""
        for key, value in data.items():
            if value is None:
                continue
            if key == "color" and isinstance(value, (list, tuple)) and len(value) == 3:
                self.color = (int(value[0]), int(value[1]), int(value[2]))
            elif hasattr(self, key):
                setattr(self, key, value)
            else:
                self.extra[key] = value


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

    @property
    def available(self) -> bool:
        """Return whether the device can currently be reached."""
        return self.state.online or self.lan_ip is not None

    @property
    def lan_reachable(self) -> bool:
        """Return whether the device has been seen on the LAN recently."""
        return self.lan_ip is not None
