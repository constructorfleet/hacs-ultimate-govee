"""Coordinator filtering tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ultimate_govee.const import DOMAIN
from custom_components.ultimate_govee.coordinator import GoveeCoordinator
from custom_components.ultimate_govee.models import DeviceState, GoveeDevice
from custom_components.ultimate_govee.profiles import profile_for
from custom_components.ultimate_govee.tap_to_runs import TapAction, TapToRun


def _raw(device_id: str, name: str) -> dict[str, Any]:
    return {
        "device": device_id,
        "sku": "H6001",
        "deviceName": name,
        "deviceExt": {"deviceSettings": {}, "lastDeviceData": {}},
    }


async def test_ignored_devices_are_not_loaded(hass: Any, tmp_path: Path) -> None:
    """Devices selected in the options flow are excluded from the fleet."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "user@example.com", "password": "secret"},
        options={"ignored_devices": ["device-2"], "enable_lan": False, "enable_iot": False},
    )
    entry.add_to_hass(hass)

    coordinator = GoveeCoordinator(
        hass,
        entry,
        async_get_clientsession(hass),
        tmp_path,
    )
    coordinator.auth.ensure_valid = AsyncMock()  # type: ignore[method-assign]
    coordinator.cloud.get_devices = AsyncMock(  # type: ignore[method-assign]
        return_value=[_raw("device-1", "One"), _raw("device-2", "Two")]
    )

    devices = await coordinator._async_update_data()

    assert set(devices) == {"device-1"}


async def test_tap_to_run_publishes_to_device(hass: Any, tmp_path: Path) -> None:
    """A tap-to-run action is published to the matching device's IoT topic."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "user@example.com", "password": "secret"},
        options={"enable_lan": False, "enable_iot": True},
    )
    entry.add_to_hass(hass)
    coordinator = GoveeCoordinator(hass, entry, async_get_clientsession(hass), tmp_path)
    coordinator.devices = {
        "device-1": GoveeDevice(
            device_id="device-1",
            sku="H6001",
            name="Lamp",
            iot_topic="topic/device-1",
            firmware=None,
            hardware=None,
            settings={},
            profile=profile_for("H6001"),
            state=DeviceState(online=True),
        )
    }
    iot = Mock(connected=True)
    coordinator._iot = iot
    coordinator._iot_started = True
    tap = TapToRun(
        name="Party",
        key="party",
        actions=(
            TapAction(
                device_name="Lamp",
                sku="H6001",
                command="ptReal",
                data={"command": ["MwUBAQAAAAAAAAAAAAAAAAAAADY="]},
                device_id="device-1",
            ),
        ),
    )

    await coordinator.async_run_tap_to_run(tap)

    iot.send_command.assert_called_once_with(
        "topic/device-1",
        "ptReal",
        {"command": ["MwUBAQAAAAAAAAAAAAAAAAAAADY="]},
        cmd_version=0,
        msg_type=1,
    )
