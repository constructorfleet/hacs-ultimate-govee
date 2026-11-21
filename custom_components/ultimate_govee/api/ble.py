"""BLE GATT connection manager for Govee devices.

Every Govee device that exposes the vendor GATT service speaks the same
20-byte frame format documented in ``protocol/codec.py``::

    0x33  <cmd>  <16 payload bytes>  <XOR of bytes 0..18>

The common service is ``00010203-0405-0607-0809-0a0b0c0d1910`` and the same
characteristic (``...2b11``) carries both writes and notifications.

Bluetooth is optional. Home Assistant's Bluetooth component and
``bleak_retry_connector`` are imported lazily so this module can be imported
(and tested) on a host without a Bluetooth stack. A :class:`GoveeBle` instance
raises :class:`GoveeBleError` when it cannot connect or write; the transport
turns that into a *not sent* result so the router can try the next path.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from typing import Any

from ..protocol.codec import build_frame

_LOGGER = logging.getLogger(__name__)

GOVEE_SERVICE_UUID = "00010203-0405-0607-0809-0a0b0c0d1910"
GOVEE_CHARACTERISTIC_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"

FRAME_LENGTH = 20
STATUS_FRAME = build_frame(0x01, opcode=0xAA)

NotificationCallback = Callable[[bytes], None]


class GoveeBleError(Exception):
    """The BLE GATT link could not connect, subscribe, or write."""


async def _async_ble_device(hass: Any, address: str) -> Any:
    """Resolve a connectable ``BLEDevice`` from Home Assistant's scanner.

    Kept as a module-level function so tests can replace it without importing
    Home Assistant's Bluetooth component.
    """
    try:
        from homeassistant.components.bluetooth import (  # noqa: PLC0415
            async_ble_device_from_address,
        )
    except Exception as err:  # Bluetooth integration unavailable
        raise GoveeBleError("Home Assistant Bluetooth is not available") from err

    try:
        device = async_ble_device_from_address(hass, address, connectable=True)
    except Exception as err:
        raise GoveeBleError(f"Unable to resolve Bluetooth address {address}: {err}") from err
    if device is None:
        raise GoveeBleError(f"No Bluetooth device found for {address}")
    return device


async def _async_establish(
    device: Any,
    name: str,
    disconnected_callback: Callable[[Any], None],
) -> Any:
    """Open a Bleak client through Home Assistant's retrying connector."""
    try:
        from bleak_retry_connector import (  # noqa: PLC0415
            BleakClientWithServiceCache,
            establish_connection,
        )
    except Exception as err:  # pragma: no cover - HA always provides this
        raise GoveeBleError("bleak-retry-connector is not available") from err

    try:
        return await establish_connection(
            BleakClientWithServiceCache,
            device,
            name,
            disconnected_callback=disconnected_callback,
            use_services_cache=True,
        )
    except Exception as err:
        raise GoveeBleError(f"Could not connect to {name}: {err}") from err


class GoveeBle:
    """One lazy GATT connection to one Govee device."""

    def __init__(
        self,
        hass: Any,
        address: str,
        name: str,
        on_notification: NotificationCallback,
    ) -> None:
        self.hass = hass
        self.address = address.strip().upper()
        self.name = name
        self._on_notification = on_notification
        self._client: Any | None = None
        self._characteristic: Any | None = None
        self._connect_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Return whether the underlying Bleak client is still connected."""
        client = self._client
        return bool(client is not None and getattr(client, "is_connected", False))

    async def async_connect(self) -> None:
        """Connect and subscribe to Govee notifications, if not already open."""
        if self.connected:
            return
        async with self._connect_lock:
            if self.connected:
                return
            if self._client is not None:
                stale = self._client
                stale_characteristic = self._characteristic
                self._client = None
                self._characteristic = None
                await self._async_close(
                    stale,
                    stop_notify=True,
                    characteristic=stale_characteristic,
                )
            device = await _async_ble_device(self.hass, self.address)
            client = await _async_establish(device, self.name, self._handle_disconnect)
            try:
                characteristic = await self._async_prepare(client)
            except Exception as err:
                await self._async_close(client, stop_notify=False)
                raise GoveeBleError(f"Could not subscribe to {self.name}: {err}") from err
            self._client = client
            self._characteristic = characteristic
            _LOGGER.debug("Connected to %s (%s) over BLE", self.name, self.address)

    async def async_send_frames(self, frames: Iterable[bytes]) -> None:
        """Write one or more complete 20-byte frames."""
        payloads = [bytes(frame) for frame in frames]
        if not payloads:
            return
        for frame in payloads:
            if len(frame) != FRAME_LENGTH:
                raise GoveeBleError(
                    f"Refusing to send a {len(frame)}-byte frame to {self.name}; "
                    "expected a 20-byte BLE frame"
                )

        async with self._send_lock:
            await self.async_connect()
            client = self._client
            characteristic = self._characteristic
            if client is None or characteristic is None:
                raise GoveeBleError(f"BLE link to {self.name} is not ready")
            for frame in payloads:
                try:
                    # Govee's vendor characteristic uses an acknowledged write.
                    await client.write_gatt_char(characteristic, frame, response=True)
                except Exception as err:
                    _LOGGER.debug(
                        "BLE write failed for %s (%s): %s",
                        self.name,
                        self.address,
                        err,
                    )
                    await self._async_disconnect()
                    raise GoveeBleError(f"BLE write failed for {self.name}: {err}") from err

    async def async_request_status(self) -> None:
        """Send the documented ``AA 01`` heart/status read frame."""
        await self.async_send_frames([STATUS_FRAME])

    async def async_stop(self) -> None:
        """Disconnect and stop notifications."""
        async with self._connect_lock:
            client = self._client
            characteristic = self._characteristic
            self._client = None
            self._characteristic = None
        if client is not None:
            await self._async_close(client, stop_notify=True, characteristic=characteristic)

    async def _async_prepare(self, client: Any) -> Any:
        """Find the Govee vendor service/characteristic and subscribe."""
        services = getattr(client, "services", None)
        if services is None:
            get_services = getattr(client, "get_services", None)
            if get_services is not None:
                services = await get_services()
        if services is None:
            raise GoveeBleError("The BLE client did not expose GATT services")

        get_service = getattr(services, "get_service", None)
        service = get_service(GOVEE_SERVICE_UUID) if get_service is not None else None
        characteristic = None
        if service is not None:
            characteristic = service.get_characteristic(GOVEE_CHARACTERISTIC_UUID)
        if characteristic is None:
            # A few devices expose the vendor characteristic without the
            # advertised service UUID; scan the discovered services for it.
            for candidate in services:
                characteristic = candidate.get_characteristic(GOVEE_CHARACTERISTIC_UUID)
                if characteristic is not None:
                    break
        if characteristic is None:
            raise GoveeBleError(
                f"Govee GATT characteristic {GOVEE_CHARACTERISTIC_UUID} was not found"
            )

        await client.start_notify(characteristic, self._handle_notification)
        return characteristic

    def _handle_notification(self, _sender: Any, data: bytearray) -> None:
        """Forward one notification to the transport callback."""
        try:
            frame = bytes(data)
        except TypeError, ValueError:
            return
        if not frame:
            return
        _LOGGER.debug(
            "BLE notification from %s (%s): %s",
            self.name,
            self.address,
            frame.hex(" "),
        )
        try:
            self._on_notification(frame)
        except Exception:
            _LOGGER.debug("BLE notification callback failed for %s", self.name, exc_info=True)

    def _handle_disconnect(self, client: Any) -> None:
        """Record an unexpected disconnect without tearing down a newer client."""
        if self._client is client:
            self._client = None
            self._characteristic = None
        _LOGGER.debug("Disconnected from %s (%s) over BLE", self.name, self.address)

    async def _async_disconnect(self) -> None:
        client = self._client
        characteristic = self._characteristic
        self._client = None
        self._characteristic = None
        if client is not None:
            await self._async_close(client, stop_notify=True, characteristic=characteristic)

    async def _async_close(
        self,
        client: Any,
        *,
        stop_notify: bool,
        characteristic: Any | None = None,
    ) -> None:
        """Close a client, logging rather than propagating cleanup failures."""
        if stop_notify and characteristic is not None:
            stop_notify_call = getattr(client, "stop_notify", None)
            if stop_notify_call is not None:
                try:
                    await stop_notify_call(characteristic)
                except Exception as err:
                    _LOGGER.debug("BLE stop_notify failed for %s: %s", self.name, err)
        disconnect = getattr(client, "disconnect", None)
        if disconnect is not None:
            try:
                await disconnect()
            except Exception as err:
                _LOGGER.debug("BLE disconnect failed for %s: %s", self.name, err)
