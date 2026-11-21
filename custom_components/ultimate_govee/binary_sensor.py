"""Binary sensors for Govee leak, presence, contact and tank alarms."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .entity_plan import PLATFORM_BINARY_SENSOR, EntitySpec, entities_for_platform


@dataclass(frozen=True, kw_only=True)
class GoveeBinarySensorDescription(BinarySensorEntityDescription):
    """Description of one binary sensor."""

    state_key: str


def _description(spec: EntitySpec) -> GoveeBinarySensorDescription:
    return GoveeBinarySensorDescription(
        key=spec.key,
        state_key=spec.state_key or spec.key,
        device_class=spec.device_class,
        translation_key=spec.translation_key,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator: GoveeCoordinator = entry.runtime_data
    entities: list[GoveeBinarySensor] = []
    for device in coordinator.devices.values():
        entities.extend(
            GoveeBinarySensor(
                coordinator,
                device.device_id,
                _description(spec),
                spec.name,
            )
            for spec in entities_for_platform(device.profile, PLATFORM_BINARY_SENSOR)
        )
    async_add_entities(entities)


class GoveeBinarySensor(GoveeEntity, BinarySensorEntity):
    """One binary reading from a Govee device."""

    entity_description: GoveeBinarySensorDescription

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device_id: str,
        description: GoveeBinarySensorDescription,
        name: str | None = None,
    ) -> None:
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        if description.translation_key is None:
            self._attr_name = name or description.key.replace("_", " ").title()

    @property
    def is_on(self) -> bool | None:
        """Return the alarm state."""
        return getattr(self.device.state, self.entity_description.state_key, None)
