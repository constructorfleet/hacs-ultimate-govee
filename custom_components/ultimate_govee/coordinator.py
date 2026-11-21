"""Coordinator that owns the Govee transports and the device fleet."""

from __future__ import annotations

import json
import logging
import time
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
    CONF_ENABLE_EFFECTS,
    CONF_ENABLE_IOT,
    CONF_ENABLE_LAN,
    CONF_ENABLE_TAP_TO_RUNS,
    CONF_IGNORED_DEVICES,
    CONF_LAN_SCAN_INTERVAL,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_ENABLE_EFFECTS,
    DEFAULT_ENABLE_IOT,
    DEFAULT_ENABLE_LAN,
    DEFAULT_ENABLE_TAP_TO_RUNS,
    DEFAULT_LAN_SCAN_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)
from .models import DeviceState, GoveeDevice
from .profiles import DeviceProfile, profile_for
from .protocol.commands import WireCommand
from .protocol.state import decode_message
from .tap_to_runs import TapAction, TapToRun, parse_tap_to_runs

_LOGGER = logging.getLogger(__name__)

GoveeData = dict[str, GoveeDevice]


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
        options = entry.options
        self.poll_interval = int(options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=self.poll_interval),
            config_entry=entry,
        )
        self.enable_lan = bool(options.get(CONF_ENABLE_LAN, DEFAULT_ENABLE_LAN))
        self.enable_iot = bool(options.get(CONF_ENABLE_IOT, DEFAULT_ENABLE_IOT))
        self.enable_effects = bool(options.get(CONF_ENABLE_EFFECTS, DEFAULT_ENABLE_EFFECTS))
        self.enable_tap_to_runs = bool(
            options.get(CONF_ENABLE_TAP_TO_RUNS, DEFAULT_ENABLE_TAP_TO_RUNS)
        )
        ignored = options.get(CONF_IGNORED_DEVICES, [])
        self.ignored_devices = {
            str(device_id) for device_id in ignored if isinstance(device_id, str)
        }
        self.lan_scan_interval = int(options.get(CONF_LAN_SCAN_INTERVAL, DEFAULT_LAN_SCAN_INTERVAL))
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
        self.devices: GoveeData = {}
        self.effects: dict[str, list[dict[str, Any]]] = {}
        self.tap_to_runs: list[TapToRun] | None = None
        self._cert_dir = cert_dir
        self._iot: GoveeIot | None = None
        self._lan: GoveeLan | None = None
        self._iot_started = False
        self._lan_started = False
        self._last_lan_scan = 0.0

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

        devices = self.devices
        for device_id in list(devices):
            if device_id in self.ignored_devices:
                del devices[device_id]
        seen: set[str] = set()
        for raw in raw_devices:
            device_id = str(raw.get("device") or "")
            if not device_id or device_id in self.ignored_devices:
                continue
            seen.add(device_id)
            device = devices.get(device_id)
            if device is None:
                device = _build_device(device_id, raw)
                devices[device_id] = device
            else:
                _update_device_metadata(device, raw)

        for device_id, device in devices.items():
            if device_id not in seen and not device.lan_reachable:
                device.state.online = False

        await self._async_poll_devices()
        self.devices = devices
        return devices

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
            if device.lan_ip is not None and self._lan is not None:
                try:
                    await self._lan.async_request_status(device.lan_ip)
                except OSError as err:
                    _LOGGER.debug("LAN status request failed for %s: %s", device.name, err)
                continue
            if (
                self.enable_iot
                and self._iot is not None
                and self._iot.connected
                and device.iot_topic
                and device.state.online
            ):
                self._iot.request_status(
                    device.iot_topic,
                    cmd_version=device.profile.status_cmd_version,
                )

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
        device = self.devices.get(device_id)
        if device is None:
            return
        decoded = decode_message(device.profile, payload)
        decoded.setdefault("online", True)
        self._apply_state(device, decoded)

    def _handle_lan_message(
        self, device_id: str, command: str, data: dict[str, Any], ip: str
    ) -> None:
        device = self.devices.get(device_id)
        if device is None:
            return
        device.lan_ip = ip
        device.lan_last_seen = time.monotonic()
        if command == "devStatus":
            decoded = decode_message(device.profile, data)
            decoded.setdefault("online", True)
            self._apply_state(device, decoded)
        else:
            self.async_update_listeners()

    def _apply_state(self, device: GoveeDevice, decoded: dict[str, Any]) -> None:
        device.state.update_from(decoded)
        device.state.online = True
        self.async_update_listeners()

    async def async_send(
        self,
        device: GoveeDevice,
        command: WireCommand,
        *,
        optimistic: dict[str, Any] | None = None,
    ) -> None:
        """Send a command over LAN when possible, otherwise AWS IoT."""
        sent = False
        if self.enable_lan and self._lan is not None and device.lan_ip:
            payload = command.lan_payload()
            if payload is not None:
                cmd, data = payload
                try:
                    await self._lan.async_send_command(device.lan_ip, cmd, data)
                    sent = True
                except OSError as err:
                    _LOGGER.debug("LAN command failed for %s: %s", device.name, err)
                    device.lan_ip = None

        if (
            not sent
            and self.enable_iot
            and self._iot is not None
            and self._iot.connected
            and device.iot_topic
        ):
            cmd, data = command.aws_payload()
            self._iot.send_command(
                device.iot_topic,
                cmd,
                data,
                cmd_version=0,
            )
            sent = True

        if not sent:
            raise GoveeApiError(f"No transport is available for {device.name}")

        if optimistic:
            self._apply_state(device, optimistic)

    async def async_get_effects(self, device: GoveeDevice) -> list[dict[str, Any]]:
        """Return and cache the effect library for a device."""
        if not self.enable_effects:
            return []
        cached = self.effects.get(device.sku)
        if cached is not None:
            return cached
        effects = await self.cloud.get_effects(
            device.sku,
            device=device.device_id,
        )
        self.effects[device.sku] = effects
        return effects

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
        if not self.enable_iot or self._iot is None or not self._iot.connected:
            raise GoveeApiError("Tap-to-runs require an active Govee IoT connection")
        sent = 0
        for action in tap_to_run.actions:
            device = self._resolve_tap_device(action)
            if device is None or not device.iot_topic:
                _LOGGER.debug(
                    "Skipping tap-to-run %s action for %s (%s): no matching device",
                    tap_to_run.name,
                    action.device_name,
                    action.sku,
                )
                continue
            self._iot.send_command(
                device.iot_topic,
                action.command,
                action.data,
                cmd_version=action.cmd_version,
                msg_type=action.msg_type,
            )
            sent += 1
        if not sent:
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


def _build_device(device_id: str, raw: dict[str, Any]) -> GoveeDevice:
    settings = _parse_json(raw.get("deviceExt", {}).get("deviceSettings"))
    last = _parse_json(raw.get("deviceExt", {}).get("lastDeviceData"))
    sku = str(raw.get("sku") or settings.get("sku") or "").upper()
    profile: DeviceProfile = profile_for(
        sku,
        raw.get("supportCmds") if isinstance(raw.get("supportCmds"), list) else None,
        raw.get("properties") if isinstance(raw.get("properties"), dict) else None,
    )
    device = GoveeDevice(
        device_id=device_id,
        sku=sku,
        name=str(raw.get("deviceName") or settings.get("deviceName") or device_id),
        iot_topic=settings.get("topic"),
        firmware=settings.get("versionSoft"),
        hardware=settings.get("versionHard"),
        settings=settings,
        profile=profile,
        raw_settings=raw,
    )
    device.state = _initial_state(settings, last)
    return device


def _update_device_metadata(device: GoveeDevice, raw: dict[str, Any]) -> None:
    settings = _parse_json(raw.get("deviceExt", {}).get("deviceSettings"))
    if not settings:
        return
    device.settings = settings
    device.raw_settings = raw
    device.iot_topic = settings.get("topic") or device.iot_topic
    device.firmware = settings.get("versionSoft") or device.firmware
    device.hardware = settings.get("versionHard") or device.hardware
    device.name = str(raw.get("deviceName") or settings.get("deviceName") or device.name)


def _initial_state(settings: dict[str, Any], last: dict[str, Any]) -> DeviceState:
    state = DeviceState()
    online = _as_bool(last.get("online"))
    state.online = bool(online) if online is not None else True
    power = _as_bool(last.get("isOnOff"))
    if power is not None:
        state.power = power
    for key, source, target in (
        ("brightness", last, "brightness"),
        ("tem", last, "temperature"),
        ("hum", last, "humidity"),
        ("battery", settings, "battery"),
        ("filterLife", settings, "filter_life"),
    ):
        value = source.get(key)
        if isinstance(value, (int, float)):
            setattr(state, target, value)
    return state


def _parse_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "on", "yes"}:
            return True
        if lowered in {"0", "false", "off", "no"}:
            return False
    return None
