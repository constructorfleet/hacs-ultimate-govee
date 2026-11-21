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
from .profiles import (
    FEATURE_MODE,
    FEATURE_TARGET_HUMIDITY,
    KIND_HUMIDIFIER,
)
from .protocol import commands


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up humidifier entities."""
    coordinator: GoveeCoordinator = entry.runtime_data
    async_add_entities(
        GoveeHumidifier(coordinator, device.device_id)
        for device in coordinator.devices.values()
        if device.profile.kind == KIND_HUMIDIFIER
    )


class GoveeHumidifier(GoveeEntity, HumidifierEntity):
    """A Govee humidifier with mist levels and work modes."""

    _attr_min_humidity = 1
    _attr_max_humidity = 100

    def __init__(self, coordinator: GoveeCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "humidifier")
        profile = self.device.profile
        features = HumidifierEntityFeature(0)
        if FEATURE_TARGET_HUMIDITY in profile.features:
            features |= HumidifierEntityFeature.TARGET_HUMIDITY
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
        await self._send(commands.power(self.device.profile, True), {"power": True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the humidifier off."""
        await self._send(commands.power(self.device.profile, False), {"power": False})

    async def async_set_humidity(self, humidity: int) -> None:
        """Set the target humidity."""
        if FEATURE_TARGET_HUMIDITY not in self.device.profile.features:
            return
        await self._send(
            commands.humidifier_target(humidity),
            {"target_humidity": humidity, "mode": "auto"},
        )

    async def async_set_mode(self, mode: str) -> None:
        """Select a work mode."""
        if mode not in self.device.profile.modes:
            return
        if mode == "auto":
            await self._send(
                commands.humidifier_target(self.device.state.target_humidity or 50),
                {"mode": "auto", "power": True},
            )
            return
        if mode == "manual":
            level = self.device.state.fan_speed or 5
            await self._send(commands.mist_level(level), {"mode": "manual", "power": True})
            return
        await self._send(
            commands.humidifier_mode(self.device.profile, mode),
            {"mode": mode},
        )
