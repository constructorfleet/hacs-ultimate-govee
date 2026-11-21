"""Tests for normalized integration options."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.ultimate_govee.const import (
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
from custom_components.ultimate_govee.options import GoveeOptions


def test_defaults_come_from_const() -> None:
    options = GoveeOptions.from_mapping({})

    assert options.poll_interval == DEFAULT_POLL_INTERVAL
    assert options.lan_scan_interval == DEFAULT_LAN_SCAN_INTERVAL
    assert options.enable_lan is DEFAULT_ENABLE_LAN
    assert options.enable_iot is DEFAULT_ENABLE_IOT
    assert options.enable_effects is DEFAULT_ENABLE_EFFECTS
    assert options.enable_tap_to_runs is DEFAULT_ENABLE_TAP_TO_RUNS
    assert options.ignored_devices == frozenset()


def test_from_mapping_preserves_legacy_coercions() -> None:
    options = GoveeOptions.from_mapping(
        {
            CONF_POLL_INTERVAL: "120",
            CONF_LAN_SCAN_INTERVAL: "90",
            CONF_ENABLE_LAN: 0,
            CONF_ENABLE_IOT: 1,
            CONF_ENABLE_EFFECTS: "",
            CONF_ENABLE_TAP_TO_RUNS: "yes",
        }
    )

    assert options.poll_interval == 120
    assert options.lan_scan_interval == 90
    assert options.enable_lan is False
    assert options.enable_iot is True
    assert options.enable_effects is False
    assert options.enable_tap_to_runs is True


def test_ignored_devices_keep_only_strings() -> None:
    options = GoveeOptions.from_mapping(
        {CONF_IGNORED_DEVICES: ["device-1", 42, None, "device-2"]}
    )

    assert options.ignored_devices == frozenset({"device-1", "device-2"})


def test_as_dict_round_trips() -> None:
    original = GoveeOptions.from_mapping(
        {
            CONF_POLL_INTERVAL: 30,
            CONF_IGNORED_DEVICES: ["device-1"],
        }
    )

    assert GoveeOptions.from_mapping(original.as_dict()) == original
    assert original.as_dict()[CONF_IGNORED_DEVICES] == ["device-1"]


def test_from_entry_reads_options() -> None:
    entry = SimpleNamespace(options={CONF_POLL_INTERVAL: 45})

    options = GoveeOptions.from_entry(entry)  # type: ignore[arg-type]

    assert options.poll_interval == 45


def test_ignored_devices_accepts_missing_or_none() -> None:
    options = GoveeOptions.from_mapping({CONF_IGNORED_DEVICES: None})

    assert options.ignored_devices == frozenset()
