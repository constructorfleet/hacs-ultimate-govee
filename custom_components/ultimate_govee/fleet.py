"""Reconcile Govee cloud payloads into the active device fleet."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, ItemsView, Iterable, Iterator, Mapping, ValuesView
from contextlib import contextmanager
from types import MappingProxyType
from typing import Any

from .models import DeviceState, GoveeDevice
from .profiles import profile_for
from .protocol.state import decode_cloud_snapshot

_LOGGER = logging.getLogger(__name__)

# BLE addresses are MACs in Govee's cloud payloads. Accept the common separated
# and compact forms, plus a UUID for stacks/adapters that report one.
_BLE_ADDRESS_RE = re.compile(
    r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$"
    r"|^[0-9A-Fa-f]{12}$"
    r"|^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
_BLE_ADDRESS_FIELDS = ("bleAddress", "bleMac", "address")
# ``bleName`` is usually the advertised local name. Only trust it when the
# cloud value itself is an address.
_BLE_NAME_FIELDS = ("bleName",)


class Fleet:
    """The devices currently known to one config entry.

    The fleet owns device identity, observation and the cloud-to-device
    mapping. It never talks to Home Assistant, the cloud client, or a
    transport; the coordinator supplies raw cloud payloads, reports typed
    observations, and listens for changes.
    """

    def __init__(self, devices: Iterable[GoveeDevice] = ()) -> None:
        self._devices: dict[str, GoveeDevice] = {device.device_id: device for device in devices}
        self._view: Mapping[str, GoveeDevice] = MappingProxyType(self._devices)
        self._listeners: list[Callable[[], None]] = []
        self._change_depth = 0
        self._changed = False

    def add_listener(self, listener: Callable[[], None]) -> None:
        """Register a callback for any device change."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[], None]) -> None:
        """Stop notifying ``listener``."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    @contextmanager
    def _change(self) -> Iterator[None]:
        """Publish once when the outermost change block commits.

        Every mutator runs inside this block. ``refresh`` nests the blocks of
        its internal steps, so the listeners see one commit for the whole
        refresh instead of one per step.
        """
        self._change_depth += 1
        try:
            yield
        finally:
            self._change_depth -= 1
            if self._change_depth == 0 and self._changed:
                self._changed = False
                for listener in tuple(self._listeners):
                    listener()

    def _record(self) -> None:
        """Mark the current change block as having modified the fleet."""
        if self._change_depth == 0:
            raise RuntimeError("Fleet change recorded outside a change block")
        self._changed = True

    @property
    def by_id(self) -> Mapping[str, GoveeDevice]:
        """Return a read-only mapping of device id to device."""
        return self._view

    def __iter__(self) -> Iterator[GoveeDevice]:
        return iter(self._devices.values())

    def __len__(self) -> int:
        return len(self._devices)

    def __getitem__(self, device_id: str) -> GoveeDevice:
        return self._devices[device_id]

    def __contains__(self, device_id: object) -> bool:
        return device_id in self._devices

    def get(self, device_id: str) -> GoveeDevice | None:
        """Return one device, if it is in the fleet."""
        return self._devices.get(device_id)

    def values(self) -> ValuesView[GoveeDevice]:
        """Return the devices in the fleet."""
        return self._devices.values()

    def items(self) -> ItemsView[str, GoveeDevice]:
        """Return the device id/device pairs in the fleet."""
        return self._devices.items()

    def prune(self, ignored: Iterable[str]) -> set[str]:
        """Remove ignored devices and return the ids that were removed."""
        ignored_ids = {str(device_id) for device_id in ignored}
        removed = {device_id for device_id in self._devices if device_id in ignored_ids}
        if removed:
            with self._change():
                self._devices = {
                    device_id: device
                    for device_id, device in self._devices.items()
                    if device_id not in removed
                }
                self._view = MappingProxyType(self._devices)
                self._record()
        return removed

    def reconcile(
        self,
        raw_devices: Iterable[Mapping[str, Any]],
        *,
        ignored: Iterable[str] = (),
    ) -> set[str]:
        """Merge one cloud device listing into the fleet.

        Existing devices are reused by id, so entities and LAN observations
        survive a refresh. Devices missing from the cloud listing are retained
        until :meth:`reconcile_seen` decides whether they are still reachable.
        """
        ignored_ids = {str(device_id) for device_id in ignored}
        next_devices: dict[str, GoveeDevice] = {}
        seen: set[str] = set()
        changed = False

        with self._change():
            for raw in raw_devices:
                if not isinstance(raw, Mapping):
                    continue
                device_id = str(raw.get("device") or "")
                if not device_id or device_id in ignored_ids:
                    continue
                seen.add(device_id)
                device = self._devices.get(device_id)
                if device is None:
                    device = _build_device(device_id, dict(raw))
                    changed = True
                else:
                    changed = _update_device_metadata(device, dict(raw)) or changed
                next_devices[device_id] = device

            for device_id, device in self._devices.items():
                if device_id in ignored_ids:
                    continue
                next_devices.setdefault(device_id, device)

            self._devices = next_devices
            self._view = MappingProxyType(next_devices)
            if changed:
                self._record()
        return seen

    def refresh(
        self,
        raw_devices: Iterable[Mapping[str, Any]],
        *,
        ignored: Iterable[str] = (),
    ) -> set[str]:
        """Prune, reconcile and reconcile reachability as one commit.

        The coordinator uses this so one cloud refresh produces one listener
        notification instead of one per internal step.
        """
        with self._change():
            removed = self.prune(ignored)
            if removed:
                _LOGGER.debug("Removed ignored devices from the fleet: %s", sorted(removed))
            seen = self.reconcile(raw_devices, ignored=ignored)
            self.reconcile_seen(seen)
        return seen

    def reconcile_seen(self, seen: set[str]) -> None:
        """Mark devices absent from the cloud listing offline unless on LAN."""
        with self._change():
            changed = False
            for device_id, device in self._devices.items():
                if (
                    device_id not in seen
                    and not device.lan_reachable
                    and device.state.online is not False
                ):
                    device.state.online = False
                    changed = True
            if changed:
                self._record()

    def observe_lan(self, device_id: str, ip: str, seen_at: float) -> bool:
        """Record that ``device_id`` answered on the LAN."""
        device = self._devices.get(device_id)
        if device is None:
            return False
        with self._change():
            changed = _observe_lan(device, ip, seen_at)
            if changed:
                self._record()
        return changed

    def mark_lan_failed(self, device_id: str) -> bool:
        """Forget a LAN endpoint that did not accept a command."""
        device = self._devices.get(device_id)
        if device is None:
            return False
        if device.lan_ip is None and device.lan_last_seen == 0.0:
            return False
        with self._change():
            device.lan_ip = None
            device.lan_last_seen = 0.0
            self._record()
        return True

    def apply_state(self, device_id: str, state: DeviceState | Mapping[str, Any]) -> bool:
        """Merge a decoded or optimistic state into one device."""
        device = self._devices.get(device_id)
        if device is None:
            return False
        if not isinstance(state, DeviceState):
            state = DeviceState.from_mapping(state)
        with self._change():
            changed = device.state.merge_from(state)
            if changed:
                self._record()
        return changed

    def apply_report(
        self,
        device_id: str,
        state: DeviceState,
        *,
        ip: str | None = None,
        seen_at: float | None = None,
    ) -> bool:
        """Apply one report and its optional endpoint proof as one change."""
        device = self._devices.get(device_id)
        if device is None:
            return False
        with self._change():
            changed = False
            if ip is not None:
                changed = _observe_lan(device, ip, seen_at or 0.0)
            changed = device.state.merge_from(state) or changed
            if changed:
                self._record()
        return changed


def _observe_lan(device: GoveeDevice, ip: str, seen_at: float) -> bool:
    changed = (
        device.lan_ip != ip or device.lan_last_seen != seen_at or device.state.online is not True
    )
    device.lan_ip = ip
    device.lan_last_seen = seen_at
    device.state.online = True
    return changed


def _build_device(device_id: str, raw: dict[str, Any]) -> GoveeDevice:
    ext = raw.get("deviceExt")
    ext = ext if isinstance(ext, dict) else {}
    settings = _parse_json(ext.get("deviceSettings"))
    last = _parse_json(ext.get("lastDeviceData"))
    sku = str(raw.get("sku") or settings.get("sku") or "").upper()
    profile = profile_for(
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
        ble_address=_ble_address(raw, ext, settings, last),
        raw_settings=raw,
    )
    device.state = decode_cloud_snapshot(profile, settings, last)
    return device


def _update_device_metadata(device: GoveeDevice, raw: dict[str, Any]) -> bool:
    ext = raw.get("deviceExt")
    ext = ext if isinstance(ext, dict) else {}
    settings = _parse_json(ext.get("deviceSettings"))
    last = _parse_json(ext.get("lastDeviceData"))
    if not settings:
        return False
    if (
        device.raw_settings
        and not device.profile_inputs_warned
        and _profile_inputs_changed(device.raw_settings, raw)
    ):
        _LOGGER.warning(
            "Profile inputs changed for %s (%s); reload the integration to apply them",
            device.name,
            device.sku,
        )
        device.profile_inputs_warned = True
    previous = (
        device.settings,
        device.raw_settings,
        device.iot_topic,
        device.firmware,
        device.hardware,
        device.name,
        device.ble_address,
    )
    device.settings = settings
    device.raw_settings = raw
    device.iot_topic = settings.get("topic") or device.iot_topic
    device.firmware = settings.get("versionSoft") or device.firmware
    device.hardware = settings.get("versionHard") or device.hardware
    device.name = str(raw.get("deviceName") or settings.get("deviceName") or device.name)
    device.ble_address = _ble_address(raw, ext, settings, last) or device.ble_address
    current = (
        device.settings,
        device.raw_settings,
        device.iot_topic,
        device.firmware,
        device.hardware,
        device.name,
        device.ble_address,
    )
    return previous != current


def _ble_address(*sources: Any) -> str | None:
    """Return a real BLE address from the known cloud payload fields.

    Govee sometimes reports ``address`` in ``deviceSettings`` and sometimes as
    ``bleAddress`` on the device or its extension. ``bleName`` is normally an
    advertised name, so it is only accepted when it is itself address-shaped.
    The integration never invents an address when none is present.
    """
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for field in _BLE_ADDRESS_FIELDS:
            address = _normalise_ble_address(source.get(field))
            if address is not None:
                return address
        for field in _BLE_NAME_FIELDS:
            address = _normalise_ble_address(source.get(field))
            if address is not None:
                return address
    return None


def _normalise_ble_address(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    address = value.strip()
    if not address or _BLE_ADDRESS_RE.fullmatch(address) is None:
        return None
    return address.upper()


def _profile_inputs_changed(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    for key in ("supportCmds", "properties"):
        old = previous.get(key)
        new = current.get(key)
        if old is not None and new is not None and old != new:
            return True
    return False


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
