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
from .entity_plan import (
    FAN_OPERATION_MODE,
    FAN_OPERATION_OSCILLATE,
    FAN_OPERATION_POWER,
    FAN_OPERATION_SPEED,
    PLATFORM_FAN,
    ControlContext,
    ControlResult,
    EntitySpec,
    entities_for_platform,
)
from .profiles import KIND_FAN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up fan entities."""
    coordinator: GoveeCoordinator = entry.runtime_data
    async_add_entities(
        GoveeFan(coordinator, device.device_id, spec)
        for device in coordinator.devices.values()
        for spec in entities_for_platform(device.profile, PLATFORM_FAN)
    )


class GoveeFan(GoveeEntity, FanEntity):
    """A fan, purifier or dehumidifier."""

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device_id: str,
        spec: EntitySpec,
    ) -> None:
        super().__init__(coordinator, device_id, spec.key)
        self._spec = spec
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
        result = self._control(FAN_OPERATION_POWER, True, speed=speed)
        await self._send(result.command, dict(result.optimistic))
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        elif percentage is not None:
            await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        speed = self._percentage_to_level(self.percentage)
        result = self._control(FAN_OPERATION_POWER, False, speed=speed)
        await self._send(result.command, dict(result.optimistic))

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the fan speed."""
        if percentage <= 0:
            await self.async_turn_off()
            return
        result = self._control(FAN_OPERATION_SPEED, percentage)
        await self._send(result.command, dict(result.optimistic))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Select a work mode."""
        result = self._control(FAN_OPERATION_MODE, preset_mode)
        await self._send(result.command, dict(result.optimistic))

    async def async_oscillate(self, oscillating: bool) -> None:
        """Turn oscillation on or off."""
        if "oscillation" not in self.device.profile.features:
            return
        result = self._control(FAN_OPERATION_OSCILLATE, oscillating)
        await self._send(result.command, dict(result.optimistic))

    def _control(
        self,
        operation: str,
        value: Any,
        **parameters: Any,
    ) -> ControlResult:
        if self._spec.control is None:
            raise ValueError("The fan plan has no control")
        return self._spec.control(
            ControlContext(
                self.device.profile,
                self.device.state,
                value,
                operation=operation,
                parameters=parameters,
            )
        )

    def _percentage_to_level(self, percentage: int | None) -> int:
        """Map a percentage to a 1-based speed level."""
        if percentage is None or not self._speeds:
            return 1
        selected = percentage_to_ordered_list_item(list(self._speeds), percentage)
        return int(selected)
