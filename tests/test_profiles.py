"""Tests for SKU classification."""

from __future__ import annotations

from custom_components.ultimate_govee.profiles import (
    KIND_CEILING_FAN,
    KIND_FAN,
    KIND_HUMIDIFIER,
    KIND_LIGHT,
    KIND_PURIFIER,
    KIND_SWITCH,
    binary_sensor_keys,
    profile_for,
    sensor_keys,
)


def test_tower_fan() -> None:
    profile = profile_for("H7100")

    assert profile.kind == KIND_FAN
    assert profile.fan_speeds == 8


def test_ceiling_fan_speeds() -> None:
    assert profile_for("H1370").fan_speeds == 12
    assert profile_for("H1310").kind == KIND_CEILING_FAN


def test_light_gets_colour_and_temperature() -> None:
    profile = profile_for("H6001")

    assert profile.kind == KIND_LIGHT
    assert profile.supports_color
    assert profile.supports_color_temp


def test_cloud_capabilities_strip_unsupported_light_features() -> None:
    profile = profile_for("H6001", ["turn", "brightness"])

    assert profile.kind == KIND_LIGHT
    assert not profile.supports_color
    assert not profile.supports_color_temp
    assert profile.supports_brightness


def test_light_kelvin_range_override() -> None:
    profile = profile_for("H6001", properties={"colorTem": {"range": {"min": 2700, "max": 6500}}})

    assert profile.min_kelvin == 2700
    assert profile.max_kelvin == 6500


def test_switch_power_override() -> None:
    profile = profile_for("H5080")

    assert profile.kind == KIND_SWITCH
    assert (profile.power_on, profile.power_off) == (17, 16)


def test_multi_gang_switches() -> None:
    assert profile_for("H5082").gang_count == 2
    assert profile_for("H5160").gang_count == 3


def test_purifier_families() -> None:
    h7123 = profile_for("H7123")
    h7120 = profile_for("H7120")

    assert h7123.kind == KIND_PURIFIER
    assert h7123.fan_speeds == 5
    assert "auto" in h7123.modes
    assert h7120.fan_speeds == 4


def test_humidifier_features_are_model_specific() -> None:
    h7142 = profile_for("H7142")
    h7140 = profile_for("H7140")

    assert h7142.kind == KIND_HUMIDIFIER
    assert "uv" in h7142.features
    assert "uv" not in h7140.features
    assert h7142.fan_speeds == 9


def test_unknown_sku_falls_back_to_a_switch() -> None:
    profile = profile_for("H9999")

    assert profile.kind == KIND_SWITCH
    assert profile.features


def test_sensor_keys() -> None:
    assert sensor_keys(profile_for("H5106")) == ("temperature", "humidity", "battery")


def test_binary_sensor_keys() -> None:
    assert binary_sensor_keys(profile_for("H5054")) == ("leak",)
