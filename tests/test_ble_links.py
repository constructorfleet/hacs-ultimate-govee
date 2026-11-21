"""Tests for the owned BLE link lifecycle."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.ultimate_govee.ble_links import (
    BleLinkSet,
    BleLinkSetClosed,
    BleLinkSpec,
)
from custom_components.ultimate_govee.models import DeviceState, GoveeDevice
from custom_components.ultimate_govee.profiles import profile_for
from custom_components.ultimate_govee.protocol.command import power_command
from custom_components.ultimate_govee.transport import (
    BleGattTransport,
    CloudMqttTransport,
    CommandRouter,
    TransportKind,
    TransportNotSent,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"


class FakeLink:
    """A link handle with the manager surface the set and transport use."""

    def __init__(self, address: str, name: str, callback: Any) -> None:
        self.address = address
        self.name = name
        self.callback = callback
        self.connected = False
        self.stopped = False
        self.frames: list[list[bytes]] = []

    async def async_send_frames(self, frames: list[bytes]) -> None:
        self.frames.append(list(frames))
        self.connected = True

    async def async_request_status(self) -> None:
        self.connected = True

    async def async_stop(self) -> None:
        self.connected = False
        self.stopped = True


def spec(device_id: str, address: str = ADDRESS) -> BleLinkSpec:
    return BleLinkSpec(device_id, address, "Lamp")


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


def link_factory(links: list[FakeLink]) -> Any:
    def create(link_spec: BleLinkSpec) -> FakeLink:
        link = FakeLink(link_spec.address, link_spec.name, None)
        links.append(link)
        return link

    return create


def manager_factory(links: list[FakeLink]) -> Any:
    def create(_hass: Any, address: str, name: str, callback: Any) -> FakeLink:
        link = FakeLink(address, name, callback)
        links.append(link)
        return link

    return create


async def test_acquire_reuses_the_same_device_link() -> None:
    links: list[FakeLink] = []
    owned = BleLinkSet(link_factory(links))

    first = await owned.async_acquire(spec("device-1"))
    second = await owned.async_acquire(spec("device-1"))

    assert first is second
    assert len(links) == 1
    assert owned.count == 1


async def test_address_change_closes_the_old_link_before_opening() -> None:
    links: list[FakeLink] = []
    owned = BleLinkSet(link_factory(links))

    first = await owned.async_acquire(spec("device-1"))
    second = await owned.async_acquire(spec("device-1", "11:22:33:44:55:66"))

    assert first is not second
    assert first.stopped is True
    assert second.address == "11:22:33:44:55:66"
    assert owned.count == 1


async def test_the_link_set_is_bounded_and_evicts_the_least_recently_used() -> None:
    links: list[FakeLink] = []
    owned = BleLinkSet(link_factory(links), max_links=2)

    await owned.async_acquire(spec("device-1"))
    await owned.async_acquire(spec("device-2"))
    # Touch device-1 so device-2 is the idle victim.
    await owned.async_acquire(spec("device-1"))
    await owned.async_acquire(spec("device-3"))

    assert owned.count == 2
    assert owned.get("device-1") is not None
    assert owned.get("device-3") is not None
    assert owned.get("device-2") is None
    assert links[1].stopped is True


async def test_stop_closes_every_link_and_refuses_to_reopen_implicitly() -> None:
    links: list[FakeLink] = []
    owned = BleLinkSet(link_factory(links))
    await owned.async_acquire(spec("device-1"))

    await owned.async_stop()

    assert owned.started is False
    assert owned.count == 0
    assert links[0].stopped is True
    with pytest.raises(BleLinkSetClosed):
        await owned.async_acquire(spec("device-1"))


async def test_start_reopens_a_stopped_set() -> None:
    links: list[FakeLink] = []
    owned = BleLinkSet(link_factory(links))
    await owned.async_stop()

    await owned.async_start()
    handle = await owned.async_acquire(spec("device-1"))

    assert owned.started is True
    assert handle.address == ADDRESS


async def test_evict_closes_one_link_only() -> None:
    links: list[FakeLink] = []
    owned = BleLinkSet(link_factory(links))
    first = await owned.async_acquire(spec("device-1"))
    second = await owned.async_acquire(spec("device-2"))

    await owned.async_evict("device-1")

    assert first.stopped is True
    assert second.stopped is False
    assert owned.get("device-1") is None


async def test_ble_status_reports_a_real_link_count() -> None:
    managers: list[FakeLink] = []
    transport = BleGattTransport(available=True, manager_factory=manager_factory(managers))

    await transport.send(device(), power_command(on=True))
    await transport.send(device(device_id="device-2"), power_command(on=False))

    status = transport.status()
    assert status.started is True
    assert status.connected is True
    assert status.links == 2
    assert transport.connection_count == 2


async def test_a_stopped_ble_transport_reports_not_sent_and_falls_back() -> None:
    managers: list[FakeLink] = []
    iot = FakeIot()
    transport = BleGattTransport(available=True, manager_factory=manager_factory(managers))
    await transport.async_start()
    await transport.send(device(), power_command(on=True))
    await transport.async_stop()

    with pytest.raises(TransportNotSent):
        await transport.send(device(), power_command(on=True))

    router = CommandRouter((transport, CloudMqttTransport(enabled=True, client=iot)))  # type: ignore[arg-type]
    used = await router.send(device(), power_command(on=True))

    assert used is TransportKind.CLOUD_MQTT
    assert iot.sent == [("topic/device-1", "turn", {"val": 1}, 0, 1)]


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
