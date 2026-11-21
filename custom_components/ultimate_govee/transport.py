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

from .api.ble import GoveeBle
from .api.cloud import GoveeApiError
from .api.iot import GoveeIot
from .api.lan import GoveeLan
from .models import GoveeDevice
from .profiles import DeviceProfile
from .protocol.codec import build_frame, bytes_to_base64
from .protocol.command import (
    ACTION_BRIGHTNESS,
    ACTION_CLOUD,
    ACTION_COLOR,
    ACTION_FRAMES,
    ACTION_POWER,
    STRATEGY_PT_REAL,
    Command,
)

_LOGGER = logging.getLogger(__name__)
FRAME_LENGTH = 20
BLE_STATUS_PREFIXES = frozenset({0xAA, 0xEE})
GANG_VALUES = ((17, 16), (34, 32), (68, 64))
CLOUD_ACTIONS = frozenset(
    {ACTION_POWER, ACTION_BRIGHTNESS, ACTION_COLOR, ACTION_FRAMES, ACTION_CLOUD}
)
LAN_ACTIONS = frozenset({ACTION_POWER, ACTION_BRIGHTNESS, ACTION_COLOR})
BLE_ACTIONS = frozenset({ACTION_POWER, ACTION_BRIGHTNESS, ACTION_FRAMES})


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

    def supports_command(self, command: Command) -> bool:
        """Whether this adapter can encode ``command`` for its own path."""
        return True

    @abstractmethod
    async def send(self, device: GoveeDevice, command: Command) -> None:
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

    def supports_command(self, command: Command) -> bool:
        return False

    async def send(self, device: GoveeDevice, command: Command) -> None:
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


class BleGattTransport(Transport):
    """BLE GATT path for direct local control.

    A connection is opened lazily per device. ``supported`` only becomes true
    when Home Assistant's Bluetooth component is loaded (or the transport was
    explicitly constructed as available); devices without a cloud-provided BLE
    address are never claimed.
    """

    kind = TransportKind.BLE_GATT

    def __init__(
        self,
        hass: Any | None = None,
        *,
        available: bool | None = None,
        manager_factory: Callable[[Any, str, str, Callable[[bytes], None]], Any] | None = None,
        on_report: Callable[[StatusReport], None] | None = None,
    ) -> None:
        self.hass = hass
        self.enabled = _bluetooth_available(hass) if available is None else available
        self._manager_factory = manager_factory or _default_ble_manager
        self._on_report = on_report
        self._managers: dict[str, Any] = {}
        self._started = False

    @property
    def supported(self) -> bool:
        return self.enabled

    @property
    def connected(self) -> bool:
        return any(
            bool(getattr(manager, "connected", False)) for manager in self._managers.values()
        )

    def supports(self, device: GoveeDevice) -> bool:
        return self.enabled and bool(device.ble_address)

    async def async_start(self) -> None:
        """Prepare the transport.

        Connections are opened on demand, so starting only records that BLE is
        available. This keeps the coordinator's start/stop contract explicit.
        """
        self._started = self.enabled
        if self.enabled:
            _LOGGER.debug("BLE GATT transport is available")
        else:
            _LOGGER.debug("BLE GATT transport is unavailable; using other transports")

    async def async_stop(self) -> None:
        """Close every per-device BLE connection."""
        self._started = False
        managers = list(self._managers.values())
        self._managers.clear()
        for manager in managers:
            stop = getattr(manager, "async_stop", None)
            if stop is None:
                continue
            try:
                await stop()
            except Exception as err:
                _LOGGER.debug("BLE shutdown failed: %s", err)

    def supports_command(self, command: Command) -> bool:
        return command.action in BLE_ACTIONS

    async def send(self, device: GoveeDevice, command: Command) -> None:
        if not self.supports(device):
            raise TransportUnavailable(f"{device.name} has no BLE GATT path")
        frames = _ble_frames(command, device.profile)
        manager = await self._async_manager(device)
        try:
            await manager.async_send_frames(frames)
        except Exception as err:
            _LOGGER.debug(
                "BLE command failed for %s (%s): %s",
                device.name,
                device.ble_address,
                err,
            )
            raise TransportNotSent(str(err)) from err

    async def request_status(self, device: GoveeDevice) -> None:
        if not self.supports(device):
            raise TransportUnavailable(f"{device.name} has no BLE GATT path")
        manager = await self._async_manager(device)
        try:
            await manager.async_request_status()
        except Exception as err:
            _LOGGER.debug(
                "BLE status request failed for %s (%s): %s",
                device.name,
                device.ble_address,
                err,
            )
            raise TransportNotSent(str(err)) from err

    async def _async_manager(self, device: GoveeDevice) -> Any:
        address = device.ble_address
        if not address:
            raise TransportUnavailable(f"{device.name} has no BLE address")
        manager = self._managers.get(device.device_id)
        if manager is not None and getattr(manager, "address", address) == address:
            return manager
        if manager is not None:
            stop = getattr(manager, "async_stop", None)
            if stop is not None:
                try:
                    await stop()
                except Exception as err:
                    _LOGGER.debug("BLE reconnect cleanup failed for %s: %s", device.name, err)
        manager = self._manager_factory(
            self.hass,
            address,
            device.name,
            self._notification_callback(device.device_id),
        )
        self._managers[device.device_id] = manager
        return manager

    def _notification_callback(self, device_id: str) -> Callable[[bytes], None]:
        def _handle(frame: bytes) -> None:
            self._handle_notification(device_id, frame)

        return _handle

    def _handle_notification(self, device_id: str, frame: bytes) -> None:
        """Turn one GATT notification into a status report for the coordinator."""
        data = bytes(frame)
        if not data:
            return
        if data[0] not in BLE_STATUS_PREFIXES:
            # Write acknowledgements share the characteristic (``33 <cmd> 00``)
            # and are not device state. Forwarding them would overwrite state.
            _LOGGER.debug(
                "Ignoring non-status BLE frame from %s: %s",
                device_id,
                data.hex(" "),
            )
            return
        if self._on_report is not None:
            self._on_report(StatusReport(device_id, {"op": {"command": [bytes_to_base64(data)]}}))

    def status(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "supported": self.supported,
            "enabled": self.enabled,
            "started": self._started,
            "connected": self.connected,
        }


class BleBroadcastTransport(UnsupportedTransport):
    """Receive-only BLE advertisement observer for sensors.

    The Govee advertisement only carries identity (goods type, pact type and
    protocol revision); sensor readings arrive through GATT notifications or
    cloud push. There is no generic, safe reading to expose from an advert, so
    this path stays explicitly unsupported rather than inventing sensor data.
    """

    kind = TransportKind.BLE_BROADCAST


def _bluetooth_available(hass: Any | None) -> bool:
    """Return whether Home Assistant's Bluetooth component is loaded."""
    if hass is None:
        return False
    components = getattr(getattr(hass, "config", None), "components", ())
    return "bluetooth" in components


def _default_ble_manager(
    hass: Any,
    address: str,
    name: str,
    on_notification: Callable[[bytes], None],
) -> GoveeBle:
    return GoveeBle(hass, address, name, on_notification)


def _ble_frames(command: Command, profile: DeviceProfile) -> list[bytes]:
    """Encode a command intent as documented BLE frames or refuse it."""
    parameters = command.parameters

    if command.action == ACTION_POWER:
        # Wire power values are profile-specific (some switches use 17/16);
        # the BLE frame is always a plain 1/0, including per-gang power.
        return [build_frame(0x01, [1 if parameters["on"] else 0])]

    if command.action == ACTION_BRIGHTNESS:
        percent = max(0, min(100, int(parameters["percent"])))
        # Legacy 254-scale models map 0..100 onto 20..254 over BLE.
        ble_value = 20 + round(percent * 234 / 100) if profile.brightness_max == 254 else percent
        return [build_frame(0x04, [ble_value])]

    if command.action == ACTION_FRAMES:
        frames = list(parameters.get("frames") or ())
        if not frames:
            raise TransportUnavailable("The command has no BLE frames")
        strategy = parameters.get("strategy", STRATEGY_PT_REAL)
        for frame in frames:
            if len(frame) != FRAME_LENGTH or _checksum(frame[: FRAME_LENGTH - 1]) != frame[-1]:
                raise TransportUnavailable(
                    f"The {strategy} payload is not a valid 20-byte BLE frame"
                )
        return frames

    if command.action == ACTION_COLOR:
        # The RGB/colour-temperature layout differs by family (0x05/0x02,
        # 0x05/0x0D, 0x05/0x15 and per-SKU variants), and nothing in the
        # device profile selects one. Fall back instead of sending wrong bytes.
        raise TransportUnavailable(
            "BLE colour frames are family-specific; use LAN or cloud for colorwc"
        )

    raise TransportUnavailable(f"{command.action} has no BLE GATT encoding")


def _checksum(data: bytes) -> int:
    checksum = 0
    for value in data:
        checksum ^= value
    return checksum


def _clamp_percent(value: Any) -> int:
    return max(0, min(100, int(value)))


def _gang_values(channel: int) -> tuple[int, int]:
    index = max(0, min(len(GANG_VALUES) - 1, channel))
    return GANG_VALUES[index]


def _color_fields(parameters: dict[str, Any]) -> dict[str, Any]:
    red, green, blue = parameters["rgb"]
    return {
        "color": {"r": red, "g": green, "b": blue},
        "colorTemInKelvin": int(parameters.get("kelvin", 0)),
    }


def _frame_fields(parameters: dict[str, Any]) -> dict[str, Any]:
    return {"command": [bytes_to_base64(frame) for frame in parameters["frames"]]}


def _cloud_wire(command: Command, profile: DeviceProfile) -> tuple[str, dict[str, Any]]:
    """Encode a command intent for the AWS IoT command envelope."""
    parameters = command.parameters
    if command.action == ACTION_POWER:
        channel = parameters.get("channel")
        if channel is not None:
            on_value, off_value = _gang_values(int(channel))
            value = on_value if parameters["on"] else off_value
        else:
            value = profile.power_on if parameters["on"] else profile.power_off
        return "turn", {"val": value}
    if command.action == ACTION_BRIGHTNESS:
        percent = _clamp_percent(parameters["percent"])
        return "brightness", {"val": round(percent * profile.brightness_max / 100)}
    if command.action == ACTION_COLOR:
        return "colorwc", _color_fields(parameters)
    if command.action == ACTION_FRAMES:
        strategy = parameters.get("strategy", STRATEGY_PT_REAL)
        return strategy, _frame_fields(parameters)
    if command.action == ACTION_CLOUD:
        return str(parameters["command"]), dict(parameters.get("data") or {})
    raise TransportUnavailable(f"{command.action} has no cloud encoding")


def _lan_wire(command: Command) -> tuple[str, dict[str, Any]] | None:
    """Encode a command intent for the LAN UDP envelope, or decline it."""
    parameters = command.parameters
    if command.action == ACTION_POWER:
        channel = parameters.get("channel")
        if channel is not None:
            on_value, off_value = _gang_values(int(channel))
            value = on_value if parameters["on"] else off_value
        else:
            value = 1 if parameters["on"] else 0
        return "turn", {"value": value}
    if command.action == ACTION_BRIGHTNESS:
        return "brightness", {"value": _clamp_percent(parameters["percent"])}
    if command.action == ACTION_COLOR:
        return "colorwc", _color_fields(parameters)
    if command.action == ACTION_FRAMES and parameters.get("lan", True):
        return STRATEGY_PT_REAL, _frame_fields(parameters)
    return None


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

    def supports_command(self, command: Command) -> bool:
        return command.action in CLOUD_ACTIONS

    async def send(self, device: GoveeDevice, command: Command) -> None:
        client = self._iot()
        if not self.enabled or client is None or not client.connected:
            raise TransportUnavailable("The Govee IoT connection is not available")
        if not device.iot_topic:
            raise TransportUnavailable(f"{device.name} has no cloud topic")
        cmd, data = _cloud_wire(command, device.profile)
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

    def supports_command(self, command: Command) -> bool:
        if command.action in LAN_ACTIONS:
            return True
        if command.action == ACTION_FRAMES:
            return bool(command.parameters.get("lan", True))
        return False

    async def send(self, device: GoveeDevice, command: Command) -> None:
        client = self._lan()
        if not self.enabled or client is None:
            raise TransportUnavailable("The LAN transport is not started")
        payload = _lan_wire(command)
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
            _LOGGER.debug("LAN status request failed for %s (%s): %s", device.name, ip, err)
            device.lan_failed()
            raise TransportNotSent(str(err)) from err
        except RuntimeError as err:
            _LOGGER.debug("LAN status request failed for %s (%s): %s", device.name, ip, err)
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
        return LanObservation(device_id, ip, seen_at if seen_at is not None else time.monotonic())

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

    async def send(self, device: GoveeDevice, command: Command) -> TransportKind:
        """Send ``command`` and return the transport that accepted it.

        Selection uses device reachability and each adapter's own command
        support. Fallback happens only when an adapter that claimed the command
        reports it was not sent.
        """
        for transport in self._ordered():
            if not transport.supports(device) or not transport.supports_command(command):
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
        return {transport.kind.value: transport.status() for transport in self._transports.values()}
