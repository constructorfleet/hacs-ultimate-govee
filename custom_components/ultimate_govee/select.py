"""Select entities for device-specific options."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .entity_plan import PLATFORM_SELECT, ControlContext, EntitySpec, entities_for_platform


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up selects for ice size and heater fan speed."""
    coordinator: GoveeCoordinator = entry.runtime_data
    entities: list[GoveeSelect] = []
    for device in coordinator.devices.values():
        entities.extend(
            GoveeSelect(coordinator, device.device_id, spec)
            for spec in entities_for_platform(device.profile, PLATFORM_SELECT)
        )
    async_add_entities(entities)


class GoveeSelect(GoveeEntity, SelectEntity):
    """A small enumerated setting."""

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device_id: str,
        spec: EntitySpec,
    ) -> None:
        super().__init__(coordinator, device_id, spec.key)
        self._spec = spec
        self._key = spec.key
        self._attr_name = spec.name or spec.key
        self._attr_options = list(spec.options)

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
        if self._spec.control is None:
            return
        result = self._spec.control(
            ControlContext(
                self.device.profile,
                self.device.state,
                option,
                options=tuple(self._attr_options),
            )
        )
        await self._send(result.command, dict(result.optimistic))
