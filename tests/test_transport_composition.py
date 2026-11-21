"""Tests for router-owned transport construction and scan cadence."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.ultimate_govee.api.cloud import GoveeApiError
from custom_components.ultimate_govee.const import (
    CONF_ENABLE_IOT,
    CONF_ENABLE_LAN,
    CONF_LAN_SCAN_INTERVAL,
)
from custom_components.ultimate_govee.models import DeviceState, GoveeDevice
from custom_components.ultimate_govee.options import GoveeOptions
from custom_components.ultimate_govee.profiles import profile_for
from custom_components.ultimate_govee.protocol.command import Command, power_command
from custom_components.ultimate_govee.transport import (
    CommandRouter,
    LanUdpTransport,
    NoTransportAvailable,
    Transport,
    TransportContext,
    TransportKind,
    TransportNotSent,
    TransportStatus,
)


class FakeLan:
    def __init__(self) -> None:
        self.scans = 0

    async def async_scan(self) -> None:
        self.scans += 1

    async def async_send_command(self, ip: str, command: str, data: dict[str, Any]) -> None:
        return

    async def async_request_status(self, ip: str) -> None:
        return

    async def async_stop(self) -> None:
        return


class ScanTransport(Transport):
    kind = TransportKind.LOCAL_MQTT

    def __init__(self, kind: TransportKind, interval: float) -> None:
        self.kind = kind
        self.scan_interval = interval
        self.scans = 0

    @property
    def supported(self) -> bool:
        return True

    @property
    def connected(self) -> bool:
        return True

    def supports(self, device: GoveeDevice) -> bool:
        return True

    async def send(self, device: GoveeDevice, command: Command) -> None:
        return

    async def request_status(self, device: GoveeDevice) -> None:
        return

    async def async_scan(self) -> None:
        self.scans += 1

    def status(self) -> TransportStatus:
        return TransportStatus(self.kind, True, True, True, True)


def context(hass: Any) -> TransportContext:
    return TransportContext(hass=hass, account_topic="account/topic")


def device(**overrides: Any) -> GoveeDevice:
    values: dict[str, Any] = {
        "device_id": "device-1",
        "sku": "H6001",
        "name": "Lamp",
        "iot_topic": "topic/device-1",
        "firmware": None,
        "hardware": None,
        "settings": {},
        "profile": profile_for("H6001"),
        "state": DeviceState(online=True),
    }
    values.update(overrides)
    return GoveeDevice(**values)


async def test_router_builds_every_known_transport_from_options() -> None:
    hass = SimpleNamespace(
        loop=asyncio.get_running_loop(),
        config=SimpleNamespace(components={"bluetooth"}),
    )
    options = GoveeOptions.from_mapping({CONF_LAN_SCAN_INTERVAL: 45})

    router = CommandRouter.from_options(options, context(hass))

    assert set(router.status()) == {
        "ble_gatt",
        "ble_broadcast",
        "lan_udp",
        "local_mqtt",
        "cloud_mqtt",
    }
    lan = router.get(TransportKind.LAN_UDP)
    assert isinstance(lan, LanUdpTransport)
    assert lan.scan_interval == 45
    assert router.get(TransportKind.BLE_GATT).supported is True  # type: ignore[union-attr]


async def test_options_flow_into_adapter_enablement() -> None:
    hass = SimpleNamespace(
        loop=asyncio.get_running_loop(),
        config=SimpleNamespace(components=set()),
    )
    options = GoveeOptions.from_mapping({CONF_ENABLE_LAN: False, CONF_ENABLE_IOT: False})

    router = CommandRouter.from_options(options, context(hass))
    status = router.status()

    assert status["ble_gatt"].supported is False
    assert status["lan_udp"].enabled is False
    assert status["cloud_mqtt"].enabled is False


async def test_a_new_transport_is_one_builder_not_a_caller_edit() -> None:
    hass = SimpleNamespace(loop=asyncio.get_running_loop(), config=SimpleNamespace(components=()))
    only = ScanTransport(TransportKind.BLE_GATT, 0)

    router = CommandRouter.from_options(
        GoveeOptions.from_mapping({}),
        context(hass),
        builders=(lambda _context, _options: only,),
    )

    assert set(router.status()) == {"ble_gatt"}


async def test_router_owns_scan_cadence_per_adapter() -> None:
    every = ScanTransport(TransportKind.LAN_UDP, 0)
    slow = ScanTransport(TransportKind.LOCAL_MQTT, 30)
    router = CommandRouter((every, slow))

    await router.async_scan(now=100.0)
    await router.async_scan(now=110.0)
    await router.async_scan(now=130.0)

    assert every.scans == 3
    assert slow.scans == 2


async def test_router_applies_the_configured_lan_interval() -> None:
    hass = SimpleNamespace(loop=asyncio.get_running_loop(), config=SimpleNamespace(components=()))
    options = GoveeOptions.from_mapping({CONF_LAN_SCAN_INTERVAL: 30})
    router = CommandRouter.from_options(options, context(hass))
    lan = router.get(TransportKind.LAN_UDP)
    assert isinstance(lan, LanUdpTransport)
    client = FakeLan()
    lan._lan = client  # type: ignore[assignment]

    await router.async_scan(now=100.0)
    await router.async_scan(now=110.0)
    await router.async_scan(now=130.0)

    assert client.scans == 2


async def test_status_records_share_one_shape_for_every_adapter() -> None:
    hass = SimpleNamespace(loop=asyncio.get_running_loop(), config=SimpleNamespace(components=()))
    router = CommandRouter.from_options(GoveeOptions.from_mapping({}), context(hass))

    for record in router.status().values():
        assert isinstance(record, TransportStatus)
        assert record.as_dict().keys() == {
            "kind",
            "supported",
            "enabled",
            "started",
            "connected",
            "links",
        }
        assert record["kind"] == record.kind.value


def test_status_record_keeps_the_old_mapping_view() -> None:
    record = TransportStatus(TransportKind.LAN_UDP, True, True, True, True)

    assert record["connected"] is True
    assert dict(record)["kind"] == "lan_udp"


async def test_no_path_is_a_transport_failure_not_only_a_cloud_error() -> None:
    router = CommandRouter(())
    target = device()

    with pytest.raises(NoTransportAvailable) as raised:
        await router.send(target, power_command(on=True))

    assert isinstance(raised.value, (GoveeApiError, TransportNotSent))
