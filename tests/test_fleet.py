"""Tests for cloud-to-fleet reconciliation."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.ultimate_govee.fleet import Fleet
from custom_components.ultimate_govee.models import DeviceState


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


def test_ble_address_is_read_from_cloud_settings() -> None:
    fleet = Fleet()

    fleet.reconcile([_raw("device-1", settings={"address": "aa:bb:cc:dd:ee:ff"})])

    device = fleet.get("device-1")
    assert device is not None
    assert device.ble_address == "AA:BB:CC:DD:EE:FF"


def test_ble_address_is_read_from_the_device_extension() -> None:
    raw = _raw("device-1")
    raw["deviceExt"]["bleAddress"] = "11:22:33:44:55:66"
    fleet = Fleet()

    fleet.reconcile([raw])

    device = fleet.get("device-1")
    assert device is not None
    assert device.ble_address == "11:22:33:44:55:66"


def test_ble_name_is_not_invented_as_an_address() -> None:
    fleet = Fleet()

    fleet.reconcile([_raw("device-1", settings={"bleName": "GVH6001_1234"})])

    device = fleet.get("device-1")
    assert device is not None
    assert device.ble_address is None


def test_ble_address_refreshes_with_cloud_metadata() -> None:
    fleet = Fleet()
    fleet.reconcile([_raw("device-1")])
    device = fleet.get("device-1")
    assert device is not None
    assert device.ble_address is None

    fleet.reconcile([_raw("device-1", settings={"bleAddress": "AA:BB:CC:DD:EE:FF"})])

    assert device.ble_address == "AA:BB:CC:DD:EE:FF"


def test_profile_is_fixed_for_the_entry_lifetime() -> None:
    fleet = Fleet()
    fleet.reconcile([_raw("device-1", sku="H6002")])
    device = fleet.get("device-1")
    assert device is not None
    profile = device.profile

    fleet.reconcile([_raw("device-1", sku="H7120")])

    assert device.profile is profile


def test_observe_lan_notifies_once_and_records_the_endpoint() -> None:
    fleet = Fleet()
    fleet.reconcile([_raw("device-1")])
    calls: list[int] = []
    fleet.add_listener(lambda: calls.append(1))

    assert fleet.observe_lan("device-1", "192.168.1.20", 5.0) is True
    assert fleet.observe_lan("device-1", "192.168.1.20", 5.0) is False

    device = fleet.get("device-1")
    assert device is not None
    assert device.lan_ip == "192.168.1.20"
    assert device.lan_last_seen == 5.0
    assert device.state.online is True
    assert calls == [1]


def test_apply_report_notifies_once_for_state_and_endpoint() -> None:
    fleet = Fleet()
    fleet.reconcile([_raw("device-1")])
    calls: list[int] = []
    fleet.add_listener(lambda: calls.append(1))

    changed = fleet.apply_report(
        "device-1",
        DeviceState(power=True, brightness=40),
        ip="192.168.1.20",
        seen_at=6.0,
    )

    device = fleet.get("device-1")
    assert changed is True
    assert calls == [1]
    assert device is not None
    assert device.lan_ip == "192.168.1.20"
    assert device.state.online is True
    assert device.state.power is True
    assert device.state.brightness == 40


def test_mark_lan_failed_notifies_endpoint_loss() -> None:
    fleet = Fleet()
    fleet.reconcile([_raw("device-1")])
    device = fleet.get("device-1")
    assert device is not None
    fleet.observe_lan("device-1", "192.168.1.20", 5.0)
    calls: list[int] = []
    fleet.add_listener(lambda: calls.append(1))

    assert fleet.mark_lan_failed("device-1") is True
    assert fleet.mark_lan_failed("device-1") is False

    assert device.lan_ip is None
    assert device.lan_last_seen == 0.0
    assert calls == [1]


def test_refresh_notifies_once_for_multiple_transitions() -> None:
    fleet = Fleet()
    fleet.reconcile([_raw("device-1")])
    calls: list[int] = []
    fleet.add_listener(lambda: calls.append(1))

    fleet.refresh([_raw("device-2")])

    first = fleet.get("device-1")
    assert first is not None
    assert first.state.online is False
    assert fleet.get("device-2") is not None
    assert calls == [1]


def test_refresh_commits_after_every_step_so_listeners_see_final_state() -> None:
    """A listener runs at the commit boundary, not between refresh steps."""
    fleet = Fleet()
    fleet.reconcile([_raw("device-1")])
    snapshots: list[tuple[set[str], bool | None]] = []

    def listener() -> None:
        snapshots.append(
            (
                set(fleet.by_id),
                fleet["device-1"].state.online,
            )
        )

    fleet.add_listener(listener)

    fleet.refresh([_raw("device-2")])

    assert snapshots == [({"device-1", "device-2"}, False)]


def test_no_op_mutations_do_not_commit_a_notification() -> None:
    fleet = Fleet()
    fleet.reconcile([_raw("device-1")])
    fleet.reconcile_seen({"device-1"})
    calls: list[int] = []
    fleet.add_listener(lambda: calls.append(1))

    fleet.reconcile([_raw("device-1")])
    fleet.reconcile_seen({"device-1"})
    assert fleet.apply_state("device-1", DeviceState(online=True)) is False

    assert calls == []


def test_a_change_recorded_outside_a_commit_block_is_rejected() -> None:
    """Recording a change is only meaningful inside the commit boundary."""
    fleet = Fleet()

    with pytest.raises(RuntimeError, match="outside a change block"):
        fleet._record()
