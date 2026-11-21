"""Normalized integration options for one Govee config entry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_ENABLE_EFFECTS,
    CONF_ENABLE_IOT,
    CONF_ENABLE_LAN,
    CONF_ENABLE_TAP_TO_RUNS,
    CONF_IGNORED_DEVICES,
    CONF_LAN_SCAN_INTERVAL,
    CONF_POLL_INTERVAL,
    DEFAULT_ENABLE_EFFECTS,
    DEFAULT_ENABLE_IOT,
    DEFAULT_ENABLE_LAN,
    DEFAULT_ENABLE_TAP_TO_RUNS,
    DEFAULT_LAN_SCAN_INTERVAL,
    DEFAULT_POLL_INTERVAL,
)


@dataclass(frozen=True, slots=True)
class GoveeOptions:
    """The options that shape polling, transports, and entities."""

    poll_interval: int
    lan_scan_interval: int
    enable_lan: bool
    enable_iot: bool
    enable_effects: bool
    enable_tap_to_runs: bool
    ignored_devices: frozenset[str]

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> GoveeOptions:
        """Build options from a config-entry options mapping."""
        ignored = mapping.get(CONF_IGNORED_DEVICES) or []
        return cls(
            poll_interval=int(mapping.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)),
            lan_scan_interval=int(mapping.get(CONF_LAN_SCAN_INTERVAL, DEFAULT_LAN_SCAN_INTERVAL)),
            enable_lan=bool(mapping.get(CONF_ENABLE_LAN, DEFAULT_ENABLE_LAN)),
            enable_iot=bool(mapping.get(CONF_ENABLE_IOT, DEFAULT_ENABLE_IOT)),
            enable_effects=bool(mapping.get(CONF_ENABLE_EFFECTS, DEFAULT_ENABLE_EFFECTS)),
            enable_tap_to_runs=bool(
                mapping.get(CONF_ENABLE_TAP_TO_RUNS, DEFAULT_ENABLE_TAP_TO_RUNS)
            ),
            ignored_devices=frozenset(
                str(device_id) for device_id in ignored if isinstance(device_id, str)
            ),
        )

    @classmethod
    def from_entry(cls, entry: ConfigEntry) -> GoveeOptions:
        """Build options from a config entry."""
        return cls.from_mapping(entry.options)

    def as_dict(self) -> dict[str, Any]:
        """Return the storage shape used by the options flow."""
        return {
            CONF_POLL_INTERVAL: self.poll_interval,
            CONF_LAN_SCAN_INTERVAL: self.lan_scan_interval,
            CONF_ENABLE_LAN: self.enable_lan,
            CONF_ENABLE_IOT: self.enable_iot,
            CONF_ENABLE_EFFECTS: self.enable_effects,
            CONF_ENABLE_TAP_TO_RUNS: self.enable_tap_to_runs,
            CONF_IGNORED_DEVICES: list(self.ignored_devices),
        }
