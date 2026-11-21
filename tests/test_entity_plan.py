"""Tests for the entity plan that every platform consumes."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTemperature,
)

from custom_components.ultimate_govee.entity_plan import (
    ControlContext,
    EntitySpec,
    entities_for_platform,
    plan_entities,
)
from custom_components.ultimate_govee.models import DeviceState
from custom_components.ultimate_govee.profiles import (
    FEATURE_BASKET,
    FEATURE_POWER_METERING,
    profile_for,
    sensor_keys,
)
from custom_components.ultimate_govee.protocol import commands


def _keys(sku: str, platform: str) -> tuple[str, ...]:
    return tuple(spec.key for spec in entities_for_platform(profile_for(sku), platform))


def _spec(sku: str, platform: str, key: str) -> EntitySpec:
    return next(
        spec for spec in entities_for_platform(profile_for(sku), platform) if spec.key == key
    )


def test_entity_spec_is_frozen() -> None:
    spec = plan_entities(profile_for("H6001"))[0]

    with pytest.raises(FrozenInstanceError):
        spec.key = "other"  # type: ignore[misc]


def test_light_plan_is_one_light() -> None:
    assert [(spec.platform, spec.key) for spec in plan_entities(profile_for("H6001"))] == [
        ("light", "light")
    ]


def test_tower_fan_plan_has_fan_and_oscillation_switch() -> None:
    assert _keys("H7100", "fan") == ("fan",)
    assert _keys("H7100", "switch") == ("oscillation",)
    assert _spec("H7100", "switch", "oscillation").name == "Oscillation"


def test_fan_night_light_is_a_switch() -> None:
    assert _keys("H7105", "switch") == ("night_light", "oscillation")


def test_ceiling_fan_plan_has_only_a_fan() -> None:
    assert _keys("H1310", "fan") == ("fan",)
    assert _keys("H1310", "switch") == ()


def test_purifier_plan_has_fan_controls_and_filter_sensor() -> None:
    assert _keys("H7120", "fan") == ("fan",)
    assert _keys("H7120", "switch") == ("night_light", "display", "lock")
    assert _keys("H7120", "sensor") == ("filter_life",)
    assert _spec("H7120", "switch", "display").entity_category is EntityCategory.CONFIG
    assert _spec("H7120", "sensor", "filter_life").unit == PERCENTAGE


def test_purifier_readings_follow_the_profile() -> None:
    assert _keys("H7122", "sensor") == ("pm25", "filter_life")
    assert _spec("H7122", "sensor", "pm25").device_class is SensorDeviceClass.PM25

    air_quality = _spec("H7123", "sensor", "air_quality")
    assert air_quality.device_class is SensorDeviceClass.ENUM
    assert air_quality.options == ("excellent", "good", "moderate", "poor")


def test_humidifier_plan() -> None:
    assert _keys("H7142", "humidifier") == ("humidifier",)
    assert _keys("H7142", "switch") == ("night_light", "uv")
    assert _keys("H7142", "number") == ("night_light_brightness",)
    assert _keys("H7142", "sensor") == ("humidity",)
    assert _keys("H7142", "binary_sensor") == ("water_shortage",)

    brightness = _spec("H7142", "number", "night_light_brightness")
    assert (brightness.minimum, brightness.maximum, brightness.step) == (1, 100, 1)


def test_heater_plan() -> None:
    assert _keys("H7130", "switch") == ("power", "lock", "oscillation")
    assert _keys("H7130", "number") == ("target_temperature",)
    assert _keys("H7130", "select") == ("fan_speed",)
    assert _keys("H7130", "sensor") == ("temperature",)

    target = _spec("H7130", "number", "target_temperature")
    assert target.device_class is NumberDeviceClass.TEMPERATURE
    assert target.unit == UnitOfTemperature.CELSIUS
    assert (target.minimum, target.maximum, target.step) == (5, 30, 0.5)

    fan_speed = _spec("H7130", "select", "fan_speed")
    assert fan_speed.options == ("low", "medium", "high")

    assert _keys("H7131", "switch") == ("power", "night_light", "lock", "oscillation")


def test_ice_maker_plan() -> None:
    assert _keys("H7172", "switch") == ("power",)
    assert _keys("H7172", "select") == ("ice_size",)
    assert _keys("H7172", "binary_sensor") == ()

    ice_size = _spec("H7172", "select", "ice_size")
    assert ice_size.options == ("small", "medium", "large")

    assert _keys("H8120", "select") == ()


def test_h5086_power_metering_becomes_three_sensor_specs() -> None:
    profile = profile_for("H5086")

    assert FEATURE_POWER_METERING in profile.features
    assert sensor_keys(profile) == ("voltage", "current", "power_usage")
    assert _keys("H5086", "switch") == ("power",)
    assert _keys("H5086", "sensor") == ("voltage", "current", "power_usage")

    voltage = _spec("H5086", "sensor", "voltage")
    current = _spec("H5086", "sensor", "current")
    power = _spec("H5086", "sensor", "power_usage")
    assert (voltage.device_class, voltage.unit) == (
        SensorDeviceClass.VOLTAGE,
        UnitOfElectricPotential.VOLT,
    )
    assert (current.device_class, current.unit) == (
        SensorDeviceClass.CURRENT,
        UnitOfElectricCurrent.AMPERE,
    )
    assert (power.device_class, power.unit) == (
        SensorDeviceClass.POWER,
        UnitOfPower.WATT,
    )

    assert _keys("H5080", "sensor") == ()


def test_switch_gangs_expand_from_gang_count() -> None:
    assert _keys("H5080", "switch") == ("power",)
    assert _keys("H5082", "switch") == ("gang0", "gang1")
    assert _keys("H5160", "switch") == ("gang0", "gang1", "gang2")

    assert _spec("H5082", "switch", "gang0").name == "Gang 1"
    assert _spec("H5082", "switch", "gang1").name == "Gang 2"


def test_sensor_plan_metadata() -> None:
    assert _keys("H5106", "sensor") == ("temperature", "humidity", "battery")
    assert _keys("H5140", "sensor") == ("temperature", "humidity", "co2", "battery")

    temperature = _spec("H5106", "sensor", "temperature")
    assert temperature.name == "Temperature"
    assert temperature.state_key == "temperature"
    assert temperature.device_class is SensorDeviceClass.TEMPERATURE
    assert temperature.unit == UnitOfTemperature.CELSIUS
    assert temperature.state_class is SensorStateClass.MEASUREMENT


def test_binary_sensor_plan_metadata() -> None:
    assert _keys("H5054", "sensor") == ("battery",)
    assert _keys("H5054", "binary_sensor") == ("leak",)
    assert _spec("H5054", "binary_sensor", "leak").device_class is (
        BinarySensorDeviceClass.MOISTURE
    )

    presence = _spec("H5127", "binary_sensor", "presence")
    assert presence.name == "Presence"
    assert presence.device_class is BinarySensorDeviceClass.PRESENCE

    assert _keys("H5023", "binary_sensor") == ("contact",)


def test_basket_feature_selects_a_binary_sensor() -> None:
    profile = profile_for("H7172")
    profile = replace(profile, features=profile.features | {FEATURE_BASKET})

    specs = entities_for_platform(profile, "binary_sensor")

    assert tuple(spec.key for spec in specs) == ("basket_full",)


def test_unknown_sku_falls_back_to_a_power_switch() -> None:
    assert [(spec.platform, spec.key) for spec in plan_entities(profile_for("H9999"))] == [
        ("switch", "power")
    ]


@pytest.mark.parametrize(
    ("sku", "count"),
    [
        ("H6001", 1),
        ("H5080", 1),
        ("H5082", 2),
        ("H7100", 2),
        ("H1310", 1),
        ("H7120", 5),
        ("H7142", 6),
        ("H7130", 6),
        ("H7131", 7),
        ("H7172", 2),
        ("H5051", 3),
        ("H5106", 3),
        ("H5054", 2),
    ],
)
def test_plan_preserves_entity_counts_for_the_test_fleet(sku: str, count: int) -> None:
    assert len(plan_entities(profile_for(sku))) == count


def test_control_platform_specs_all_carry_a_builder() -> None:
    """Every controllable spec reads from the plan's control seam."""
    for sku in ("H5080", "H5082", "H7100", "H7120", "H7130", "H7142", "H7172"):
        profile = profile_for(sku)
        for platform in ("fan", "number", "select", "switch"):
            for spec in entities_for_platform(profile, platform):
                assert spec.control is not None, (sku, platform, spec.key)


def test_power_switch_control_matches_heater_builder() -> None:
    profile = profile_for("H7130")
    spec = _spec("H7130", "switch", "power")

    result = spec.control(ControlContext(profile, DeviceState(power=True), False))

    assert result.command == commands.heater_power(profile, False)
    assert result.optimistic == {"power": False}


def test_gang_switch_control_matches_gang_builder() -> None:
    profile = profile_for("H5082")
    spec = _spec("H5082", "switch", "gang1")
    state = DeviceState(gangs=(True, False))

    result = spec.control(ControlContext(profile, state, True))

    assert result.command == commands.gang_power(profile, 1, True)
    assert result.optimistic == {"gangs": (True, True), "power": True}


def test_feature_switch_controls_match_builders() -> None:
    purifier = profile_for("H7120")
    state = DeviceState(night_light_brightness=40, color=(1, 2, 3))

    night_light = _spec("H7120", "switch", "night_light")
    display = _spec("H7120", "switch", "display")

    assert night_light.control(ControlContext(purifier, state, True)).command == (
        commands.night_light(purifier, True, 40, (1, 2, 3))
    )
    assert display.control(ControlContext(purifier, state, True)).command == (
        commands.display(purifier, True)
    )


def test_number_controls_match_builders() -> None:
    heater = profile_for("H7130")
    target = _spec("H7130", "number", "target_temperature")

    result = target.control(ControlContext(heater, DeviceState(), 22.5))

    assert result.command == commands.heater_target(heater, 22.5)
    assert result.optimistic == {"target_temperature": 22.5}

    humidifier = profile_for("H7142")
    brightness = _spec("H7142", "number", "night_light_brightness")
    result = brightness.control(ControlContext(humidifier, DeviceState(), 30))

    assert result.command == commands.night_light(humidifier, True, 30, (255, 255, 255))
    assert result.optimistic == {"night_light_brightness": 30, "night_light": True}


def test_select_controls_match_builders() -> None:
    heater = profile_for("H7130")
    spec = _spec("H7130", "select", "fan_speed")

    result = spec.control(ControlContext(heater, DeviceState(), "high", options=spec.options))

    assert result.command == commands.heater_speed(heater, 3)
    assert result.optimistic == {"fan_speed": 3, "percentage": 100}

    ice = profile_for("H7172")
    ice_size = _spec("H7172", "select", "ice_size")
    result = ice_size.control(ControlContext(ice, DeviceState(), "large"))

    assert result.command == commands.ice_size(ice, "large")
    assert result.optimistic == {"ice_size": "large"}


def test_fan_control_matches_fan_builders() -> None:
    profile = profile_for("H7100")
    spec = _spec("H7100", "fan", "fan")
    state = DeviceState(power=True, fan_speed=3)

    power = spec.control(
        ControlContext(profile, state, True, operation="power", parameters={"speed": 3})
    )
    assert power.command == commands.fan_power(profile, True, 3)
    assert power.optimistic == {"power": True}

    speed = spec.control(ControlContext(profile, state, 50, operation="speed"))
    assert speed.command == commands.fan_speed(profile, 4)
    assert speed.optimistic == {"percentage": 50, "fan_speed": 4}

    mode = spec.control(ControlContext(profile, state, "manual", operation="mode"))
    assert mode.command == commands.fan_mode(profile, "manual")
    assert mode.optimistic == {"mode": "manual", "power": True}

    oscillate = spec.control(ControlContext(profile, state, True, operation="oscillate"))
    assert oscillate.command == commands.oscillation(profile, True)


def test_purifier_and_dehumidifier_fan_controls_match_builders() -> None:
    purifier = profile_for("H7120")
    purifier_spec = _spec("H7120", "fan", "fan")
    state = DeviceState(power=True)

    power = purifier_spec.control(
        ControlContext(purifier, state, True, operation="power", parameters={"speed": 1})
    )
    assert power.command == commands.power(purifier, True)

    speed = purifier_spec.control(ControlContext(purifier, state, 60, operation="speed"))
    assert speed.command == commands.purifier_speed(purifier, 60)
    assert speed.optimistic == {"percentage": 60, "fan_speed": 3}

    mode = purifier_spec.control(ControlContext(purifier, state, "sleep", operation="mode"))
    assert mode.command == commands.purifier_mode(purifier, "sleep")

    dehumidifier = profile_for("H7150")
    dehumidifier_spec = _spec("H7150", "fan", "fan")
    mode = dehumidifier_spec.control(ControlContext(dehumidifier, state, "auto", operation="mode"))
    assert mode.command == commands.dehumidifier_mode(dehumidifier, "auto")
