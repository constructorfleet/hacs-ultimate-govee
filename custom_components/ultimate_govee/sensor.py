"""Sensor entities for Govee devices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .entity_plan import PLATFORM_SENSOR, EntitySpec, entities_for_platform

AIR_QUALITY_MAP = {1: "excellent", 2: "good", 3: "moderate", 4: "poor"}


@dataclass(frozen=True, kw_only=True)
class GoveeSensorDescription(SensorEntityDescription):
    """Description of one sensor key."""

    state_key: str


def _description(spec: EntitySpec) -> GoveeSensorDescription:
    return GoveeSensorDescription(
        key=spec.key,
        state_key=spec.state_key or spec.key,
        device_class=spec.device_class,
        native_unit_of_measurement=spec.unit,
        state_class=spec.state_class,
        options=list(spec.options) if spec.options else None,
        icon=spec.icon,
        translation_key=spec.translation_key,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for every device that reports readings."""
    coordinator: GoveeCoordinator = entry.runtime_data
    entities: list[GoveeSensor] = []
    for device in coordinator.devices.values():
        entities.extend(
            GoveeSensor(coordinator, device.device_id, _description(spec), spec.name)
            for spec in entities_for_platform(device.profile, PLATFORM_SENSOR)
        )
    async_add_entities(entities)


class GoveeSensor(GoveeEntity, SensorEntity):
    """One measurement from a Govee device."""

    entity_description: GoveeSensorDescription

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device_id: str,
        description: GoveeSensorDescription,
        name: str | None = None,
    ) -> None:
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        if description.translation_key is None:
            self._attr_name = name or description.key.replace("_", " ").title()

    @property
    def native_value(self) -> Any:
        """Return the latest reading."""
        value = getattr(self.device.state, self.entity_description.state_key, None)
        if self.entity_description.key == "air_quality" and isinstance(value, int):
            return AIR_QUALITY_MAP.get(value)
        return value
