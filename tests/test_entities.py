"""Smoke tests that every platform can create entities for real profiles."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ultimate_govee.const import DOMAIN
from custom_components.ultimate_govee.coordinator import GoveeCoordinator
from custom_components.ultimate_govee.models import DeviceState, GoveeDevice
from custom_components.ultimate_govee.profiles import profile_for


def _device(
    device_id: str,
    sku: str,
    *,
    online: bool = True,
    state: DeviceState | None = None,
) -> GoveeDevice:
    return GoveeDevice(
        device_id=device_id,
        sku=sku,
        name=f"Test {sku}",
        iot_topic=f"topic/{device_id}",
        firmware="1.0.0",
        hardware="1.0.0",
        settings={},
        profile=profile_for(sku),
        state=state or DeviceState(online=online),
    )


@pytest.fixture
def devices() -> dict[str, GoveeDevice]:
    """Return a fleet covering every entity platform."""
    return {
        "light-1": _device(
            "light-1",
            "H6001",
            state=DeviceState(
                online=True,
                power=True,
                brightness=50,
                color=(255, 0, 0),
                color_temp=4000,
            ),
        ),
        "switch-1": _device(
            "switch-1",
            "H5080",
            state=DeviceState(online=True, power=True),
        ),
        "double-1": _device(
            "double-1",
            "H5082",
            state=DeviceState(online=True, power=True, gangs=(True, False)),
        ),
        "fan-1": _device(
            "fan-1",
            "H7100",
            state=DeviceState(online=True, power=True, fan_speed=3, oscillation=False),
        ),
        "ceiling-1": _device(
            "ceiling-1",
            "H1310",
            state=DeviceState(online=True, power=True, fan_speed=2),
        ),
        "purifier-1": _device(
            "purifier-1",
            "H7120",
            state=DeviceState(online=True, power=True, fan_speed=2, percentage=50),
        ),
        "humidifier-1": _device(
            "humidifier-1",
            "H7142",
            state=DeviceState(
                online=True,
                power=True,
                target_humidity=50,
                humidity=45,
                mode="auto",
            ),
        ),
        "heater-1": _device(
            "heater-1",
            "H7130",
            state=DeviceState(online=True, power=True, fan_speed=2),
        ),
        "heater-2": _device(
            "heater-2",
            "H7131",
            state=DeviceState(online=True, power=True, fan_speed=2),
        ),
        "ice-1": _device(
            "ice-1",
            "H7172",
            state=DeviceState(online=True, power=True, basket_full=False),
        ),
        "thermo-1": _device(
            "thermo-1",
            "H5051",
            state=DeviceState(
                online=True,
                temperature=21.5,
                humidity=45,
                battery=90,
            ),
        ),
        "monitor-1": _device(
            "monitor-1",
            "H5106",
            state=DeviceState(online=True, temperature=22.0, humidity=40, pm25=8),
        ),
        "leak-1": _device(
            "leak-1",
            "H5054",
            state=DeviceState(online=True, leak=False, battery=80),
        ),
    }


async def test_all_platforms_create_entities(
    hass: Any,
    monkeypatch: pytest.MonkeyPatch,
    devices: dict[str, GoveeDevice],
) -> None:
    """Set up the integration and check that every platform added entities."""

    async def _setup(self: GoveeCoordinator) -> None:
        self.devices = devices

    async def _refresh(self: GoveeCoordinator) -> None:
        self.devices = devices
        self.data = devices

    async def _effects(self: GoveeCoordinator, device: GoveeDevice) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(GoveeCoordinator, "async_setup", _setup)
    monkeypatch.setattr(GoveeCoordinator, "async_config_entry_first_refresh", _refresh)
    monkeypatch.setattr(GoveeCoordinator, "async_get_effects", _effects)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="account-1",
        data={"email": "user@example.com", "password": "secret"},
        options={"enable_lan": False, "enable_iot": False},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for platform in (
        "binary_sensor",
        "fan",
        "humidifier",
        "light",
        "number",
        "select",
        "sensor",
        "switch",
    ):
        assert hass.states.async_entity_ids(platform), f"no {platform} entities"

    assert hass.states.get("light.test_h6001")
    assert hass.states.get("switch.test_h5080")
    assert hass.states.get("fan.test_h7100")
    assert hass.states.get("humidifier.test_h7142")
    assert hass.states.get("number.test_h7130_target_temperature")
