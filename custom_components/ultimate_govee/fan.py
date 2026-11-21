"""Fan entities for Govee tower/ceiling fans, purifiers and dehumidifiers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .profiles import (
    KIND_CEILING_FAN,
    KIND_DEHUMIDIFIER,
    KIND_FAN,
    KIND_PURIFIER,
)
from .protocol import commands

FAN_KINDS = {KIND_CEILING_FAN, KIND_DEHUMIDIFIER, KIND_FAN, KIND_PURIFIER}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up fan entities."""
    coordinator: GoveeCoordinator = entry.runtime_data
    async_add_entities(
        GoveeFan(coordinator, device.device_id)
        for device in coordinator.devices.values()
        if device.profile.kind in FAN_KINDS
    )


class GoveeFan(GoveeEntity, FanEntity):
    """A fan, purifier or dehumidifier."""

    def __init__(self, coordinator: GoveeCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "fan")
        profile = self.device.profile
        self._speeds = tuple(str(speed) for speed in range(1, profile.fan_speeds + 1))
        features = FanEntityFeature.SET_SPEED
        self._attr_supported_features = (
            features | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
        )
        if profile.modes:
            self._attr_supported_features |= FanEntityFeature.PRESET_MODE
            self._attr_preset_modes = list(profile.modes)
        if profile.kind == KIND_FAN and "oscillation" in profile.features:
            self._attr_supported_features |= FanEntityFeature.OSCILLATE

    @property
    def is_on(self) -> bool:
        """Return whether the fan is running."""
        return bool(self.device.state.power)

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        state = self.device.state
        if state.percentage is not None:
            return state.percentage
        if state.fan_speed and self._speeds:
            level = max(1, min(len(self._speeds), state.fan_speed))
            return ordered_list_item_to_percentage(list(self._speeds), str(level))
        return None

    @property
    def preset_mode(self) -> str | None:
        """Return the active preset/work mode."""
        return self.device.state.mode

    @property
    def oscillating(self) -> bool | None:
        """Return the oscillation state."""
        return self.device.state.oscillation

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn the fan on, optionally at a speed or preset."""
        speed = self._percentage_to_level(percentage)
        await self._send(self._power_command(True, speed), {"power": True})
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        elif percentage is not None:
            await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        speed = self._percentage_to_level(self.percentage)
        await self._send(self._power_command(False, speed), {"power": False})

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the fan speed."""
        profile = self.device.profile
        if percentage <= 0:
            await self.async_turn_off()
            return
        if profile.kind == KIND_PURIFIER:
            command = commands.purifier_speed(profile, percentage)
        else:
            command = commands.fan_speed(profile, self._percentage_to_level(percentage))
        await self._send(
            command,
            {"percentage": percentage, "fan_speed": self._percentage_to_level(percentage)},
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Select a work mode."""
        profile = self.device.profile
        if profile.kind == KIND_PURIFIER:
            command = commands.purifier_mode(profile, preset_mode)
        elif profile.kind == KIND_DEHUMIDIFIER:
            command = commands.dehumidifier_mode(preset_mode)
        else:
            command = commands.fan_mode(profile, preset_mode)
        await self._send(command, {"mode": preset_mode, "power": True})

    async def async_oscillate(self, oscillating: bool) -> None:
        """Turn oscillation on or off."""
        if "oscillation" not in self.device.profile.features:
            return
        await self._send(
            commands.oscillation(self.device.profile, oscillating),
            {"oscillation": oscillating},
        )

    def _power_command(self, on: bool, speed: int) -> commands.WireCommand:
        profile = self.device.profile
        if profile.kind in {KIND_PURIFIER, KIND_DEHUMIDIFIER}:
            return commands.power(profile, on)
        return commands.fan_power(profile, on, speed)

    def _percentage_to_level(self, percentage: int | None) -> int:
        """Map a percentage to a 1-based speed level."""
        if percentage is None or not self._speeds:
            return 1
        selected = percentage_to_ordered_list_item(list(self._speeds), percentage)
        return int(selected)
