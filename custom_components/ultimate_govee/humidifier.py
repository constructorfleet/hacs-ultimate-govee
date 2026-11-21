"""Humidifier entities for Govee humidifiers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.humidifier import (
    HumidifierEntity,
    HumidifierEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .entity_plan import (
    HUMIDIFIER_OPERATION_MODE,
    HUMIDIFIER_OPERATION_POWER,
    HUMIDIFIER_OPERATION_TARGET,
    PLATFORM_HUMIDIFIER,
    ControlContext,
    ControlResult,
    EntitySpec,
    entities_for_platform,
)
from .profiles import (
    FEATURE_MODE,
    FEATURE_TARGET_HUMIDITY,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up humidifier entities."""
    coordinator: GoveeCoordinator = entry.runtime_data
    async_add_entities(
        GoveeHumidifier(coordinator, device.device_id, spec)
        for device in coordinator.devices.values()
        for spec in entities_for_platform(device.profile, PLATFORM_HUMIDIFIER)
    )


class GoveeHumidifier(GoveeEntity, HumidifierEntity):
    """A Govee humidifier with mist levels and work modes."""

    _attr_min_humidity = 1
    _attr_max_humidity = 100

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device_id: str,
        spec: EntitySpec,
    ) -> None:
        super().__init__(coordinator, device_id, spec.key)
        self._spec = spec
        profile = self.device.profile
        features = HumidifierEntityFeature(0)
        if FEATURE_MODE in profile.features and profile.modes:
            features |= HumidifierEntityFeature.MODES
            self._attr_available_modes = list(profile.modes)
        self._attr_supported_features = features

    @property
    def is_on(self) -> bool:
        """Return whether the humidifier is running."""
        return bool(self.device.state.power)

    @property
    def target_humidity(self) -> int | None:
        """Return the target humidity."""
        return self.device.state.target_humidity

    @property
    def current_humidity(self) -> float | None:
        """Return the measured humidity."""
        return self.device.state.humidity

    @property
    def mode(self) -> str | None:
        """Return the active work mode."""
        return self.device.state.mode

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the humidifier on."""
        await self._async_send(self._control(HUMIDIFIER_OPERATION_POWER, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the humidifier off."""
        await self._async_send(self._control(HUMIDIFIER_OPERATION_POWER, False))

    async def async_set_humidity(self, humidity: int) -> None:
        """Set the target humidity."""
        if FEATURE_TARGET_HUMIDITY not in self.device.profile.features:
            return
        await self._async_send(self._control(HUMIDIFIER_OPERATION_TARGET, humidity))

    async def async_set_mode(self, mode: str) -> None:
        """Select a work mode."""
        if mode not in self.device.profile.modes:
            return
        await self._async_send(self._control(HUMIDIFIER_OPERATION_MODE, mode))

    def _control(self, operation: str, value: Any = None, **parameters: Any) -> ControlResult:
        if self._spec.control is None:
            raise ValueError("The humidifier plan has no control")
        return self._spec.control(
            ControlContext(
                self.device.profile,
                self.device.state,
                value,
                operation=operation,
                parameters=parameters,
            )
        )

    async def _async_send(self, result: ControlResult) -> None:
        await self._send(result.command, dict(result.optimistic))
