"""Transport adapters and the per-device command router.

Each adapter owns one path to a device. The router picks the first adapter that
can carry a command for that device and falls back only when the command was
*not sent*. Adapters that are modelled but not implemented are explicit and
report ``supported = False`` rather than pretending to work.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .api.ble import GoveeBle
from .api.cloud import GoveeApiError
from .api.iot import GoveeIot
from .api.lan import GoveeLan
from .ble_links import BleLinkSet, BleLinkSetClosed, BleLinkSpec
from .models import GoveeDevice
from .options import GoveeOptions
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


class NoTransportAvailable(GoveeApiError, TransportNotSent):
    """No adapter could carry a command or status request for this device."""


@dataclass(frozen=True, slots=True)
class StatusReport:
    """A decoded-later status payload reported by a transport.

    ``ip`` and ``seen_at`` are present when the report itself proves that the
    device answered on an endpoint, as a LAN ``devStatus`` datagram does.
    """

    device_id: str
    payload: dict[str, Any]
    ip: str | None = None
    seen_at: float | None = None


@dataclass(frozen=True, slots=True)
class LanObservation:
    """A LAN datagram that proves a device is reachable on an address."""

    device_id: str
    ip: str
    seen_at: float


InboundEvent = StatusReport | LanObservation


@dataclass(frozen=True, slots=True)
class TransportStatus(Mapping[str, Any]):
    """The one status record every adapter reports.

    The fields are the contract; the mapping view keeps diagnostics and older
    callers (``status["lan_udp"]["connected"]``) working from the same record.
    """

    kind: TransportKind
    supported: bool
    enabled: bool
    started: bool
    connected: bool
    links: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return the JSON-friendly shape used by diagnostics."""
        return {
            "kind": self.kind.value,
            "supported": self.supported,
            "enabled": self.enabled,
            "started": self.started,
            "connected": self.connected,
            "links": self.links,
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())


class Transport(ABC):
    """One path by which commands and status requests reach a device."""

    kind: TransportKind

    #: Seconds between this adapter's periodic scans; 0 means every tick.
    scan_interval: float = 0.0

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

    async def async_start(self) -> None:
        """Prepare this adapter's client.

        Adapters with nothing to open keep the default no-op.
        """
        return

    async def async_stop(self) -> None:
        """Release this adapter's client.

        Adapters with nothing to close keep the default no-op.
        """
        return

    async def async_scan(self) -> None:
        """Run any periodic discovery this adapter owns.

        Only adapters that discover devices implement this.
        """
        return

    @abstractmethod
    async def send(self, device: GoveeDevice, command: Command) -> None:
        """Send ``command`` or raise :class:`TransportNotSent`."""

    @abstractmethod
    async def request_status(self, device: GoveeDevice) -> None:
        """Request a status report or raise :class:`TransportNotSent`."""

    @abstractmethod
    def status(self) -> TransportStatus:
        """Return this adapter's typed status record."""


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

    def status(self) -> TransportStatus:
        return TransportStatus(
            kind=self.kind,
            supported=False,
            enabled=False,
            started=False,
            connected=False,
        )


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
        max_connections: int = 8,
    ) -> None:
        self.hass = hass
        self.enabled = _bluetooth_available(hass) if available is None else available
        self._manager_factory = manager_factory or _default_ble_manager
        self._on_report = on_report
        self._links = BleLinkSet(self._open_link, max_links=max_connections)

    @property
    def supported(self) -> bool:
        return self.enabled

    @property
    def connected(self) -> bool:
        return self._links.connected

    @property
    def connection_count(self) -> int:
        """Return the number of open per-device links."""
        return self._links.count

    def supports(self, device: GoveeDevice) -> bool:
        return self.enabled and bool(device.ble_address)

    async def async_start(self) -> None:
        """Open the connection set so links may be created on demand."""
        if self.enabled:
            await self._links.async_start()
            _LOGGER.debug("BLE GATT transport is available")
        else:
            await self._links.async_stop()
            _LOGGER.debug("BLE GATT transport is unavailable; using other transports")

    async def async_stop(self) -> None:
        """Close every per-device BLE connection and refuse new ones."""
        await self._links.async_stop()

    def supports_command(self, command: Command) -> bool:
        return command.action in BLE_ACTIONS

    async def send(self, device: GoveeDevice, command: Command) -> None:
        if not self.supports(device):
            raise TransportUnavailable(f"{device.name} has no BLE GATT path")
        frames = _ble_frames(command, device.profile)
        try:
            manager = await self._async_manager(device)
        except TransportNotSent:
            raise
        except Exception as err:  # an open failure is a not-sent result
            raise TransportNotSent(str(err)) from err
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
        finally:
            await self._async_release_evicted(device.device_id, manager)

    async def request_status(self, device: GoveeDevice) -> None:
        if not self.supports(device):
            raise TransportUnavailable(f"{device.name} has no BLE GATT path")
        try:
            manager = await self._async_manager(device)
        except TransportNotSent:
            raise
        except Exception as err:
            raise TransportNotSent(str(err)) from err
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
        finally:
            await self._async_release_evicted(device.device_id, manager)

    async def _async_release_evicted(self, device_id: str, manager: Any) -> None:
        """Close a link that stopped being current while it was sending."""
        if not self._links.owns(device_id, manager):
            await self._links.async_close(manager)

    async def _async_manager(self, device: GoveeDevice) -> Any:
        address = device.ble_address
        if not address:
            raise TransportUnavailable(f"{device.name} has no BLE address")
        try:
            return await self._links.async_acquire(
                BleLinkSpec(device.device_id, address, device.name)
            )
        except BleLinkSetClosed as err:
            raise TransportUnavailable("The BLE GATT transport is stopped") from err

    def _open_link(self, spec: BleLinkSpec) -> Any:
        return self._manager_factory(
            self.hass,
            spec.address,
            spec.name,
            self._notification_callback(spec.device_id),
        )

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

    def status(self) -> TransportStatus:
        return TransportStatus(
            kind=self.kind,
            supported=self.supported,
            enabled=self.enabled,
            started=self._links.started,
            connected=self.connected,
            links=self._links.count,
        )


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
    """Govee's AWS IoT / cloud MQTT path.

    The adapter owns its ``GoveeIot`` client: it asks the supplied certificate
    source for credentials, connects on start, disconnects on stop, and
    normalizes inbound messages into :class:`StatusReport` events.
    """

    kind = TransportKind.CLOUD_MQTT

    def __init__(
        self,
        *,
        enabled: bool,
        account_id: str = "",
        client_id: str = "",
        account_topic: str = "",
        cert_dir: Path | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        certificate: Callable[[], Awaitable[dict[str, Any]]] | None = None,
        on_event: Callable[[InboundEvent], None] | None = None,
        client: GoveeIot | None = None,
    ) -> None:
        self.enabled = enabled
        self._account_id = account_id
        self._client_id = client_id
        self._account_topic = account_topic
        self._cert_dir = cert_dir
        self._loop = loop
        self._certificate = certificate
        self._on_event = on_event
        self._iot = client

    @property
    def supported(self) -> bool:
        return self.enabled

    @property
    def connected(self) -> bool:
        return bool(self._iot and self._iot.connected)

    def supports(self, device: GoveeDevice) -> bool:
        return (
            self.enabled
            and bool(device.iot_topic)
            and self._iot is not None
            and self._iot.connected
        )

    def supports_status(self, device: GoveeDevice) -> bool:
        return self.supports(device) and device.state.online

    def supports_command(self, command: Command) -> bool:
        return command.action in CLOUD_ACTIONS

    async def async_start(self) -> None:
        """Connect the IoT client if credentials and an account topic exist."""
        if not self.enabled or self._iot is not None:
            return
        if not self._account_topic:
            _LOGGER.warning("Govee did not return an account topic; skipping IoT transport")
            return
        if self._certificate is None or self._cert_dir is None or self._loop is None:
            _LOGGER.warning("The IoT transport is missing its certificate source")
            return
        try:
            certificate = await self._certificate()
        except Exception as err:  # keep the LAN/polling paths alive
            _LOGGER.warning("Unable to obtain the Govee IoT certificate: %s", err)
            return
        iot = GoveeIot(
            account_id=self._account_id,
            client_id=self._client_id,
            account_topic=self._account_topic,
            cert_dir=self._cert_dir,
            loop=self._loop,
            on_message=self._handle_message,
        )
        try:
            await iot.async_start(certificate)
        except Exception as err:  # keep the LAN/polling paths alive
            _LOGGER.warning("Unable to connect to Govee IoT: %s", err)
            return
        self._iot = iot

    async def async_stop(self) -> None:
        """Disconnect the IoT client and forget it."""
        client = self._iot
        self._iot = None
        if client is not None:
            await client.async_stop()

    async def send(self, device: GoveeDevice, command: Command) -> None:
        client = self._iot
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
        client = self._iot
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

    def _handle_message(self, payload: dict[str, Any]) -> None:
        """Normalize one inbound IoT message and hand it to the consumer."""
        if self._on_event is not None:
            self._on_event(self.event(payload))

    def status(self) -> TransportStatus:
        client = self._iot
        return TransportStatus(
            kind=self.kind,
            supported=self.supported,
            enabled=self.enabled,
            started=client is not None,
            connected=bool(client and client.connected),
        )


class LanUdpTransport(Transport):
    """The local UDP multicast path.

    The adapter owns its ``GoveeLan`` client and turns every datagram into
    either a :class:`StatusReport` or a :class:`LanObservation`. Endpoint loss
    is reported through ``on_endpoint_lost`` instead of mutating a device.
    """

    kind = TransportKind.LAN_UDP

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop | None = None,
        *,
        enabled: bool,
        scan_interval: float = 0.0,
        on_event: Callable[[InboundEvent], None] | None = None,
        on_endpoint_lost: Callable[[str], None] | None = None,
        client: GoveeLan | None = None,
    ) -> None:
        self.enabled = enabled
        self.scan_interval = float(scan_interval)
        self._loop = loop
        self._on_event = on_event
        self._on_endpoint_lost = on_endpoint_lost
        self._lan = client

    @property
    def supported(self) -> bool:
        return self.enabled

    @property
    def connected(self) -> bool:
        return self._lan is not None

    def supports(self, device: GoveeDevice) -> bool:
        return self.enabled and bool(device.lan_ip) and self._lan is not None

    def supports_command(self, command: Command) -> bool:
        if command.action in LAN_ACTIONS:
            return True
        if command.action == ACTION_FRAMES:
            return bool(command.parameters.get("lan", True))
        return False

    async def async_start(self) -> None:
        """Bind the LAN sockets when the transport is enabled."""
        if not self.enabled or self._lan is not None:
            return
        if self._loop is None:
            _LOGGER.warning("The LAN transport is missing its event loop")
            return
        lan = GoveeLan(self._loop, self._handle_message)
        try:
            await lan.async_start()
        except Exception as err:  # keep cloud polling alive when LAN is unavailable
            _LOGGER.warning("Unable to start Govee LAN discovery: %s", err)
            return
        self._lan = lan

    async def async_stop(self) -> None:
        """Close the LAN sockets and forget the client."""
        client = self._lan
        self._lan = None
        if client is not None:
            await client.async_stop()

    async def async_scan(self) -> None:
        """Send the multicast scan request when the client is running."""
        if self._lan is None:
            return
        try:
            await self._lan.async_scan()
        except OSError as err:
            _LOGGER.debug("LAN scan failed: %s", err)

    async def send(self, device: GoveeDevice, command: Command) -> None:
        client = self._lan
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
            self._endpoint_lost(device.device_id)
            raise TransportNotSent(str(err)) from err
        except RuntimeError as err:
            _LOGGER.debug("LAN command failed for %s (%s): %s", device.name, ip, err)
            raise TransportNotSent(str(err)) from err

    async def request_status(self, device: GoveeDevice) -> None:
        client = self._lan
        if not self.enabled or client is None:
            raise TransportUnavailable("The LAN transport is not started")
        if not device.lan_ip:
            raise TransportUnavailable(f"{device.name} has no LAN address")
        ip = device.lan_ip
        try:
            await client.async_request_status(ip)
        except OSError as err:
            _LOGGER.debug("LAN status request failed for %s (%s): %s", device.name, ip, err)
            self._endpoint_lost(device.device_id)
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
        observed_at = seen_at if seen_at is not None else time.monotonic()
        if command == "devStatus":
            return StatusReport(device_id, data, ip=ip, seen_at=observed_at)
        return LanObservation(device_id, ip, observed_at)

    def _handle_message(self, device_id: str, command: str, data: dict[str, Any], ip: str) -> None:
        """Normalize one inbound datagram and hand it to the consumer."""
        if self._on_event is not None:
            self._on_event(self.event(device_id, command, data, ip))

    def _endpoint_lost(self, device_id: str) -> None:
        if self._on_endpoint_lost is not None:
            self._on_endpoint_lost(device_id)

    def status(self) -> TransportStatus:
        client = self._lan
        return TransportStatus(
            kind=self.kind,
            supported=self.supported,
            enabled=self.enabled,
            started=client is not None,
            connected=client is not None,
        )


@dataclass(frozen=True, slots=True)
class TransportContext:
    """The non-option inputs the router needs to build adapters."""

    hass: Any
    account_id: str = ""
    client_id: str = ""
    account_topic: str = ""
    cert_dir: Path | None = None
    certificate: Callable[[], Awaitable[dict[str, Any]]] | None = None
    on_event: Callable[[InboundEvent], None] | None = None
    on_endpoint_lost: Callable[[str], None] | None = None


TransportBuilder = Callable[[TransportContext, GoveeOptions], Transport | None]


def _build_ble_gatt(context: TransportContext, _options: GoveeOptions) -> Transport:
    return BleGattTransport(context.hass, on_report=context.on_event)


def _build_ble_broadcast(_context: TransportContext, _options: GoveeOptions) -> Transport:
    return BleBroadcastTransport()


def _build_lan_udp(context: TransportContext, options: GoveeOptions) -> Transport:
    return LanUdpTransport(
        context.hass.loop,
        enabled=options.enable_lan,
        scan_interval=options.lan_scan_interval,
        on_event=context.on_event,
        on_endpoint_lost=context.on_endpoint_lost,
    )


def _build_local_mqtt(_context: TransportContext, _options: GoveeOptions) -> Transport:
    return LocalMqttTransport()


def _build_cloud_mqtt(context: TransportContext, options: GoveeOptions) -> Transport:
    return CloudMqttTransport(
        enabled=options.enable_iot,
        account_id=context.account_id,
        client_id=context.client_id,
        account_topic=context.account_topic,
        cert_dir=context.cert_dir,
        loop=context.hass.loop,
        certificate=context.certificate,
        on_event=context.on_event,
    )


#: One row per known path. Adding a Transport means adding one builder here.
DEFAULT_TRANSPORT_BUILDERS: tuple[TransportBuilder, ...] = (
    _build_ble_gatt,
    _build_ble_broadcast,
    _build_lan_udp,
    _build_local_mqtt,
    _build_cloud_mqtt,
)


class CommandRouter:
    """Choose the first usable transport for a device and command."""

    _ORDER = (
        TransportKind.BLE_GATT,
        TransportKind.LAN_UDP,
        TransportKind.LOCAL_MQTT,
        TransportKind.CLOUD_MQTT,
    )

    def __init__(self, transports: Iterable[Transport]) -> None:
        self._transports: dict[TransportKind, Transport] = {}
        for transport in transports:
            self.register(transport)
        self._last_scan: dict[TransportKind, float] = {}

    @classmethod
    def from_options(
        cls,
        options: GoveeOptions,
        context: TransportContext,
        *,
        builders: Iterable[TransportBuilder] = DEFAULT_TRANSPORT_BUILDERS,
    ) -> CommandRouter:
        """Build the adapter set from normalized options and one context.

        A new Transport registers one builder; callers keep constructing the
        router, never the concrete adapters.
        """
        transports = (build(context, options) for build in builders)
        return cls(transport for transport in transports if transport is not None)

    def register(self, transport: Transport) -> None:
        """Add one adapter; a later adapter for the same kind replaces it."""
        self._transports[transport.kind] = transport

    def get(self, kind: TransportKind) -> Transport | None:
        """Return the adapter for ``kind`` if it is registered."""
        return self._transports.get(kind)

    async def async_start(self) -> None:
        """Start every registered adapter in registration order."""
        for transport in self._transports.values():
            await transport.async_start()

    async def async_stop(self) -> None:
        """Stop every registered adapter in reverse registration order."""
        for transport in reversed(tuple(self._transports.values())):
            await transport.async_stop()

    async def async_scan(self, now: float | None = None) -> None:
        """Run each adapter's discovery hook when its cadence is due.

        The router owns the clock, so adapters declare ``scan_interval`` and
        callers simply tick. ``now`` is injectable for tests.
        """
        observed = time.monotonic() if now is None else now
        for transport in self._transports.values():
            interval = transport.scan_interval
            if interval > 0:
                last = self._last_scan.get(transport.kind, 0.0)
                if observed - last < interval:
                    continue
            self._last_scan[transport.kind] = observed
            await transport.async_scan()

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
        raise NoTransportAvailable(f"No transport is available for {device.name}")

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
        raise NoTransportAvailable(f"No transport is available for {device.name}")

    def status(self) -> dict[str, TransportStatus]:
        """Return every adapter's typed status, including unsupported ones."""
        return {transport.kind.value: transport.status() for transport in self._transports.values()}

    def status_dict(self) -> dict[str, dict[str, Any]]:
        """Return the JSON-friendly diagnostics shape for every adapter."""
        return {kind: record.as_dict() for kind, record in self.status().items()}
