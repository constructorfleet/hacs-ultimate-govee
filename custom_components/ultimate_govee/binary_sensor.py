"""Binary sensors for Govee leak, presence, contact and tank alarms."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .profiles import binary_sensor_keys


@dataclass(frozen=True, kw_only=True)
class GoveeBinarySensorDescription(BinarySensorEntityDescription):
    """Description of one binary sensor."""

    state_key: str


BINARY_SENSOR_DESCRIPTIONS: dict[str, GoveeBinarySensorDescription] = {
    "leak": GoveeBinarySensorDescription(
        key="leak",
        state_key="leak",
        device_class=BinarySensorDeviceClass.MOISTURE,
        translation_key="leak",
    ),
    "presence": GoveeBinarySensorDescription(
        key="presence",
        state_key="presence",
        device_class=BinarySensorDeviceClass.PRESENCE,
    ),
    "contact": GoveeBinarySensorDescription(
        key="contact",
        state_key="contact",
        device_class=BinarySensorDeviceClass.OPENING,
        translation_key="contact",
    ),
    "water_shortage": GoveeBinarySensorDescription(
        key="water_shortage",
        state_key="water_shortage",
        device_class=BinarySensorDeviceClass.PROBLEM,
        translation_key="water_shortage",
    ),
    "basket_full": GoveeBinarySensorDescription(
        key="basket_full",
        state_key="basket_full",
        device_class=BinarySensorDeviceClass.PROBLEM,
        translation_key="basket_full",
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator: GoveeCoordinator = entry.runtime_data
    entities: list[GoveeBinarySensor] = []
    for device in coordinator.devices.values():
        for key in binary_sensor_keys(device.profile):
            description = BINARY_SENSOR_DESCRIPTIONS.get(key)
            if description is not None:
                entities.append(GoveeBinarySensor(coordinator, device.device_id, description))
    async_add_entities(entities)


class GoveeBinarySensor(GoveeEntity, BinarySensorEntity):
    """One binary reading from a Govee device."""

    entity_description: GoveeBinarySensorDescription

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device_id: str,
        description: GoveeBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        if description.translation_key is None:
            self._attr_name = description.key.replace("_", " ").title()

    @property
    def is_on(self) -> bool | None:
        """Return the alarm state."""
        return getattr(self.device.state, self.entity_description.state_key, None)
