"""Switch entities for Govee plugs, appliances and accessory functions."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .profiles import (
    FEATURE_DISPLAY,
    FEATURE_LOCK,
    FEATURE_NIGHT_LIGHT,
    FEATURE_OSCILLATION,
    FEATURE_UV,
    KIND_CEILING_FAN,
    KIND_COMPOSTER,
    KIND_DIFFUSER,
    KIND_FAN,
    KIND_HEATER,
    KIND_HUMIDIFIER,
    KIND_ICE_MAKER,
    KIND_KETTLE,
    KIND_PURIFIER,
    KIND_SWITCH,
    KIND_TV,
)
from .protocol import commands

POWER_KINDS = {
    KIND_COMPOSTER,
    KIND_DIFFUSER,
    KIND_HEATER,
    KIND_ICE_MAKER,
    KIND_KETTLE,
    KIND_SWITCH,
    KIND_TV,
}
CONTROL_KINDS = {
    KIND_CEILING_FAN,
    KIND_COMPOSTER,
    KIND_DIFFUSER,
    KIND_FAN,
    KIND_HEATER,
    KIND_HUMIDIFIER,
    KIND_ICE_MAKER,
    KIND_KETTLE,
    KIND_PURIFIER,
    KIND_TV,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches for every controllable Govee device."""
    coordinator: GoveeCoordinator = entry.runtime_data
    entities: list[GoveeSwitch] = []
    for device in coordinator.devices.values():
        profile = device.profile
        if profile.kind not in POWER_KINDS and profile.kind not in CONTROL_KINDS:
            continue
        if profile.kind == KIND_SWITCH and profile.gang_count > 1:
            entities.extend(
                GoveeSwitch(coordinator, device.device_id, f"gang{index}", name)
                for index, name in enumerate(
                    f"Gang {number}" for number in range(1, profile.gang_count + 1)
                )
            )
        elif profile.kind in POWER_KINDS:
            entities.append(GoveeSwitch(coordinator, device.device_id, "power"))

        if profile.kind not in CONTROL_KINDS:
            continue
        for feature, name in (
            (FEATURE_NIGHT_LIGHT, "Night light"),
            (FEATURE_DISPLAY, "Display"),
            (FEATURE_LOCK, "Child lock"),
            (FEATURE_UV, "UV sterilisation"),
            (FEATURE_OSCILLATION, "Oscillation"),
        ):
            if feature in profile.features:
                entities.append(GoveeSwitch(coordinator, device.device_id, feature, name))

    async_add_entities(entities)


class GoveeSwitch(GoveeEntity, SwitchEntity):
    """A power switch, per-gang switch or accessory toggle."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device_id: str,
        key: str,
        name: str | None = None,
    ) -> None:
        super().__init__(coordinator, device_id, key)
        self._key = key
        self._attr_name = name
        if key in {FEATURE_DISPLAY, FEATURE_LOCK, FEATURE_UV}:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool:
        """Return the switch state."""
        state = self.device.state
        if self._key == "power":
            return bool(state.power)
        if self._key.startswith("gang"):
            index = int(self._key.removeprefix("gang"))
            return bool(state.gangs and index < len(state.gangs) and state.gangs[index])
        return bool(getattr(state, self._key, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch or function on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch or function off."""
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        profile = self.device.profile
        state = self.device.state
        if self._key == "power":
            if profile.kind == KIND_ICE_MAKER:
                command = commands.ice_power(profile, on)
            elif profile.kind == KIND_HEATER:
                command = commands.heater_power(profile, on)
            else:
                command = commands.power(profile, on)
            await self._send(command, {"power": on})
            return
        if self._key.startswith("gang"):
            index = int(self._key.removeprefix("gang"))
            await self._send(
                commands.gang_power(profile, index, on),
                _gang_state(state.gangs, index, on),
            )
            return
        if self._key == FEATURE_NIGHT_LIGHT:
            await self._send(
                commands.night_light(
                    profile,
                    on,
                    state.night_light_brightness or 100,
                    state.color or (255, 255, 255),
                ),
                {"night_light": on},
            )
            return
        if self._key == FEATURE_DISPLAY:
            await self._send(commands.display(profile, on), {"display": on})
            return
        if self._key == FEATURE_LOCK:
            await self._send(commands.lock(profile, on), {"lock": on})
            return
        if self._key == FEATURE_UV:
            await self._send(commands.uv(on), {"uv": on})
            return
        if self._key == FEATURE_OSCILLATION:
            await self._send(commands.oscillation(profile, on), {"oscillation": on})


def _gang_state(
    gangs: tuple[bool, ...] | None, index: int, on: bool
) -> dict[str, tuple[bool, ...]]:
    values = list(gangs or ())
    while len(values) <= index:
        values.append(False)
    values[index] = on
    return {"gangs": tuple(values), "power": any(values)}
