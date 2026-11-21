"""Control parity between the entity platforms and the entity plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
)

from custom_components.ultimate_govee.entity_plan import entities_for_platform
from custom_components.ultimate_govee.humidifier import GoveeHumidifier
from custom_components.ultimate_govee.light import GoveeLight
from custom_components.ultimate_govee.models import DeviceState, GoveeDevice
from custom_components.ultimate_govee.profiles import profile_for
from custom_components.ultimate_govee.protocol import commands


@dataclass(frozen=True)
class _Effect:
    name: str
    frames: tuple[tuple[int, ...], ...]


class _Effects:
    def __init__(self, effects: tuple[_Effect, ...] = ()) -> None:
        self._effects = effects

    def effects(self, device: GoveeDevice) -> tuple[_Effect, ...]:
        return self._effects


class _Coordinator:
    last_update_success = True

    def __init__(
        self,
        device: GoveeDevice,
        effects: tuple[_Effect, ...] = (),
    ) -> None:
        self.devices = {device.device_id: device}
        self.effects_library = _Effects(effects)
        self.sent: list[tuple[Any, dict[str, Any] | None]] = []

    async def async_send(
        self,
        device: GoveeDevice,
        command: Any,
        *,
        optimistic: dict[str, Any] | None = None,
    ) -> None:
        self.sent.append((command, optimistic))


def _device(device_id: str, sku: str, state: DeviceState) -> GoveeDevice:
    return GoveeDevice(
        device_id=device_id,
        sku=sku,
        name=f"Test {sku}",
        iot_topic=f"topic/{device_id}",
        firmware="1.0.0",
        hardware="1.0.0",
        settings={},
        profile=profile_for(sku),
        state=state,
    )


async def test_light_turn_on_sends_each_attribute_as_one_plan_result() -> None:
    device = _device("light-1", "H6001", DeviceState(power=False))
    coordinator = _Coordinator(device, effects=(_Effect("Sunrise", ((0xAA, 1),)),))
    spec = entities_for_platform(device.profile, "light")[0]
    light = GoveeLight(coordinator, device.device_id, spec)  # type: ignore[arg-type]

    await light.async_turn_on(
        **{
            ATTR_BRIGHTNESS: 128,
            ATTR_RGB_COLOR: (10, 20, 30),
            ATTR_COLOR_TEMP_KELVIN: 4000,
            ATTR_EFFECT: "Sunrise",
        }
    )

    profile = device.profile
    assert [command for command, _ in coordinator.sent] == [
        commands.power(profile, True),
        commands.brightness(profile, 50),
        commands.color(10, 20, 30),
        commands.color_temp(4000),
        commands.effect([(0xAA, 1)]),
    ]
    assert [optimistic for _, optimistic in coordinator.sent] == [
        {"power": True},
        {"brightness": 50},
        {"color": (10, 20, 30), "color_temp": None},
        {"color_temp": 4000},
        {"effect": "Sunrise", "power": True},
    ]


async def test_light_turn_on_already_on_skips_the_power_command() -> None:
    device = _device("light-1", "H6001", DeviceState(power=True, brightness=50))
    coordinator = _Coordinator(device)
    spec = entities_for_platform(device.profile, "light")[0]
    light = GoveeLight(coordinator, device.device_id, spec)  # type: ignore[arg-type]

    await light.async_turn_on(**{ATTR_BRIGHTNESS: 255})

    assert [command for command, _ in coordinator.sent] == [
        commands.brightness(device.profile, 100)
    ]


async def test_light_turn_off_and_unknown_effect_keep_existing_behaviour() -> None:
    device = _device("light-1", "H6001", DeviceState(power=True))
    coordinator = _Coordinator(device)
    spec = entities_for_platform(device.profile, "light")[0]
    light = GoveeLight(coordinator, device.device_id, spec)  # type: ignore[arg-type]

    await light.async_turn_on(**{ATTR_EFFECT: "Missing"})
    assert coordinator.sent == []

    await light.async_turn_off()
    assert coordinator.sent == [(commands.power(device.profile, False), {"power": False})]


async def test_humidifier_controls_come_from_the_plan() -> None:
    device = _device(
        "humidifier-1",
        "H7142",
        DeviceState(power=True, target_humidity=55, fan_speed=7),
    )
    coordinator = _Coordinator(device)
    spec = entities_for_platform(device.profile, "humidifier")[0]
    humidifier = GoveeHumidifier(coordinator, device.device_id, spec)  # type: ignore[arg-type]

    await humidifier.async_set_humidity(65)
    await humidifier.async_set_mode("auto")
    await humidifier.async_set_mode("manual")
    await humidifier.async_set_mode("program")
    await humidifier.async_turn_off()

    profile = device.profile
    assert [command for command, _ in coordinator.sent] == [
        commands.humidifier_target(profile, 65),
        commands.humidifier_target(profile, 55),
        commands.mist_level(profile, 7),
        commands.humidifier_mode(profile, "program"),
        commands.power(profile, False),
    ]
    assert [optimistic for _, optimistic in coordinator.sent] == [
        {"target_humidity": 65, "mode": "auto"},
        {"mode": "auto", "power": True},
        {"mode": "manual", "power": True},
        {"mode": "program"},
        {"power": False},
    ]


async def test_humidifier_rejects_unsupported_modes_without_sending() -> None:
    device = _device("humidifier-1", "H7142", DeviceState(power=True))
    coordinator = _Coordinator(device)
    spec = entities_for_platform(device.profile, "humidifier")[0]
    humidifier = GoveeHumidifier(coordinator, device.device_id, spec)  # type: ignore[arg-type]

    await humidifier.async_set_mode("unknown")

    assert coordinator.sent == []
