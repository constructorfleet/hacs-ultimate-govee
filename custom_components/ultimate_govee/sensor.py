"""Sensor entities for Govee devices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfDensity,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfRatio,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .profiles import sensor_keys

AIR_QUALITY_OPTIONS = ["excellent", "good", "moderate", "poor"]
AIR_QUALITY_MAP = {1: "excellent", 2: "good", 3: "moderate", 4: "poor"}


@dataclass(frozen=True, kw_only=True)
class GoveeSensorDescription(SensorEntityDescription):
    """Description of one sensor key."""

    state_key: str


SENSOR_DESCRIPTIONS: dict[str, GoveeSensorDescription] = {
    "temperature": GoveeSensorDescription(
        key="temperature",
        state_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "humidity": GoveeSensorDescription(
        key="humidity",
        state_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "battery": GoveeSensorDescription(
        key="battery",
        state_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "pm25": GoveeSensorDescription(
        key="pm25",
        state_key="pm25",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "co2": GoveeSensorDescription(
        key="co2",
        state_key="co2",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "air_quality": GoveeSensorDescription(
        key="air_quality",
        state_key="air_quality",
        device_class=SensorDeviceClass.ENUM,
        options=AIR_QUALITY_OPTIONS,
        translation_key="air_quality",
    ),
    "filter_life": GoveeSensorDescription(
        key="filter_life",
        state_key="filter_life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:air-filter",
        translation_key="filter_life",
    ),
    "voltage": GoveeSensorDescription(
        key="voltage",
        state_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "current": GoveeSensorDescription(
        key="current",
        state_key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "power_usage": GoveeSensorDescription(
        key="power_usage",
        state_key="power_usage",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for every device that reports readings."""
    coordinator: GoveeCoordinator = entry.runtime_data
    entities: list[GoveeSensor] = []
    for device in coordinator.devices.values():
        keys = list(sensor_keys(device.profile))
        if device.sku == "H5086":
            keys.extend(("voltage", "current", "power_usage"))
        entities.extend(
            GoveeSensor(coordinator, device.device_id, SENSOR_DESCRIPTIONS[key])
            for key in keys
            if key in SENSOR_DESCRIPTIONS
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
    ) -> None:
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        if description.translation_key is None:
            self._attr_name = description.key.replace("_", " ").title()

    @property
    def native_value(self) -> Any:
        """Return the latest reading."""
        value = getattr(self.device.state, self.entity_description.state_key, None)
        if self.entity_description.key == "air_quality" and isinstance(value, int):
            return AIR_QUALITY_MAP.get(value)
        return value
