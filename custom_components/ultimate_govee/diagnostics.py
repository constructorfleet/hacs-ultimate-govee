"""Diagnostics support for Ultimate Govee."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_TOPIC,
    CONF_CLIENT_ID,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
)
from .coordinator import GoveeCoordinator
from .transport import TransportKind

REDACTED_KEYS = {
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_TOPIC,
    CONF_CLIENT_ID,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    "wifiMac",
    "wifiName",
    "bleName",
    "bleAddress",
    "ble_address",
    "address",
    "topic",
    "p12",
    "p12Pass",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: GoveeCoordinator = entry.runtime_data
    statuses = coordinator.transport_statuses()
    iot = statuses.get(TransportKind.CLOUD_MQTT.value)
    lan = statuses.get(TransportKind.LAN_UDP.value)
    return {
        "data": _redact(dict(entry.data)),
        "options": coordinator.govee_options.as_dict(),
        "transports": {kind: record.as_dict() for kind, record in statuses.items()},
        "iot": {
            "enabled": bool(iot and iot.enabled),
            "connected": bool(iot and iot.connected),
        },
        "lan": {
            "enabled": bool(lan and lan.enabled),
        },
        "devices": [
            _redact(
                {
                    "device_id": device.device_id,
                    "sku": device.sku,
                    "name": device.name,
                    "firmware": device.firmware,
                    "hardware": device.hardware,
                    "profile": {
                        "kind": device.profile.kind,
                        "features": sorted(device.profile.features),
                        "model_name": device.profile.model_name,
                        "dialect": device.profile.dialect,
                        "evidence": device.profile.evidence,
                    },
                    "lan_ip": device.lan_ip,
                    "ble_address": device.ble_address,
                    "state": asdict(device.state),
                    "settings": device.settings,
                }
            )
            for device in coordinator.devices.values()
        ],
    }


def _redact(data: Any) -> Any:
    """Recursively remove credentials and identifiers."""
    if isinstance(data, dict):
        return {
            key: "**REDACTED**" if key in REDACTED_KEYS else _redact(value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_redact(value) for value in data]
    if isinstance(data, tuple):
        return tuple(_redact(value) for value in data)
    return data
