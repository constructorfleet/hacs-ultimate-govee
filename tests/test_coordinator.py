"""Coordinator filtering tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ultimate_govee.api.cloud import GoveeApiError
from custom_components.ultimate_govee.const import DOMAIN
from custom_components.ultimate_govee.coordinator import GoveeCoordinator
from custom_components.ultimate_govee.fleet import Fleet
from custom_components.ultimate_govee.models import DeviceState, GoveeDevice
from custom_components.ultimate_govee.profiles import profile_for
from custom_components.ultimate_govee.protocol.codec import build_frame, bytes_to_base64
from custom_components.ultimate_govee.tap_to_runs import TapAction, TapToRun
from custom_components.ultimate_govee.transport import StatusReport, TransportKind


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
    coordinator.fleet = Fleet(
        [
            GoveeDevice(
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
        ]
    )
    iot = Mock(connected=True)
    cloud = coordinator.router.get(TransportKind.CLOUD_MQTT)
    assert cloud is not None
    cloud._iot = iot  # type: ignore[attr-defined]
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


def _coordinator_with_device(hass: Any, tmp_path: Path) -> tuple[GoveeCoordinator, GoveeDevice]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "user@example.com", "password": "secret"},
        options={"enable_lan": False, "enable_iot": False},
    )
    entry.add_to_hass(hass)
    coordinator = GoveeCoordinator(hass, entry, async_get_clientsession(hass), tmp_path)
    device = GoveeDevice(
        device_id="device-1",
        sku="H6001",
        name="Lamp",
        iot_topic="topic/device-1",
        firmware=None,
        hardware=None,
        settings={},
        profile=profile_for("H6001"),
    )
    coordinator.fleet = Fleet([device])
    return coordinator, device


async def test_apply_state_accepts_mapping_and_device_state(hass: Any, tmp_path: Path) -> None:
    """Optimistic call sites can keep using mappings at the coordinator boundary."""
    coordinator, device = _coordinator_with_device(hass, tmp_path)

    coordinator._apply_state(device, {"power": True})
    assert device.state.power is True
    assert device.state.online is None

    coordinator._apply_state(device, DeviceState(brightness=25))
    assert device.state.brightness == 25
    assert device.state.power is True


async def test_inbound_status_marks_device_online(hass: Any, tmp_path: Path) -> None:
    """A live status report proves the device is reachable."""
    coordinator, device = _coordinator_with_device(hass, tmp_path)

    cloud = coordinator.router.get(TransportKind.CLOUD_MQTT)
    assert cloud is not None
    cloud._handle_message({"device": "device-1", "state": {"onOff": 1}})  # type: ignore[attr-defined]

    assert device.state.power is True
    assert device.state.online is True


async def test_lan_devstatus_records_endpoint(hass: Any, tmp_path: Path) -> None:
    """A status report also proves the device is reachable over LAN."""
    coordinator, device = _coordinator_with_device(hass, tmp_path)

    lan = coordinator.router.get(TransportKind.LAN_UDP)
    assert lan is not None
    lan._handle_message(  # type: ignore[attr-defined]
        "device-1", "devStatus", {"state": {"onOff": 1}}, "192.168.1.20"
    )

    assert device.lan_ip == "192.168.1.20"
    assert device.lan_last_seen > 0
    assert device.state.power is True
    assert device.state.online is True


async def test_tap_to_run_reports_delivery_failure(hass: Any, tmp_path: Path) -> None:
    """A matched tap-to-run that cannot be delivered is not reported as unmatched."""
    coordinator, _ = _coordinator_with_device(hass, tmp_path)
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

    with pytest.raises(GoveeApiError, match="No transport delivered the Party tap-to-run"):
        await coordinator.async_run_tap_to_run(tap)


async def test_coordinator_lifecycle_delegates_to_the_router(hass: Any, tmp_path: Path) -> None:
    """The coordinator starts and stops the router, never concrete adapters."""
    coordinator, _ = _coordinator_with_device(hass, tmp_path)
    coordinator.auth.ensure_valid = AsyncMock()  # type: ignore[method-assign]
    calls: list[str] = []

    class RouterStub:
        async def async_start(self) -> None:
            calls.append("start")

        async def async_stop(self) -> None:
            calls.append("stop")

    coordinator.router = RouterStub()  # type: ignore[assignment]

    await coordinator.async_setup()
    await coordinator.async_shutdown()

    assert calls == ["start", "stop"]


async def test_fleet_changes_notify_coordinator_listeners(hass: Any, tmp_path: Path) -> None:
    """A fleet observation is the single path to entity listeners."""
    coordinator, device = _coordinator_with_device(hass, tmp_path)
    calls: list[int] = []
    coordinator.async_update_listeners = Mock(  # type: ignore[method-assign]
        side_effect=lambda: calls.append(1)
    )

    assert coordinator.fleet.observe_lan("device-1", "192.168.1.20", 5.0)
    assert coordinator.fleet.observe_lan("device-1", "192.168.1.20", 5.0) is False

    assert calls == [1]
    assert device.lan_ip == "192.168.1.20"


async def test_ble_status_report_is_applied_by_the_coordinator(hass: Any, tmp_path: Path) -> None:
    """A BLE notification crosses the same typed event seam as cloud and LAN."""
    coordinator, device = _coordinator_with_device(hass, tmp_path)
    frame = build_frame(0x01, [1], opcode=0xAA)

    coordinator._handle_inbound(
        StatusReport("device-1", {"op": {"command": [bytes_to_base64(frame)]}})
    )

    assert device.state.power is True
    assert device.state.online is True


async def test_refresh_publishes_one_listener_notification(hass: Any, tmp_path: Path) -> None:
    """A refresh does not notify once per Fleet step and once for its result."""
    coordinator, _ = _coordinator_with_device(hass, tmp_path)
    coordinator.auth.ensure_valid = AsyncMock()  # type: ignore[method-assign]
    coordinator.cloud.get_devices = AsyncMock(  # type: ignore[method-assign]
        return_value=[_raw("device-1", "One"), _raw("device-2", "Two")]
    )
    coordinator.async_update_listeners = Mock()  # type: ignore[method-assign]

    await coordinator._async_update_data()

    coordinator.async_update_listeners.assert_not_called()
    assert set(coordinator.devices) == {"device-1", "device-2"}
