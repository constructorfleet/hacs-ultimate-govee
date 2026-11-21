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
    transports = coordinator.transport_status()
    return {
        "data": _redact(dict(entry.data)),
        "options": coordinator.govee_options.as_dict(),
        "transports": transports,
        "iot": {
            "enabled": coordinator.enable_iot,
            "connected": transports["cloud_mqtt"]["connected"],
        },
        "lan": {
            "enabled": coordinator.enable_lan,
        },
        "devices": [
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
                },
                "lan_ip": device.lan_ip,
                "state": _redact(asdict(device.state)),
                "settings": _redact(device.settings),
            }
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
