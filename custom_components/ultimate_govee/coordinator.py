"""Coordinator that owns the Govee transports and the device fleet."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.auth import GoveeAuth, GoveeAuthError
from .api.cloud import GoveeApiError, GoveeCloud
from .api.iot import GoveeIot
from .api.lan import GoveeLan
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_TOPIC,
    CONF_CLIENT_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DOMAIN,
)
from .effects import EffectsLibrary
from .fleet import Fleet
from .models import DeviceState, GoveeDevice
from .options import GoveeOptions
from .protocol.commands import WireCommand
from .protocol.state import decode_message
from .tap_to_runs import TapAction, TapToRun, parse_tap_to_runs
from .transport import (
    BleBroadcastTransport,
    BleGattTransport,
    CloudMqttTransport,
    CommandRouter,
    LanObservation,
    LanUdpTransport,
    LocalMqttTransport,
    StatusReport,
)

_LOGGER = logging.getLogger(__name__)

GoveeData = Mapping[str, GoveeDevice]


class GoveeCoordinator(DataUpdateCoordinator[GoveeData]):
    """Keep the device fleet, tokens and transports in sync."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        session: Any,
        cert_dir: Path,
    ) -> None:
        self.govee_options = GoveeOptions.from_entry(entry)
        self.poll_interval = self.govee_options.poll_interval
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=self.poll_interval),
            config_entry=entry,
        )
        self.enable_lan = self.govee_options.enable_lan
        self.enable_iot = self.govee_options.enable_iot
        self.enable_effects = self.govee_options.enable_effects
        self.enable_tap_to_runs = self.govee_options.enable_tap_to_runs
        self.ignored_devices = set(self.govee_options.ignored_devices)
        self.lan_scan_interval = self.govee_options.lan_scan_interval
        data = entry.data
        self.auth = GoveeAuth(
            session,
            email=data[CONF_EMAIL],
            password=data[CONF_PASSWORD],
            client_id=data.get(CONF_CLIENT_ID),
            access_token=data.get(CONF_ACCESS_TOKEN),
            refresh_token=data.get(CONF_REFRESH_TOKEN),
            expires_at=data.get(CONF_TOKEN_EXPIRES_AT),
            account_id=data.get(CONF_ACCOUNT_ID),
            account_topic=data.get(CONF_ACCOUNT_TOPIC),
        )
        self.cloud = GoveeCloud(session, self.auth)
        self.fleet = Fleet()
        self.effects_library = EffectsLibrary(self.cloud, enabled=self.enable_effects)
        self.tap_to_runs: list[TapToRun] | None = None
        self._cert_dir = cert_dir
        self._iot: GoveeIot | None = None
        self._lan: GoveeLan | None = None
        self._iot_started = False
        self._lan_started = False
        self.router = CommandRouter(
            (
                BleGattTransport(),
                BleBroadcastTransport(),
                LanUdpTransport(lambda: self._lan, enabled=self.enable_lan),
                LocalMqttTransport(),
                CloudMqttTransport(lambda: self._iot, enabled=self.enable_iot),
            )
        )
        self._last_lan_scan = 0.0

    @property
    def devices(self) -> Mapping[str, GoveeDevice]:
        """Return the current device fleet as a read-only mapping."""
        return self.fleet.by_id

    async def async_setup(self) -> None:
        """Log in and start the enabled transports."""
        await self.auth.ensure_valid()
        if self.enable_iot:
            await self._async_start_iot()
        if self.enable_lan:
            await self._async_start_lan()

    async def async_shutdown(self) -> None:
        """Stop the transports and flush tokens."""
        if self._iot is not None:
            await self._iot.async_stop()
            self._iot = None
        if self._lan is not None:
            await self._lan.async_stop()
            self._lan = None
        await super().async_shutdown()

    async def _async_update_data(self) -> GoveeData:
        try:
            await self.auth.ensure_valid()
            raw_devices = await self.cloud.get_devices()
        except GoveeAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (GoveeApiError, aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(str(err)) from err

        removed = self.fleet.prune(self.ignored_devices)
        if removed:
            _LOGGER.debug("Removed ignored devices from the fleet: %s", sorted(removed))
        seen = self.fleet.reconcile(raw_devices, ignored=self.ignored_devices)
        self.fleet.reconcile_seen(seen)

        await self._async_poll_devices()
        return self.fleet.by_id

    async def _async_poll_devices(self) -> None:
        now = time.monotonic()
        if (
            self.enable_lan
            and self._lan is not None
            and now - self._last_lan_scan >= self.lan_scan_interval
        ):
            self._last_lan_scan = now
            try:
                await self._lan.async_scan()
            except OSError as err:
                _LOGGER.debug("LAN scan failed: %s", err)

        for device in self.devices.values():
            try:
                await self.router.request_status(device)
            except (GoveeApiError, OSError) as err:
                _LOGGER.debug("Status request failed for %s: %s", device.name, err)

    async def _async_start_iot(self) -> None:
        if self._iot_started:
            return
        if not self.auth.account_topic:
            _LOGGER.warning("Govee did not return an account topic; skipping IoT transport")
            return
        try:
            certificate = await self.cloud.get_iot_certificate()
        except Exception as err:  # keep the LAN/polling paths alive
            _LOGGER.warning("Unable to obtain the Govee IoT certificate: %s", err)
            return
        iot = GoveeIot(
            account_id=self.auth.account_id or "",
            client_id=self.auth.client_id,
            account_topic=self.auth.account_topic or "",
            cert_dir=self._cert_dir,
            loop=self.hass.loop,
            on_message=self._handle_iot_message,
        )
        try:
            await iot.async_start(certificate)
        except Exception as err:  # keep the LAN/polling paths alive
            _LOGGER.warning("Unable to connect to Govee IoT: %s", err)
            return
        self._iot = iot
        self._iot_started = True

    async def _async_start_lan(self) -> None:
        if self._lan_started:
            return
        lan = GoveeLan(self.hass.loop, self._handle_lan_message)
        try:
            await lan.async_start()
        except Exception as err:  # keep cloud polling alive when LAN is unavailable
            _LOGGER.warning("Unable to start Govee LAN discovery: %s", err)
            return
        self._lan = lan
        self._lan_started = True

    def _handle_iot_message(self, payload: dict[str, Any]) -> None:
        device_id = str(payload.get("device") or "")
        self._handle_inbound(StatusReport(device_id, payload))

    def _handle_lan_message(
        self, device_id: str, command: str, data: dict[str, Any], ip: str
    ) -> None:
        if command == "devStatus":
            device = self.devices.get(device_id)
            if device is not None:
                device.observed_lan(ip, time.monotonic())
            self._handle_inbound(StatusReport(device_id, data))
        else:
            self._handle_inbound(LanObservation(device_id, ip, time.monotonic()))

    def _handle_inbound(self, event: StatusReport | LanObservation) -> None:
        device = self.devices.get(event.device_id)
        if device is None:
            return
        if isinstance(event, LanObservation):
            device.observed_lan(event.ip, event.seen_at)
            self.async_update_listeners()
            return
        decoded = decode_message(device.profile, dict(event.payload))
        if decoded.online is None:
            decoded.online = True
        self._apply_state(device, decoded)

    def _apply_state(self, device: GoveeDevice, state: DeviceState | Mapping[str, Any]) -> None:
        """Merge a decoded or optimistic state into the device."""
        if not isinstance(state, DeviceState):
            state = DeviceState.from_mapping(state)
        device.state.merge_from(state)
        self.async_update_listeners()

    async def async_send(
        self,
        device: GoveeDevice,
        command: WireCommand,
        *,
        optimistic: DeviceState | Mapping[str, Any] | None = None,
    ) -> None:
        """Send a command through the router's selected transport."""
        await self.router.send(device, command)
        if optimistic:
            self._apply_state(device, optimistic)

    def transport_status(self) -> dict[str, Any]:
        """Return the status of every configured transport."""
        return self.router.status()

    async def async_get_tap_to_runs(self) -> list[TapToRun]:
        """Fetch and cache the account's tap-to-runs."""
        if self.tap_to_runs is not None:
            return self.tap_to_runs
        if not self.enable_tap_to_runs:
            self.tap_to_runs = []
            return self.tap_to_runs
        components = await self.cloud.get_tap_to_runs()
        self.tap_to_runs = parse_tap_to_runs(components)
        return self.tap_to_runs

    async def async_run_tap_to_run(self, tap_to_run: TapToRun) -> None:
        """Publish every action in a tap-to-run to its device."""
        matched = 0
        sent = 0
        for action in tap_to_run.actions:
            device = self._resolve_tap_device(action)
            if device is None:
                _LOGGER.debug(
                    "Skipping tap-to-run %s action for %s (%s): no matching device",
                    tap_to_run.name,
                    action.device_name,
                    action.sku,
                )
                continue
            matched += 1
            command = WireCommand(
                cmd=action.command,
                data=dict(action.data),
                cmd_version=action.cmd_version,
                msg_type=action.msg_type,
            )
            try:
                await self.router.send(device, command)
            except GoveeApiError as err:
                _LOGGER.debug(
                    "Skipping tap-to-run %s action for %s: %s",
                    tap_to_run.name,
                    action.device_name,
                    err,
                )
                continue
            sent += 1
        if not sent:
            if matched:
                raise GoveeApiError(
                    f"No transport delivered the {tap_to_run.name} tap-to-run"
                )
            raise GoveeApiError(f"No devices matched the {tap_to_run.name} tap-to-run")

    def _resolve_tap_device(self, action: TapAction) -> GoveeDevice | None:
        if action.device_id:
            device = self.devices.get(action.device_id)
            if device is not None:
                return device
        candidates = [
            device
            for device in self.devices.values()
            if device.name == action.device_name and (not action.sku or device.sku == action.sku)
        ]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            candidates = [device for device in self.devices.values() if device.sku == action.sku]
        return candidates[0] if len(candidates) == 1 else None
