"""Reconcile Govee cloud payloads into the active device fleet."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import ItemsView, Iterable, Iterator, Mapping, ValuesView
from types import MappingProxyType
from typing import Any

from .models import GoveeDevice
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

    The fleet owns device identity and the cloud-to-device mapping. It never
    talks to Home Assistant, the cloud client, or a transport; the coordinator
    supplies raw cloud payloads and decides when to poll.
    """

    def __init__(self, devices: Iterable[GoveeDevice] = ()) -> None:
        self._devices: dict[str, GoveeDevice] = {device.device_id: device for device in devices}
        self._view: Mapping[str, GoveeDevice] = MappingProxyType(self._devices)

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
            self._devices = {
                device_id: device
                for device_id, device in self._devices.items()
                if device_id not in removed
            }
            self._view = MappingProxyType(self._devices)
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
            else:
                _update_device_metadata(device, dict(raw))
            next_devices[device_id] = device

        for device_id, device in self._devices.items():
            if device_id in ignored_ids:
                continue
            next_devices.setdefault(device_id, device)

        self._devices = next_devices
        self._view = MappingProxyType(next_devices)
        return seen

    def reconcile_seen(self, seen: set[str]) -> None:
        """Mark devices absent from the cloud listing offline unless on LAN."""
        for device_id, device in self._devices.items():
            if device_id not in seen and not device.lan_reachable:
                device.state.online = False


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


def _update_device_metadata(device: GoveeDevice, raw: dict[str, Any]) -> None:
    ext = raw.get("deviceExt")
    ext = ext if isinstance(ext, dict) else {}
    settings = _parse_json(ext.get("deviceSettings"))
    last = _parse_json(ext.get("lastDeviceData"))
    if not settings:
        return
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
    device.settings = settings
    device.raw_settings = raw
    device.iot_topic = settings.get("topic") or device.iot_topic
    device.firmware = settings.get("versionSoft") or device.firmware
    device.hardware = settings.get("versionHard") or device.hardware
    device.name = str(raw.get("deviceName") or settings.get("deviceName") or device.name)
    device.ble_address = _ble_address(raw, ext, settings, last) or device.ble_address


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
