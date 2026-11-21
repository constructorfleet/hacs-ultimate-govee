"""Coordinator that wires the transport router to the device fleet."""

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
from .protocol.command import ACTION_CLOUD, Command
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
        self._fleet = Fleet()
        self._fleet.add_listener(self._handle_fleet_changed)
        self.effects_library = EffectsLibrary(self.cloud, enabled=self.enable_effects)
        self.tap_to_runs: list[TapToRun] | None = None
        self.router = CommandRouter(
            (
                BleGattTransport(self.hass, on_report=self._handle_inbound),
                BleBroadcastTransport(),
                LanUdpTransport(
                    self.hass.loop,
                    enabled=self.enable_lan,
                    on_event=self._handle_inbound,
                    on_endpoint_lost=self._handle_lan_endpoint_lost,
                ),
                LocalMqttTransport(),
                CloudMqttTransport(
                    enabled=self.enable_iot,
                    account_id=self.auth.account_id or "",
                    client_id=self.auth.client_id or "",
                    account_topic=self.auth.account_topic or "",
                    cert_dir=cert_dir,
                    loop=self.hass.loop,
                    certificate=self.cloud.get_iot_certificate,
                    on_event=self._handle_inbound,
                ),
            )
        )
        self._last_lan_scan = 0.0
        self._refreshing = False

    @property
    def fleet(self) -> Fleet:
        """Return the reconciled device fleet."""
        return self._fleet

    @fleet.setter
    def fleet(self, fleet: Fleet) -> None:
        """Replace the fleet and keep the coordinator's change hook attached."""
        if fleet is self._fleet:
            return
        self._fleet.remove_listener(self._handle_fleet_changed)
        self._fleet = fleet
        fleet.add_listener(self._handle_fleet_changed)

    @property
    def devices(self) -> Mapping[str, GoveeDevice]:
        """Return the current device fleet as a read-only mapping."""
        return self.fleet.by_id

    async def async_setup(self) -> None:
        """Log in and start every registered transport."""
        await self.auth.ensure_valid()
        await self.router.async_start()

    async def async_shutdown(self) -> None:
        """Stop every transport and flush tokens."""
        await self.router.async_stop()
        await super().async_shutdown()

    async def _async_update_data(self) -> GoveeData:
        self._refreshing = True
        try:
            try:
                await self.auth.ensure_valid()
                raw_devices = await self.cloud.get_devices()
            except GoveeAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except (GoveeApiError, aiohttp.ClientError, TimeoutError) as err:
                raise UpdateFailed(str(err)) from err

            self.fleet.refresh(raw_devices, ignored=self.ignored_devices)
            await self._async_poll_devices()
            return self.fleet.by_id
        finally:
            self._refreshing = False

    async def _async_poll_devices(self) -> None:
        now = time.monotonic()
        if self.enable_lan and now - self._last_lan_scan >= self.lan_scan_interval:
            self._last_lan_scan = now
            await self.router.async_scan()

        for device in self.devices.values():
            try:
                await self.router.request_status(device)
            except (GoveeApiError, OSError) as err:
                _LOGGER.debug("Status request failed for %s: %s", device.name, err)

    def _handle_inbound(self, event: StatusReport | LanObservation) -> None:
        """Apply one typed event reported by a transport."""
        device = self.fleet.get(event.device_id)
        if device is None:
            return
        if isinstance(event, LanObservation):
            self.fleet.observe_lan(event.device_id, event.ip, event.seen_at)
            return
        decoded = decode_message(device.profile, dict(event.payload))
        if decoded.online is None:
            decoded.online = True
        self.fleet.apply_report(
            event.device_id,
            decoded,
            ip=event.ip,
            seen_at=event.seen_at,
        )

    def _handle_fleet_changed(self) -> None:
        """Publish a fleet change to Home Assistant's entity listeners.

        The refresh cycle publishes its own result once, so a change made
        while reconciling must not notify a second time.
        """
        if self._refreshing:
            return
        self.async_update_listeners()

    def _handle_lan_endpoint_lost(self, device_id: str) -> None:
        """Forget a LAN endpoint the transport could not reach."""
        self.fleet.mark_lan_failed(device_id)

    def _apply_state(self, device: GoveeDevice, state: DeviceState | Mapping[str, Any]) -> None:
        """Merge a decoded or optimistic state into the device through the fleet."""
        self.fleet.apply_state(device.device_id, state)

    async def async_send(
        self,
        device: GoveeDevice,
        command: Command,
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
            # A tap-to-run is an account-defined action whose wire shape only
            # the cloud API defines. LAN and BLE decline it; the router falls
            # back only when a transport that claimed it did not send.
            command = Command(
                ACTION_CLOUD,
                {"command": action.command, "data": dict(action.data)},
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
                raise GoveeApiError(f"No transport delivered the {tap_to_run.name} tap-to-run")
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
