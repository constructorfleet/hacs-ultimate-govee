"""Tests for cloud-to-fleet reconciliation."""

from __future__ import annotations

from typing import Any

from custom_components.ultimate_govee.fleet import Fleet


def _raw(
    device_id: str,
    *,
    sku: str = "H6002",
    name: str = "Lamp",
    topic: str | None = None,
    last: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    device_settings = {
        "topic": topic or f"topic/{device_id}",
        "versionSoft": "1.0.0",
        "versionHard": "1.0.0",
    }
    device_settings.update(settings or {})
    return {
        "device": device_id,
        "sku": sku,
        "deviceName": name,
        "deviceExt": {
            "deviceSettings": device_settings,
            "lastDeviceData": last or {"online": 1},
        },
    }


def test_reconcile_builds_a_device_from_cloud_fields() -> None:
    fleet = Fleet()

    fleet.reconcile([_raw("device-1", last={"online": 1, "isOnOff": 1, "brightness": 127})])

    device = fleet.get("device-1")
    assert device is not None
    assert device.name == "Lamp"
    assert device.iot_topic == "topic/device-1"
    assert device.profile.model_name
    assert device.state.online is True
    assert device.state.power is True
    assert device.state.brightness == 50


def test_refresh_reuses_devices_and_replaces_the_mapping() -> None:
    fleet = Fleet()
    fleet.reconcile([_raw("device-1")])
    device = fleet.get("device-1")
    previous_view = fleet.by_id

    fleet.reconcile([_raw("device-1", name="Renamed")])

    assert fleet.get("device-1") is device
    assert device is not None and device.name == "Renamed"
    assert fleet.by_id is not previous_view
    assert previous_view["device-1"] is device


def test_absent_device_is_retained_until_seen_reconciles_it() -> None:
    fleet = Fleet()
    fleet.reconcile([_raw("device-1")])
    device = fleet.get("device-1")
    assert device is not None

    fleet.reconcile([])
    assert fleet.get("device-1") is device
    assert device.state.online is True

    fleet.reconcile_seen(set())
    assert device.state.online is False


def test_absent_lan_device_stays_available() -> None:
    fleet = Fleet()
    fleet.reconcile([_raw("device-1")])
    device = fleet.get("device-1")
    assert device is not None
    device.lan_ip = "192.168.1.20"

    fleet.reconcile([])
    fleet.reconcile_seen(set())

    assert device.state.online is True


def test_prune_removes_ignored_devices() -> None:
    fleet = Fleet()
    fleet.reconcile([_raw("device-1"), _raw("device-2")])

    removed = fleet.prune({"device-2"})

    assert removed == {"device-2"}
    assert fleet.get("device-2") is None
    assert fleet.get("device-1") is not None


def test_reconcile_skips_ignored_devices() -> None:
    fleet = Fleet()

    fleet.reconcile([_raw("device-1"), _raw("device-2")], ignored={"device-2"})

    assert fleet.get("device-1") is not None
    assert fleet.get("device-2") is None


def test_profile_is_fixed_for_the_entry_lifetime() -> None:
    fleet = Fleet()
    fleet.reconcile([_raw("device-1", sku="H6002")])
    device = fleet.get("device-1")
    assert device is not None
    profile = device.profile

    fleet.reconcile([_raw("device-1", sku="H7120")])

    assert device.profile is profile
