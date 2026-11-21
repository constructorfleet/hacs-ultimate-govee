"""Transport adapters and the per-device command router.

Each adapter owns one path to a device. The router picks the first adapter that
can carry a command for that device and falls back only when the command was
*not sent*. Adapters that are modelled but not implemented are explicit and
report ``supported = False`` rather than pretending to work.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .api.cloud import GoveeApiError
from .api.iot import GoveeIot
from .api.lan import GoveeLan
from .models import GoveeDevice
from .protocol.commands import WireCommand

_LOGGER = logging.getLogger(__name__)


class TransportKind(StrEnum):
    """The paths a command can take to a Govee device."""

    BLE_GATT = "ble_gatt"
    BLE_BROADCAST = "ble_broadcast"
    LAN_UDP = "lan_udp"
    LOCAL_MQTT = "local_mqtt"
    CLOUD_MQTT = "cloud_mqtt"


class TransportNotSent(Exception):
    """The transport did not accept the command, so another one may be tried."""


class TransportUnavailable(TransportNotSent):
    """The transport cannot currently reach this device."""


@dataclass(frozen=True, slots=True)
class StatusReport:
    """A decoded-later status payload reported by a transport."""

    device_id: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LanObservation:
    """A LAN datagram that proves a device is reachable on an address."""

    device_id: str
    ip: str
    seen_at: float


InboundEvent = StatusReport | LanObservation


class Transport(ABC):
    """One path by which commands and status requests reach a device."""

    kind: TransportKind

    @property
    @abstractmethod
    def supported(self) -> bool:
        """Whether this adapter has a working implementation."""

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Whether the adapter can currently send."""

    @abstractmethod
    def supports(self, device: GoveeDevice) -> bool:
        """Whether this adapter can address ``device`` for a command."""

    def supports_status(self, device: GoveeDevice) -> bool:
        """Whether this adapter can request status for ``device``."""
        return self.supports(device)

    @abstractmethod
    async def send(self, device: GoveeDevice, command: WireCommand) -> None:
        """Send ``command`` or raise :class:`TransportNotSent`."""

    @abstractmethod
    async def request_status(self, device: GoveeDevice) -> None:
        """Request a status report or raise :class:`TransportNotSent`."""

    @abstractmethod
    def status(self) -> dict[str, Any]:
        """Return diagnostics-friendly state for this adapter."""


class UnsupportedTransport(Transport):
    """A modelled path that is deliberately not implemented yet."""

    kind = TransportKind.LOCAL_MQTT

    @property
    def supported(self) -> bool:
        return False

    @property
    def connected(self) -> bool:
        return False

    def supports(self, device: GoveeDevice) -> bool:
        return False

    async def send(self, device: GoveeDevice, command: WireCommand) -> None:
        raise TransportUnavailable(f"{self.kind.value} is not implemented")

    async def request_status(self, device: GoveeDevice) -> None:
        raise TransportUnavailable(f"{self.kind.value} is not implemented")

    def status(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "supported": False,
            "enabled": False,
            "started": False,
            "connected": False,
        }


class LocalMqttTransport(UnsupportedTransport):
    """Wi-Fi local MQTT path used by some newer families."""

    kind = TransportKind.LOCAL_MQTT


class BleGattTransport(UnsupportedTransport):
    """BLE GATT path for direct local control."""

    kind = TransportKind.BLE_GATT


class BleBroadcastTransport(UnsupportedTransport):
    """Receive-only BLE advertisement observer for sensors."""

    kind = TransportKind.BLE_BROADCAST


class CloudMqttTransport(Transport):
    """Govee's AWS IoT / cloud MQTT path."""

    kind = TransportKind.CLOUD_MQTT

    def __init__(
        self,
        iot: Callable[[], GoveeIot | None],
        *,
        enabled: bool,
    ) -> None:
        self._iot = iot
        self.enabled = enabled

    @property
    def supported(self) -> bool:
        return self.enabled

    @property
    def connected(self) -> bool:
        client = self._iot()
        return bool(client and client.connected)

    def supports(self, device: GoveeDevice) -> bool:
        return (
            self.enabled
            and bool(device.iot_topic)
            and (client := self._iot()) is not None
            and client.connected
        )

    def supports_status(self, device: GoveeDevice) -> bool:
        return self.supports(device) and device.state.online

    async def send(self, device: GoveeDevice, command: WireCommand) -> None:
        client = self._iot()
        if not self.enabled or client is None or not client.connected:
            raise TransportUnavailable("The Govee IoT connection is not available")
        if not device.iot_topic:
            raise TransportUnavailable(f"{device.name} has no cloud topic")
        cmd, data = command.aws_payload()
        try:
            client.send_command(
                device.iot_topic,
                cmd,
                data,
                cmd_version=command.cmd_version,
                msg_type=command.msg_type,
            )
        except GoveeApiError as err:
            if not client.connected:
                raise TransportNotSent(str(err)) from err
            raise

    async def request_status(self, device: GoveeDevice) -> None:
        client = self._iot()
        if not self.enabled or client is None or not client.connected:
            raise TransportUnavailable("The Govee IoT connection is not available")
        if not device.iot_topic:
            raise TransportUnavailable(f"{device.name} has no cloud topic")
        client.request_status(
            device.iot_topic,
            cmd_version=device.profile.status_cmd_version,
        )

    def event(self, payload: dict[str, Any]) -> StatusReport:
        """Normalize an IoT message into a typed status report."""
        return StatusReport(str(payload.get("device") or ""), payload)

    def status(self) -> dict[str, Any]:
        client = self._iot()
        return {
            "kind": self.kind.value,
            "supported": self.supported,
            "enabled": self.enabled,
            "started": client is not None,
            "connected": bool(client and client.connected),
        }


class LanUdpTransport(Transport):
    """The local UDP multicast path."""

    kind = TransportKind.LAN_UDP

    def __init__(
        self,
        lan: Callable[[], GoveeLan | None],
        *,
        enabled: bool,
    ) -> None:
        self._lan = lan
        self.enabled = enabled

    @property
    def supported(self) -> bool:
        return self.enabled

    @property
    def connected(self) -> bool:
        return self._lan() is not None

    def supports(self, device: GoveeDevice) -> bool:
        return self.enabled and bool(device.lan_ip) and self._lan() is not None

    async def send(self, device: GoveeDevice, command: WireCommand) -> None:
        client = self._lan()
        if not self.enabled or client is None:
            raise TransportUnavailable("The LAN transport is not started")
        payload = command.lan_payload()
        if payload is None:
            raise TransportUnavailable("The command has no LAN payload")
        if not device.lan_ip:
            raise TransportUnavailable(f"{device.name} has no LAN address")
        cmd, data = payload
        ip = device.lan_ip
        try:
            await client.async_send_command(ip, cmd, data)
        except OSError as err:
            _LOGGER.debug("LAN command failed for %s (%s): %s", device.name, ip, err)
            device.lan_failed()
            raise TransportNotSent(str(err)) from err
        except RuntimeError as err:
            _LOGGER.debug("LAN command failed for %s (%s): %s", device.name, ip, err)
            raise TransportNotSent(str(err)) from err

    async def request_status(self, device: GoveeDevice) -> None:
        client = self._lan()
        if not self.enabled or client is None:
            raise TransportUnavailable("The LAN transport is not started")
        if not device.lan_ip:
            raise TransportUnavailable(f"{device.name} has no LAN address")
        ip = device.lan_ip
        try:
            await client.async_request_status(ip)
        except OSError as err:
            _LOGGER.debug(
                "LAN status request failed for %s (%s): %s", device.name, ip, err
            )
            device.lan_failed()
            raise TransportNotSent(str(err)) from err
        except RuntimeError as err:
            _LOGGER.debug(
                "LAN status request failed for %s (%s): %s", device.name, ip, err
            )
            raise TransportNotSent(str(err)) from err

    def event(
        self,
        device_id: str,
        command: str,
        data: dict[str, Any],
        ip: str,
        *,
        seen_at: float | None = None,
    ) -> InboundEvent:
        """Normalize a LAN datagram into a typed status report or observation."""
        if command == "devStatus":
            return StatusReport(device_id, data)
        return LanObservation(
            device_id, ip, seen_at if seen_at is not None else time.monotonic()
        )

    def status(self) -> dict[str, Any]:
        client = self._lan()
        return {
            "kind": self.kind.value,
            "supported": self.supported,
            "enabled": self.enabled,
            "started": client is not None,
            "connected": client is not None,
        }


class CommandRouter:
    """Choose the first usable transport for a device and command."""

    _ORDER = (
        TransportKind.BLE_GATT,
        TransportKind.LAN_UDP,
        TransportKind.LOCAL_MQTT,
        TransportKind.CLOUD_MQTT,
    )

    def __init__(self, transports: Iterable[Transport]) -> None:
        self._transports = {transport.kind: transport for transport in transports}

    def get(self, kind: TransportKind) -> Transport | None:
        """Return the adapter for ``kind`` if it is registered."""
        return self._transports.get(kind)

    def _ordered(self) -> Iterable[Transport]:
        for kind in self._ORDER:
            transport = self._transports.get(kind)
            if transport is not None:
                yield transport
        for kind, transport in self._transports.items():
            if kind not in self._ORDER and kind is not TransportKind.BLE_BROADCAST:
                yield transport

    async def send(self, device: GoveeDevice, command: WireCommand) -> TransportKind:
        """Send ``command`` and return the transport that accepted it."""
        for transport in self._ordered():
            if not transport.supports(device):
                continue
            if transport.kind is TransportKind.LAN_UDP and command.lan_payload() is None:
                continue
            try:
                await transport.send(device, command)
            except TransportNotSent:
                continue
            return transport.kind
        raise GoveeApiError(f"No transport is available for {device.name}")

    async def request_status(self, device: GoveeDevice) -> TransportKind:
        """Request status and return the transport that accepted it."""
        for transport in self._ordered():
            if not transport.supports_status(device):
                continue
            try:
                await transport.request_status(device)
            except TransportNotSent:
                continue
            return transport.kind
        raise GoveeApiError(f"No transport is available for {device.name}")

    def status(self) -> dict[str, Any]:
        """Return every adapter's state, including unsupported ones."""
        return {
            transport.kind.value: transport.status()
            for transport in self._transports.values()
        }
