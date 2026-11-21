"""Switch entities for Govee plugs, appliances and accessory functions."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .entity_plan import PLATFORM_SWITCH, ControlContext, EntitySpec, entities_for_platform


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches for every controllable Govee device."""
    coordinator: GoveeCoordinator = entry.runtime_data
    entities: list[GoveeSwitch] = []
    for device in coordinator.devices.values():
        entities.extend(
            GoveeSwitch(coordinator, device.device_id, spec)
            for spec in entities_for_platform(device.profile, PLATFORM_SWITCH)
        )
    async_add_entities(entities)


class GoveeSwitch(GoveeEntity, SwitchEntity):
    """A power switch, per-gang switch or accessory toggle."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device_id: str,
        spec: EntitySpec,
    ) -> None:
        super().__init__(coordinator, device_id, spec.key)
        self._spec = spec
        self._key = spec.key
        self._attr_name = spec.name
        self._attr_entity_category = spec.entity_category

    @property
    def is_on(self) -> bool:
        """Return the switch state."""
        state = self.device.state
        if self._key == "power":
            return bool(state.power)
        if self._key.startswith("gang"):
            index = int(self._key.removeprefix("gang"))
            return bool(state.gangs and index < len(state.gangs) and state.gangs[index])
        return bool(getattr(state, self._key, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch or function on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch or function off."""
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        if self._spec.control is None:
            return
        result = self._spec.control(ControlContext(self.device.profile, self.device.state, on))
        await self._send(result.command, dict(result.optimistic))
