"""Tests for the BLE GATT transport and connection manager.

Everything here uses fakes; no Bluetooth adapter or Home Assistant Bluetooth
component is required.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

import custom_components.ultimate_govee.api.ble as ble_api
from custom_components.ultimate_govee.api.cloud import GoveeApiError
from custom_components.ultimate_govee.models import DeviceState, GoveeDevice
from custom_components.ultimate_govee.profiles import profile_for
from custom_components.ultimate_govee.protocol.codec import build_frame, bytes_to_base64
from custom_components.ultimate_govee.protocol.command import (
    Command,
    brightness_command,
    color_command,
    frames_command,
    power_command,
)
from custom_components.ultimate_govee.protocol.state import decode_message
from custom_components.ultimate_govee.transport import (
    BleBroadcastTransport,
    BleGattTransport,
    CloudMqttTransport,
    CommandRouter,
    TransportKind,
    TransportNotSent,
    TransportUnavailable,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"


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
        "ble_address": ADDRESS,
    }
    values.update(overrides)
    return GoveeDevice(**values)


def xor(frame: bytes) -> int:
    value = 0
    for byte in frame:
        value ^= byte
    return value


class FakeManager:
    """A stand-in for :class:`GoveeBle` with the transport-facing surface."""

    def __init__(
        self,
        address: str,
        name: str,
        callback: Any,
        *,
        fail: bool = False,
    ) -> None:
        self.address = address
        self.name = name
        self.callback = callback
        self.fail = fail
        self.frames: list[list[bytes]] = []
        self.status_requests = 0
        self.stopped = False
        self.connected = False

    async def async_send_frames(self, frames: list[bytes]) -> None:
        if self.fail:
            raise ble_api.GoveeBleError("write failed")
        self.frames.append(list(frames))
        self.connected = True

    async def async_request_status(self) -> None:
        if self.fail:
            raise ble_api.GoveeBleError("status failed")
        self.status_requests += 1
        self.connected = True

    async def async_stop(self) -> None:
        self.stopped = True
        self.connected = False


def manager_factory(managers: list[FakeManager], *, fail: bool = False) -> Any:
    def create(_hass: Any, address: str, name: str, callback: Any) -> FakeManager:
        manager = FakeManager(address, name, callback, fail=fail)
        managers.append(manager)
        return manager

    return create


class FakeIot:
    connected = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict[str, Any] | None, int, int]] = []

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


async def test_turn_frame_has_documented_opcode_and_bcc() -> None:
    managers: list[FakeManager] = []
    transport = BleGattTransport(available=True, manager_factory=manager_factory(managers))

    await transport.send(device(), power_command(on=True))

    frame = managers[0].frames[0][0]
    assert frame[:3] == bytes([0x33, 0x01, 0x01])
    assert len(frame) == 20
    assert xor(frame[:19]) == frame[19]


async def test_brightness_frame_uses_register_04() -> None:
    managers: list[FakeManager] = []
    transport = BleGattTransport(available=True, manager_factory=manager_factory(managers))

    await transport.send(device(), brightness_command(50))

    frame = managers[0].frames[0][0]
    assert frame[:3] == bytes([0x33, 0x04, 0x32])
    assert xor(frame[:19]) == frame[19]


async def test_legacy_254_brightness_scales_to_20_254() -> None:
    managers: list[FakeManager] = []
    transport = BleGattTransport(available=True, manager_factory=manager_factory(managers))
    target = device(sku="H6002", profile=profile_for("H6002"))

    await transport.send(target, brightness_command(50))

    frame = managers[0].frames[0][0]
    assert frame[:3] == bytes([0x33, 0x04, 0x89])
    assert xor(frame[:19]) == frame[19]


async def test_turn_normalizes_profile_power_values() -> None:
    managers: list[FakeManager] = []
    transport = BleGattTransport(available=True, manager_factory=manager_factory(managers))
    target = device(sku="H5080", profile=profile_for("H5080"))

    await transport.send(target, power_command(on=True))

    frame = managers[0].frames[0][0]
    assert frame[:3] == bytes([0x33, 0x01, 0x01])
    assert xor(frame[:19]) == frame[19]


@pytest.mark.parametrize("command_name", ["ptReal", "multiSync"])
async def test_pt_real_and_multi_sync_send_decoded_frames(command_name: str) -> None:
    managers: list[FakeManager] = []
    transport = BleGattTransport(available=True, manager_factory=manager_factory(managers))
    first = build_frame(0x05, [0x0A, 0x01])
    second = build_frame(0x04, [0x80])

    await transport.send(
        device(),
        frames_command([first, second], strategy=command_name),
    )

    assert managers[0].frames == [[first, second]]


async def test_pt_real_rejects_a_bad_frame_instead_of_sending_it() -> None:
    managers: list[FakeManager] = []
    transport = BleGattTransport(available=True, manager_factory=manager_factory(managers))
    frame = bytearray(build_frame(0x01, [1]))
    frame[-1] ^= 0xFF

    with pytest.raises(TransportUnavailable, match="not a valid 20-byte BLE frame"):
        await transport.send(device(), frames_command(bytes(frame), strategy="ptReal"))

    assert managers == []


async def test_colorwc_falls_back_because_the_frame_is_family_specific() -> None:
    managers: list[FakeManager] = []
    transport = BleGattTransport(available=True, manager_factory=manager_factory(managers))

    with pytest.raises(TransportUnavailable, match="family-specific"):
        await transport.send(
            device(),
            color_command(rgb=(255, 0, 0)),
        )

    assert managers == []


async def test_unknown_cloud_command_is_refused() -> None:
    managers: list[FakeManager] = []
    transport = BleGattTransport(available=True, manager_factory=manager_factory(managers))

    with pytest.raises(TransportUnavailable, match="no BLE GATT encoding"):
        await transport.send(device(), Command("toggle", {}))


async def test_router_prefers_ble_over_cloud() -> None:
    managers: list[FakeManager] = []
    iot = FakeIot()
    router = CommandRouter(
        (
            BleGattTransport(available=True, manager_factory=manager_factory(managers)),
            CloudMqttTransport(lambda: iot, enabled=True),
        )
    )

    used = await router.send(device(), power_command(on=True))

    assert used is TransportKind.BLE_GATT
    assert len(managers[0].frames) == 1
    assert iot.sent == []


async def test_router_falls_back_when_ble_write_fails(caplog: Any) -> None:
    caplog.set_level(logging.DEBUG)
    managers: list[FakeManager] = []
    iot = FakeIot()
    router = CommandRouter(
        (
            BleGattTransport(
                available=True,
                manager_factory=manager_factory(managers, fail=True),
            ),
            CloudMqttTransport(lambda: iot, enabled=True),
        )
    )

    used = await router.send(device(), power_command(on=True))

    assert used is TransportKind.CLOUD_MQTT
    assert iot.sent == [("topic/device-1", "turn", {"val": 1}, 0, 1)]
    assert "BLE command failed" in caplog.text
    assert ADDRESS in caplog.text


async def test_router_falls_back_when_ble_has_no_address() -> None:
    managers: list[FakeManager] = []
    iot = FakeIot()
    router = CommandRouter(
        (
            BleGattTransport(available=True, manager_factory=manager_factory(managers)),
            CloudMqttTransport(lambda: iot, enabled=True),
        )
    )
    target = device(ble_address=None)

    used = await router.send(target, power_command(on=True))

    assert used is TransportKind.CLOUD_MQTT
    assert managers == []


async def test_transport_without_ha_bluetooth_stays_unsupported() -> None:
    transport = BleGattTransport()
    target = device()

    assert transport.supported is False
    assert transport.supports(target) is False
    with pytest.raises(TransportUnavailable):
        await transport.send(target, power_command(on=True))
    assert transport.status()["enabled"] is False


async def test_ble_broadcast_remains_an_explicit_receive_only_placeholder() -> None:
    transport = BleBroadcastTransport()

    assert transport.supported is False
    assert transport.supports(device()) is False
    assert transport.status()["enabled"] is False


async def test_notification_becomes_a_decodable_status_report() -> None:
    managers: list[FakeManager] = []
    reports: list[Any] = []
    transport = BleGattTransport(
        available=True,
        manager_factory=manager_factory(managers),
        on_report=reports.append,
    )
    target = device()
    await transport.send(target, power_command(on=True))

    frame = build_frame(0x01, [1], opcode=0xAA)
    managers[0].callback(frame)

    assert len(reports) == 1
    report = reports[0]
    assert report.device_id == "device-1"
    assert report.payload == {"op": {"command": [bytes_to_base64(frame)]}}
    decoded = decode_message(target.profile, report.payload)
    assert decoded.power is True


async def test_write_acknowledgements_do_not_become_device_state() -> None:
    managers: list[FakeManager] = []
    reports: list[Any] = []
    transport = BleGattTransport(
        available=True,
        manager_factory=manager_factory(managers),
        on_report=reports.append,
    )
    await transport.send(device(), power_command(on=True))

    managers[0].callback(build_frame(0x01, [0]))

    assert reports == []


async def test_request_status_uses_the_manager() -> None:
    managers: list[FakeManager] = []
    transport = BleGattTransport(available=True, manager_factory=manager_factory(managers))

    await transport.request_status(device())

    assert managers[0].status_requests == 1


async def test_status_reports_started_and_connected() -> None:
    managers: list[FakeManager] = []
    transport = BleGattTransport(available=True, manager_factory=manager_factory(managers))

    assert transport.status()["started"] is False

    await transport.async_start()
    await transport.send(device(), power_command(on=True))

    status = transport.status()
    assert status["supported"] is True
    assert status["enabled"] is True
    assert status["started"] is True
    assert status["connected"] is True

    await transport.async_stop()
    assert transport.status()["started"] is False


async def test_async_stop_closes_every_manager() -> None:
    managers: list[FakeManager] = []
    transport = BleGattTransport(available=True, manager_factory=manager_factory(managers))
    await transport.send(device(), power_command(on=True))
    await transport.send(device(device_id="device-2"), power_command(on=False))

    await transport.async_stop()

    assert all(manager.stopped for manager in managers)
    assert transport.connected is False


class FakeCharacteristic:
    uuid = ble_api.GOVEE_CHARACTERISTIC_UUID


class FakeService:
    def __init__(self) -> None:
        self.characteristic = FakeCharacteristic()

    def get_characteristic(self, uuid: str) -> FakeCharacteristic | None:
        if uuid.lower() == ble_api.GOVEE_CHARACTERISTIC_UUID:
            return self.characteristic
        return None


class FakeServices:
    def __init__(self) -> None:
        self.service = FakeService()

    def get_service(self, uuid: str) -> FakeService | None:
        if uuid.lower() == ble_api.GOVEE_SERVICE_UUID:
            return self.service
        return None

    def __iter__(self) -> Any:
        return iter([self.service])


class FakeClient:
    def __init__(self) -> None:
        self.is_connected = True
        self.services = FakeServices()
        self.writes: list[tuple[Any, bytes, bool]] = []
        self.notifications: list[tuple[Any, Any]] = []
        self.stopped_notifications = False
        self.disconnected = False
        self.fail_write = False

    async def start_notify(self, characteristic: Any, callback: Any) -> None:
        self.notifications.append((characteristic, callback))

    async def write_gatt_char(self, characteristic: Any, data: bytes, *, response: bool) -> None:
        if self.fail_write:
            raise OSError("GATT write failed")
        self.writes.append((characteristic, bytes(data), response))

    async def stop_notify(self, characteristic: Any) -> None:
        self.stopped_notifications = True

    async def disconnect(self) -> None:
        self.is_connected = False
        self.disconnected = True


async def test_govee_ble_connects_writes_status_and_notifies(monkeypatch: Any) -> None:
    client = FakeClient()

    async def fake_device(_hass: Any, _address: str) -> Any:
        return object()

    async def fake_establish(_device: Any, _name: str, disconnected_callback: Any) -> FakeClient:
        client.disconnected_callback = disconnected_callback
        return client

    monkeypatch.setattr(ble_api, "_async_ble_device", fake_device)
    monkeypatch.setattr(ble_api, "_async_establish", fake_establish)
    notifications: list[bytes] = []
    manager = ble_api.GoveeBle(None, ADDRESS, "Lamp", notifications.append)

    frame = build_frame(0x01, [1])
    await manager.async_send_frames([frame])

    assert manager.connected is True
    characteristic, written, response = client.writes[0]
    assert characteristic.uuid == ble_api.GOVEE_CHARACTERISTIC_UUID
    assert written == frame
    assert response is True
    assert len(client.notifications) == 1

    notification = build_frame(0x01, [1], opcode=0xAA)
    client.notifications[0][1](client.notifications[0][0], notification)
    assert notifications == [notification]

    await manager.async_request_status()
    assert client.writes[-1][1] == ble_api.STATUS_FRAME

    await manager.async_stop()
    assert manager.connected is False
    assert client.stopped_notifications is True
    assert client.disconnected is True


async def test_govee_ble_connect_failure_raises_not_sent(monkeypatch: Any) -> None:
    async def missing_device(_hass: Any, _address: str) -> Any:
        raise ble_api.GoveeBleError("No Bluetooth device found")

    monkeypatch.setattr(ble_api, "_async_ble_device", missing_device)
    manager = ble_api.GoveeBle(None, ADDRESS, "Lamp", lambda _frame: None)

    with pytest.raises(ble_api.GoveeBleError, match="No Bluetooth device"):
        await manager.async_send_frames([build_frame(0x01, [1])])

    assert manager.connected is False


async def test_govee_ble_write_failure_disconnects(monkeypatch: Any) -> None:
    client = FakeClient()
    client.fail_write = True

    async def fake_device(_hass: Any, _address: str) -> Any:
        return object()

    async def fake_establish(_device: Any, _name: str, _disconnected_callback: Any) -> FakeClient:
        return client

    monkeypatch.setattr(ble_api, "_async_ble_device", fake_device)
    monkeypatch.setattr(ble_api, "_async_establish", fake_establish)
    manager = ble_api.GoveeBle(None, ADDRESS, "Lamp", lambda _frame: None)

    with pytest.raises(ble_api.GoveeBleError, match="write failed"):
        await manager.async_send_frames([build_frame(0x01, [1])])

    assert manager.connected is False
    assert client.disconnected is True


async def test_govee_ble_rejects_a_non_20_byte_frame() -> None:
    manager = ble_api.GoveeBle(None, ADDRESS, "Lamp", lambda _frame: None)

    with pytest.raises(ble_api.GoveeBleError, match="20-byte"):
        await manager.async_send_frames([b"\x33\x01\x01"])


async def test_router_raises_only_when_no_transport_accepts() -> None:
    router = CommandRouter((BleGattTransport(available=True),))

    with pytest.raises(GoveeApiError, match="No transport"):
        await router.send(device(ble_address=None), power_command(on=True))


async def test_transport_not_sent_is_what_the_router_sees() -> None:
    managers: list[FakeManager] = []
    transport = BleGattTransport(
        available=True,
        manager_factory=manager_factory(managers, fail=True),
    )

    with pytest.raises(TransportNotSent):
        await transport.send(device(), power_command(on=True))
