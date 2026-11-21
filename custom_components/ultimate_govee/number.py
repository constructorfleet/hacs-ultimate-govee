"""Number entities for heater targets and night-light brightness."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .entity_plan import PLATFORM_NUMBER, ControlContext, EntitySpec, entities_for_platform


def _govee_number(
    coordinator: GoveeCoordinator,
    device_id: str,
    spec: EntitySpec,
) -> GoveeNumber:
    return GoveeNumber(
        coordinator,
        device_id,
        spec,
        spec.name or spec.key,
        minimum=spec.minimum if spec.minimum is not None else 0.0,
        maximum=spec.maximum if spec.maximum is not None else 0.0,
        step=spec.step if spec.step is not None else 1.0,
        device_class=spec.device_class,
        unit=spec.unit,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities."""
    coordinator: GoveeCoordinator = entry.runtime_data
    entities: list[GoveeNumber] = []
    for device in coordinator.devices.values():
        entities.extend(
            _govee_number(coordinator, device.device_id, spec)
            for spec in entities_for_platform(device.profile, PLATFORM_NUMBER)
        )
    async_add_entities(entities)


class GoveeNumber(GoveeEntity, NumberEntity):
    """A numeric setting on a Govee device."""

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device_id: str,
        spec: EntitySpec,
        name: str,
        *,
        minimum: float,
        maximum: float,
        step: float,
        device_class: NumberDeviceClass | None = None,
        unit: str | None = None,
    ) -> None:
        super().__init__(coordinator, device_id, spec.key)
        self._spec = spec
        self._key = spec.key
        self._attr_name = name
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> float | None:
        """Return the current setting."""
        value = getattr(self.device.state, self._key, None)
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Apply the new setting."""
        if self._spec.control is None:
            return
        result = self._spec.control(ControlContext(self.device.profile, self.device.state, value))
        await self._send(result.command, dict(result.optimistic))
