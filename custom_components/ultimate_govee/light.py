"""Light entities for Govee LED products."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .entity_plan import (
    LIGHT_OPERATION_BRIGHTNESS,
    LIGHT_OPERATION_COLOR,
    LIGHT_OPERATION_COLOR_TEMP,
    LIGHT_OPERATION_EFFECT,
    LIGHT_OPERATION_POWER,
    PLATFORM_LIGHT,
    ControlContext,
    ControlResult,
    EntitySpec,
    entities_for_platform,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up light entities."""
    coordinator: GoveeCoordinator = entry.runtime_data
    async_add_entities(
        GoveeLight(coordinator, device.device_id, spec)
        for device in coordinator.devices.values()
        for spec in entities_for_platform(device.profile, PLATFORM_LIGHT)
    )


class GoveeLight(GoveeEntity, LightEntity):
    """A dimmable, colour-capable Govee light."""

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device_id: str,
        spec: EntitySpec,
    ) -> None:
        super().__init__(coordinator, device_id, spec.key)
        self._spec = spec
        profile = self.device.profile
        modes: set[ColorMode] = set()
        if profile.supports_color:
            modes.add(ColorMode.RGB)
        if profile.supports_color_temp:
            modes.add(ColorMode.COLOR_TEMP)
        if not modes and profile.supports_brightness:
            modes.add(ColorMode.BRIGHTNESS)
        self._attr_supported_color_modes = modes or {ColorMode.ONOFF}
        self._attr_min_color_temp_kelvin = profile.min_kelvin
        self._attr_max_color_temp_kelvin = profile.max_kelvin
        self._effects_loaded = False

    @property
    def is_on(self) -> bool:
        """Return whether the light is on."""
        return bool(self.device.state.power)

    @property
    def brightness(self) -> int | None:
        """Return the brightness on Home Assistant's 0-255 scale."""
        value = self.device.state.brightness
        return None if value is None else round(value * 255 / 100)

    @property
    def color_mode(self) -> ColorMode:
        """Return the colour mode the light is currently using."""
        if self.device.state.color is not None and self.device.profile.supports_color:
            return ColorMode.RGB
        if self.device.state.color_temp is not None and self.device.profile.supports_color_temp:
            return ColorMode.COLOR_TEMP
        if self.device.profile.supports_color:
            return ColorMode.RGB
        if self.device.profile.supports_color_temp:
            return ColorMode.COLOR_TEMP
        if self.device.profile.supports_brightness:
            return ColorMode.BRIGHTNESS
        return ColorMode.ONOFF

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the RGB colour."""
        return self.device.state.color

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the colour temperature."""
        return self.device.state.color_temp

    @property
    def effect_list(self) -> list[str] | None:
        """Return the names of the device's effects."""
        effects = self.coordinator.effects_library.effects(self.device)
        if not effects:
            return None
        return [effect.name for effect in effects]

    @property
    def effect(self) -> str | None:
        """Return the active effect."""
        return self.device.state.effect

    async def async_added_to_hass(self) -> None:
        """Load the effect library once the entity exists."""
        await super().async_added_to_hass()
        if self._effects_loaded or not self.device.profile.supports_color:
            return
        self._effects_loaded = True
        await self.coordinator.effects_library.async_load(self.device)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on and apply any requested attributes."""
        if not self.device.state.power:
            await self._async_send(self._control(LIGHT_OPERATION_POWER, True))

        if ATTR_BRIGHTNESS in kwargs:
            await self._async_send(
                self._control(LIGHT_OPERATION_BRIGHTNESS, kwargs[ATTR_BRIGHTNESS])
            )

        if ATTR_RGB_COLOR in kwargs:
            await self._async_send(self._control(LIGHT_OPERATION_COLOR, kwargs[ATTR_RGB_COLOR]))

        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            await self._async_send(
                self._control(LIGHT_OPERATION_COLOR_TEMP, kwargs[ATTR_COLOR_TEMP_KELVIN])
            )

        if ATTR_EFFECT in kwargs:
            await self._async_set_effect(str(kwargs[ATTR_EFFECT]))

    async def _async_set_effect(self, name: str) -> None:
        effect = next(
            (
                item
                for item in self.coordinator.effects_library.effects(self.device)
                if item.name == name
            ),
            None,
        )
        if effect is None:
            return
        await self._async_send(self._control(LIGHT_OPERATION_EFFECT, name, frames=effect.frames))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._async_send(self._control(LIGHT_OPERATION_POWER, False))

    def _control(self, operation: str, value: Any = None, **parameters: Any) -> ControlResult:
        if self._spec.control is None:
            raise ValueError("The light plan has no control")
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
