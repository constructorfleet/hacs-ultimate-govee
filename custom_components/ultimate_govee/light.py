"""Light entities for Govee LED products."""

from __future__ import annotations

import logging
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

from .api.cloud import GoveeApiError
from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .profiles import KIND_LIGHT
from .protocol import commands

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up light entities."""
    coordinator: GoveeCoordinator = entry.runtime_data
    async_add_entities(
        GoveeLight(coordinator, device.device_id)
        for device in coordinator.devices.values()
        if device.profile.kind == KIND_LIGHT
    )


class GoveeLight(GoveeEntity, LightEntity):
    """A dimmable, colour-capable Govee light."""

    def __init__(self, coordinator: GoveeCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "light")
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
        effects = self.coordinator.effects.get(self.device.sku)
        if not effects:
            return None
        return [str(effect.get("name")) for effect in effects if effect.get("name")]

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
        try:
            await self.coordinator.async_get_effects(self.device)
        except (GoveeApiError, OSError) as err:
            _LOGGER.debug("Unable to load effects for %s: %s", self.device.name, err)
            return
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on and apply any requested attributes."""
        if not self.device.state.power:
            await self._send(commands.power(self.device.profile, True), {"power": True})

        if ATTR_BRIGHTNESS in kwargs:
            brightness = round(int(kwargs[ATTR_BRIGHTNESS]) * 100 / 255)
            await self._send(
                commands.brightness(self.device.profile, brightness),
                {"brightness": brightness},
            )

        if ATTR_RGB_COLOR in kwargs:
            red, green, blue = kwargs[ATTR_RGB_COLOR]
            await self._send(
                commands.color(red, green, blue),
                {"color": (red, green, blue), "color_temp": None},
            )

        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            kelvin = int(kwargs[ATTR_COLOR_TEMP_KELVIN])
            await self._send(commands.color_temp(kelvin), {"color_temp": kelvin})

        if ATTR_EFFECT in kwargs:
            await self._async_set_effect(str(kwargs[ATTR_EFFECT]))

    async def _async_set_effect(self, name: str) -> None:
        effects = self.coordinator.effects.get(self.device.sku, [])
        effect = next((item for item in effects if str(item.get("name")) == name), None)
        if effect is None:
            return
        frames = effect.get("opCode") or effect.get("code")
        if isinstance(frames, str):
            frames = [frames]
        if not isinstance(frames, list):
            return
        await self._send(commands.effect(frames), {"effect": name, "power": True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._send(commands.power(self.device.profile, False), {"power": False})
