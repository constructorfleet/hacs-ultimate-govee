"""Tests for SKU classification."""

from __future__ import annotations

import pytest

from custom_components.ultimate_govee.profiles import (
    FEATURE_POWER,
    KIND_CEILING_FAN,
    KIND_FAN,
    KIND_HUMIDIFIER,
    KIND_LIGHT,
    KIND_PURIFIER,
    KIND_SWITCH,
    PRIORITY_FALLBACK,
    PRIORITY_PREFIX,
    PROFILE_REGISTRY,
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
    assert profile.family == "light_prefix"
    assert not profile.supports_color
    assert not profile.supports_color_temp
    assert profile.supports_brightness


def test_light_kelvin_range_override() -> None:
    profile = profile_for("H6001", properties={"colorTem": {"range": {"min": 2700, "max": 6500}}})

    assert profile.family == "light_prefix"
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
    assert profile.features == frozenset({FEATURE_POWER})
    assert profile.family == "generic"


def test_sensor_keys() -> None:
    assert sensor_keys(profile_for("H5106")) == ("temperature", "humidity", "battery")


def test_binary_sensor_keys() -> None:
    assert binary_sensor_keys(profile_for("H5054")) == ("leak",)


def test_registry_priorities_are_explicit_and_unique() -> None:
    priorities = [spec.priority for spec in PROFILE_REGISTRY]
    names = [spec.name for spec in PROFILE_REGISTRY]

    assert priorities == sorted(priorities)
    assert len(set(priorities)) == len(priorities)
    assert len(set(names)) == len(names)
    assert names[-2:] == ["light_prefix", "generic"]
    assert priorities[-2] == PRIORITY_PREFIX
    assert priorities[-1] == PRIORITY_FALLBACK


def test_exact_model_rules_precede_prefix_rules() -> None:
    priorities = {spec.name: spec.priority for spec in PROFILE_REGISTRY}

    assert priorities["ceiling_fan"] < priorities["light_prefix"]
    assert priorities["tv"] < priorities["light_prefix"]
    assert priorities["switch_single"] < priorities["light_prefix"]
    # Two exact-model lists overlap, so their relative order is explicit too.
    assert priorities["ceiling_fan"] < priorities["fan"]


@pytest.mark.parametrize(
    ("sku", "family", "kind"),
    [
        ("H1310", "ceiling_fan", KIND_CEILING_FAN),
        ("R1310", "ceiling_fan", KIND_CEILING_FAN),
        ("H1161", "tv", "tv"),
        ("H1162", "tv", "tv"),
        ("H1163", "tv", "tv"),
        ("H1167", "tv", "tv"),
        ("H1168", "tv", "tv"),
        ("H7014", "switch_single", KIND_SWITCH),
    ],
)
def test_known_prefix_collisions_resolve_to_exact_models(sku: str, family: str, kind: str) -> None:
    profile = profile_for(sku)

    assert profile.family == family
    assert profile.kind == kind


@pytest.mark.parametrize(
    ("sku", "family", "kind", "fan_speeds", "gang_count", "modes", "ice_sizes", "features"),
    [
        (
            "H1310",
            "ceiling_fan",
            KIND_CEILING_FAN,
            6,
            1,
            (),
            (),
            {"power", "fan", "brightness", "color", "color_temp"},
        ),
        (
            "H1370",
            "ceiling_fan",
            KIND_CEILING_FAN,
            12,
            1,
            (),
            (),
            {"power", "fan", "brightness", "color", "color_temp"},
        ),
        ("H7100", "fan", KIND_FAN, 8, 1, (), (), {"power", "fan", "oscillation"}),
        (
            "H7105",
            "fan",
            KIND_FAN,
            8,
            1,
            (),
            (),
            {"power", "fan", "oscillation", "night_light"},
        ),
        (
            "H7130",
            "heater1",
            "heater",
            3,
            1,
            ("low", "medium", "high"),
            (),
            {
                "power",
                "target_temperature",
                "temperature",
                "fan",
                "mode",
                "lock",
                "oscillation",
            },
        ),
        (
            "H7131",
            "heater2",
            "heater",
            4,
            1,
            ("fan-only", "low", "medium", "high"),
            (),
            {
                "power",
                "target_temperature",
                "temperature",
                "fan",
                "mode",
                "night_light",
                "lock",
                "oscillation",
            },
        ),
        (
            "H7140",
            "humidifier",
            KIND_HUMIDIFIER,
            8,
            1,
            (),
            (),
            {"power", "water_tank", "night_light"},
        ),
        (
            "H7141",
            "humidifier",
            KIND_HUMIDIFIER,
            8,
            1,
            ("manual", "auto", "program"),
            (),
            {"power", "target_humidity", "humidity", "mode", "water_tank"},
        ),
        (
            "H7142",
            "humidifier",
            KIND_HUMIDIFIER,
            9,
            1,
            ("manual", "auto", "program"),
            (),
            {
                "power",
                "target_humidity",
                "humidity",
                "mode",
                "water_tank",
                "night_light",
                "uv",
            },
        ),
        (
            "H7122",
            "purifier_3a",
            KIND_PURIFIER,
            5,
            1,
            ("sleep", "low", "medium", "high", "auto"),
            (),
            {"power", "fan", "filter", "display", "lock", "night_light", "mode", "pm25"},
        ),
        (
            "H7120",
            "purifier_h7120",
            KIND_PURIFIER,
            4,
            1,
            ("sleep", "low", "medium", "high"),
            (),
            {"power", "fan", "filter", "display", "lock", "night_light", "mode"},
        ),
        (
            "H7126",
            "purifier_h7126",
            KIND_PURIFIER,
            3,
            1,
            ("sleep", "low", "high"),
            (),
            {"power", "fan", "filter", "display", "lock", "night_light", "mode"},
        ),
        (
            "H7150",
            "dehumidifier",
            "dehumidifier",
            8,
            1,
            ("low", "medium", "high", "auto"),
            (),
            {
                "power",
                "target_humidity",
                "humidity",
                "temperature",
                "fan",
                "mode",
                "water_tank",
            },
        ),
        ("H7161", "diffuser", "diffuser", 0, 1, (), (), {"power"}),
        (
            "H7172",
            "ice_maker",
            "ice_maker",
            0,
            1,
            (),
            ("small", "medium", "large"),
            {"power", "ice_size"},
        ),
        ("H8120", "ice_maker", "ice_maker", 0, 1, (), (), {"power"}),
        (
            "H7170",
            "kettle",
            "kettle",
            0,
            1,
            ("custom", "green_tea", "oolong_tea", "coffee", "black_tea"),
            (),
            {"power", "temperature", "mode"},
        ),
        ("H7184", "composter", "composter", 0, 1, (), (), {"power"}),
        (
            "H1161",
            "tv",
            "tv",
            0,
            1,
            (),
            (),
            {"power", "brightness", "color", "color_temp"},
        ),
        ("H5080", "switch_single", KIND_SWITCH, 0, 1, (), (), {"power"}),
        ("H5082", "switch_double", KIND_SWITCH, 0, 2, (), (), {"power"}),
        ("H5160", "switch_triple", KIND_SWITCH, 0, 3, (), (), {"power"}),
        ("H5054", "leak_sensor", "leak", 0, 1, (), (), {"battery", "leak"}),
        (
            "H5051",
            "thermo_sensor",
            "thermo",
            0,
            1,
            (),
            (),
            {"temperature", "humidity", "battery"},
        ),
        ("H5122", "unknown_sensor", "unknown", 0, 1, (), (), {"battery"}),
        (
            "H6001",
            "light_prefix",
            KIND_LIGHT,
            0,
            1,
            (),
            (),
            {"power", "brightness", "color", "color_temp"},
        ),
    ],
)
def test_representative_profiles_are_unchanged(
    *,
    sku: str,
    family: str,
    kind: str,
    fan_speeds: int,
    gang_count: int,
    modes: tuple[str, ...],
    ice_sizes: tuple[str, ...],
    features: set[str],
) -> None:
    profile = profile_for(sku)

    assert profile.family == family
    assert profile.kind == kind
    assert profile.fan_speeds == fan_speeds
    assert profile.gang_count == gang_count
    assert profile.modes == modes
    assert profile.ice_sizes == ice_sizes
    assert profile.features == features
