"""Select entities for device-specific options."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .profiles import KIND_HEATER, KIND_ICE_MAKER
from .protocol import commands


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up selects for ice size and heater fan speed."""
    coordinator: GoveeCoordinator = entry.runtime_data
    entities: list[GoveeSelect] = []
    for device in coordinator.devices.values():
        if device.profile.kind == KIND_ICE_MAKER and device.profile.ice_sizes:
            entities.append(
                GoveeSelect(
                    coordinator,
                    device.device_id,
                    "ice_size",
                    "Ice size",
                    list(device.profile.ice_sizes),
                )
            )
        elif device.profile.kind == KIND_HEATER:
            entities.append(
                GoveeSelect(
                    coordinator,
                    device.device_id,
                    "fan_speed",
                    "Fan speed",
                    list(device.profile.modes) or ["low", "medium", "high"],
                )
            )
    async_add_entities(entities)


class GoveeSelect(GoveeEntity, SelectEntity):
    """A small enumerated setting."""

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device_id: str,
        key: str,
        name: str,
        options: list[str],
    ) -> None:
        super().__init__(coordinator, device_id, key)
        self._key = key
        self._attr_name = name
        self._attr_options = options

    @property
    def current_option(self) -> str | None:
        """Return the selected option."""
        if self._key == "fan_speed":
            speed = self.device.state.fan_speed
            options = self._attr_options
            if isinstance(speed, int) and 1 <= speed <= len(options):
                return options[speed - 1]
            return None
        value = getattr(self.device.state, self._key, None)
        return str(value) if value is not None else None

    async def async_select_option(self, option: str) -> None:
        """Apply the selected option."""
        profile = self.device.profile
        if self._key == "ice_size":
            await self._send(commands.ice_size(profile, option), {"ice_size": option})
            return
        if self._key == "fan_speed":
            level = self._attr_options.index(option) + 1
            await self._send(
                commands.heater_speed(profile, level),
                {
                    "fan_speed": level,
                    "percentage": round(level * 100 / len(self._attr_options)),
                },
            )
