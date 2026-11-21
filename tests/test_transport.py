"""Tests for the transport seam and command router."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from custom_components.ultimate_govee.api.cloud import GoveeApiError
from custom_components.ultimate_govee.models import DeviceState, GoveeDevice
from custom_components.ultimate_govee.profiles import profile_for
from custom_components.ultimate_govee.protocol.commands import WireCommand
from custom_components.ultimate_govee.transport import (
    BleBroadcastTransport,
    BleGattTransport,
    CloudMqttTransport,
    CommandRouter,
    LanObservation,
    LanUdpTransport,
    LocalMqttTransport,
    StatusReport,
    TransportKind,
    TransportNotSent,
)


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


class FakeIot:
    connected = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict[str, Any] | None, int, int]] = []
        self.statuses: list[tuple[str, int]] = []

    def send_command(
        self,
        topic: str,
        command: str,
        data: dict[str, Any] | None = None,
        *,
        cmd_version: int = 0,
        msg_type: int = 1,
    ) -> None:
        self.sent.append((topic, command, data, cmd_version, msg_type))

    def request_status(self, topic: str, cmd_version: int = 2) -> None:
        self.statuses.append((topic, cmd_version))


class FakeLan:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict[str, Any]]] = []
        self.statuses: list[str] = []
        self.fail = False

    async def async_send_command(self, ip: str, command: str, data: dict[str, Any]) -> None:
        if self.fail:
            raise OSError("LAN send failed")
        self.sent.append((ip, command, data))

    async def async_request_status(self, ip: str) -> None:
        if self.fail:
            raise OSError("LAN status failed")
        self.statuses.append(ip)


def test_cloud_transport_sends_envelope_fields() -> None:
    iot = FakeIot()
    transport = CloudMqttTransport(lambda: iot, enabled=True)
    command = WireCommand("ptReal", {"command": ["frame"]}, cmd_version=2, msg_type=0)

    asyncio.run(transport.send(device(), command))

    assert iot.sent == [("topic/device-1", "ptReal", {"command": ["frame"]}, 2, 0)]


def test_lan_transport_failure_clears_endpoint() -> None:
    lan = FakeLan()
    lan.fail = True
    transport = LanUdpTransport(lambda: lan, enabled=True)
    target = device(lan_ip="192.168.1.20")
    command = WireCommand("turn", {"val": 1}, lan_cmd="turn", lan_data={"value": 1})

    with pytest.raises(TransportNotSent):
        asyncio.run(transport.send(target, command))

    assert target.lan_ip is None
    assert target.lan_last_seen == 0.0


def test_router_prefers_lan_and_falls_back_to_cloud() -> None:
    lan = FakeLan()
    lan.fail = True
    iot = FakeIot()
    router = CommandRouter(
        (
            LanUdpTransport(lambda: lan, enabled=True),
            CloudMqttTransport(lambda: iot, enabled=True),
        )
    )
    target = device(lan_ip="192.168.1.20")
    command = WireCommand("turn", {"val": 1}, lan_cmd="turn", lan_data={"value": 1})

    used = asyncio.run(router.send(target, command))

    assert used is TransportKind.CLOUD_MQTT
    assert iot.sent == [("topic/device-1", "turn", {"val": 1}, 0, 1)]


def test_router_skips_lan_without_a_lan_payload() -> None:
    lan = FakeLan()
    iot = FakeIot()
    router = CommandRouter(
        (
            LanUdpTransport(lambda: lan, enabled=True),
            CloudMqttTransport(lambda: iot, enabled=True),
        )
    )
    target = device(lan_ip="192.168.1.20")
    command = WireCommand("ptReal", {"command": ["frame"]})

    used = asyncio.run(router.send(target, command))

    assert used is TransportKind.CLOUD_MQTT
    assert lan.sent == []
    assert iot.sent == [("topic/device-1", "ptReal", {"command": ["frame"]}, 0, 1)]


def test_router_status_includes_unsupported_adapters() -> None:
    router = CommandRouter(
        (
            BleGattTransport(),
            BleBroadcastTransport(),
            LanUdpTransport(lambda: None, enabled=False),
            LocalMqttTransport(),
            CloudMqttTransport(lambda: None, enabled=False),
        )
    )

    status = router.status()

    assert set(status) == {
        "ble_gatt",
        "ble_broadcast",
        "lan_udp",
        "local_mqtt",
        "cloud_mqtt",
    }
    assert status["ble_gatt"]["supported"] is False
    assert status["local_mqtt"]["supported"] is False
    assert status["ble_broadcast"]["enabled"] is False


def test_router_request_status_prefers_lan() -> None:
    lan = FakeLan()
    iot = FakeIot()
    router = CommandRouter(
        (
            LanUdpTransport(lambda: lan, enabled=True),
            CloudMqttTransport(lambda: iot, enabled=True),
        )
    )
    target = device(lan_ip="192.168.1.20")

    used = asyncio.run(router.request_status(target))

    assert used is TransportKind.LAN_UDP
    assert lan.statuses == ["192.168.1.20"]
    assert iot.statuses == []


def test_router_request_status_falls_back_to_cloud() -> None:
    lan = FakeLan()
    lan.fail = True
    iot = FakeIot()
    router = CommandRouter(
        (
            LanUdpTransport(lambda: lan, enabled=True),
            CloudMqttTransport(lambda: iot, enabled=True),
        )
    )
    target = device(lan_ip="192.168.1.20")

    used = asyncio.run(router.request_status(target))

    assert used is TransportKind.CLOUD_MQTT
    assert iot.statuses == [("topic/device-1", 2)]


def test_cloud_status_skips_offline_device() -> None:
    iot = FakeIot()
    router = CommandRouter((CloudMqttTransport(lambda: iot, enabled=True),))
    target = device(state=DeviceState(online=False))

    with pytest.raises(GoveeApiError, match="No transport"):
        asyncio.run(router.request_status(target))

    assert iot.statuses == []


def test_lan_event_normalizes_reports_and_observations() -> None:
    transport = LanUdpTransport(FakeLan, enabled=True)

    report = transport.event("device-1", "devStatus", {"onOff": 1}, "192.168.1.20")
    observation = transport.event("device-1", "scan", {}, "192.168.1.21", seen_at=12.5)

    assert isinstance(report, StatusReport)
    assert report.device_id == "device-1"
    assert report.payload == {"onOff": 1}
    assert isinstance(observation, LanObservation)
    assert observation.ip == "192.168.1.21"
    assert observation.seen_at == 12.5


def test_lan_transport_logs_send_failure(caplog: Any) -> None:
    """A LAN send failure is visible in the log before falling back to cloud."""
    caplog.set_level(logging.DEBUG)
    lan = FakeLan()
    lan.fail = True
    transport = LanUdpTransport(lambda: lan, enabled=True)
    target = device(lan_ip="192.168.1.20")
    command = WireCommand("turn", {"val": 1}, lan_cmd="turn", lan_data={"value": 1})

    with pytest.raises(TransportNotSent):
        asyncio.run(transport.send(target, command))

    assert "LAN command failed" in caplog.text
    assert "192.168.1.20" in caplog.text
