"""The Home Assistant entities a device profile supports.

The entity plan is the one place that decides which entities exist for a
profile, what metadata they carry, and how a control action becomes a
:class:`~.protocol.command.Command`. Platform modules are thin adapters: they
ask the plan for their platform's specs and instantiate them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDensity,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfRatio,
    UnitOfTemperature,
)
from homeassistant.util.percentage import percentage_to_ordered_list_item

from .models import DeviceState
from .profiles import (
    FEATURE_DISPLAY,
    FEATURE_ICE_SIZE,
    FEATURE_LOCK,
    FEATURE_NIGHT_LIGHT,
    FEATURE_OSCILLATION,
    FEATURE_TARGET_TEMPERATURE,
    FEATURE_UV,
    KIND_CEILING_FAN,
    KIND_COMPOSTER,
    KIND_DEHUMIDIFIER,
    KIND_DIFFUSER,
    KIND_FAN,
    KIND_HEATER,
    KIND_HUMIDIFIER,
    KIND_ICE_MAKER,
    KIND_KETTLE,
    KIND_LIGHT,
    KIND_PURIFIER,
    KIND_SWITCH,
    KIND_TV,
    DeviceProfile,
    binary_sensor_keys,
    sensor_keys,
)
from .protocol import commands
from .protocol.command import Command

PLATFORM_BINARY_SENSOR: Final = "binary_sensor"
PLATFORM_FAN: Final = "fan"
PLATFORM_HUMIDIFIER: Final = "humidifier"
PLATFORM_LIGHT: Final = "light"
PLATFORM_NUMBER: Final = "number"
PLATFORM_SELECT: Final = "select"
PLATFORM_SENSOR: Final = "sensor"
PLATFORM_SWITCH: Final = "switch"

type DeviceClass = SensorDeviceClass | BinarySensorDeviceClass | NumberDeviceClass


@dataclass(frozen=True, slots=True)
class ControlContext:
    """The device facts and requested value for one control action."""

    profile: DeviceProfile
    state: DeviceState
    value: Any = None
    options: tuple[str, ...] = ()
    operation: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ControlResult:
    """The Command a control action produces and its optimistic state."""

    command: Command
    optimistic: Mapping[str, Any] = field(default_factory=dict)


ControlBuilder = Callable[[ControlContext], ControlResult]

FAN_OPERATION_POWER: Final = "power"
FAN_OPERATION_SPEED: Final = "speed"
FAN_OPERATION_MODE: Final = "mode"
FAN_OPERATION_OSCILLATE: Final = "oscillate"

LIGHT_OPERATION_POWER: Final = "power"
LIGHT_OPERATION_BRIGHTNESS: Final = "brightness"
LIGHT_OPERATION_COLOR: Final = "color"
LIGHT_OPERATION_COLOR_TEMP: Final = "color_temp"
LIGHT_OPERATION_EFFECT: Final = "effect"

HUMIDIFIER_OPERATION_POWER: Final = "power"
HUMIDIFIER_OPERATION_TARGET: Final = "target"
HUMIDIFIER_OPERATION_MODE: Final = "mode"


@dataclass(frozen=True, slots=True)
class EntitySpec:
    """One entity a profile supports and the metadata it needs."""

    platform: str
    key: str
    state_key: str | None = None
    control: ControlBuilder | None = None
    name: str | None = None
    translation_key: str | None = None
    device_class: DeviceClass | None = None
    unit: str | None = None
    state_class: SensorStateClass | None = None
    entity_category: EntityCategory | None = None
    options: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    icon: str | None = None


# Sensor readings select from the profile's data-driven sensor keys.
_SENSOR_SPECS: Final[dict[str, EntitySpec]] = {
    "temperature": EntitySpec(
        platform=PLATFORM_SENSOR,
        key="temperature",
        state_key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "humidity": EntitySpec(
        platform=PLATFORM_SENSOR,
        key="humidity",
        state_key="humidity",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "battery": EntitySpec(
        platform=PLATFORM_SENSOR,
        key="battery",
        state_key="battery",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "pm25": EntitySpec(
        platform=PLATFORM_SENSOR,
        key="pm25",
        state_key="pm25",
        name="Pm25",
        device_class=SensorDeviceClass.PM25,
        unit=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "co2": EntitySpec(
        platform=PLATFORM_SENSOR,
        key="co2",
        state_key="co2",
        name="Co2",
        device_class=SensorDeviceClass.CO2,
        unit=UnitOfRatio.PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "air_quality": EntitySpec(
        platform=PLATFORM_SENSOR,
        key="air_quality",
        state_key="air_quality",
        translation_key="air_quality",
        device_class=SensorDeviceClass.ENUM,
        options=("excellent", "good", "moderate", "poor"),
    ),
    "filter_life": EntitySpec(
        platform=PLATFORM_SENSOR,
        key="filter_life",
        state_key="filter_life",
        translation_key="filter_life",
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:air-filter",
    ),
    "voltage": EntitySpec(
        platform=PLATFORM_SENSOR,
        key="voltage",
        state_key="voltage",
        name="Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        unit=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "current": EntitySpec(
        platform=PLATFORM_SENSOR,
        key="current",
        state_key="current",
        name="Current",
        device_class=SensorDeviceClass.CURRENT,
        unit=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "power_usage": EntitySpec(
        platform=PLATFORM_SENSOR,
        key="power_usage",
        state_key="power_usage",
        name="Power Usage",
        device_class=SensorDeviceClass.POWER,
        unit=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
}

# Binary sensors select from the profile's data-driven binary sensor keys.
_BINARY_SENSOR_SPECS: Final[dict[str, EntitySpec]] = {
    "leak": EntitySpec(
        platform=PLATFORM_BINARY_SENSOR,
        key="leak",
        state_key="leak",
        translation_key="leak",
        device_class=BinarySensorDeviceClass.MOISTURE,
    ),
    "presence": EntitySpec(
        platform=PLATFORM_BINARY_SENSOR,
        key="presence",
        state_key="presence",
        name="Presence",
        device_class=BinarySensorDeviceClass.PRESENCE,
    ),
    "contact": EntitySpec(
        platform=PLATFORM_BINARY_SENSOR,
        key="contact",
        state_key="contact",
        translation_key="contact",
        device_class=BinarySensorDeviceClass.OPENING,
    ),
    "water_shortage": EntitySpec(
        platform=PLATFORM_BINARY_SENSOR,
        key="water_shortage",
        state_key="water_shortage",
        translation_key="water_shortage",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    "basket_full": EntitySpec(
        platform=PLATFORM_BINARY_SENSOR,
        key="basket_full",
        state_key="basket_full",
        translation_key="basket_full",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
}

# Kinds whose power is not already covered by their primary entity.
_POWER_SWITCH_KINDS: Final[frozenset[str]] = frozenset(
    {
        KIND_COMPOSTER,
        KIND_DIFFUSER,
        KIND_HEATER,
        KIND_ICE_MAKER,
        KIND_KETTLE,
        KIND_SWITCH,
        KIND_TV,
    }
)

# Kinds that expose accessory toggles as switches.
_CONTROL_SWITCH_KINDS: Final[frozenset[str]] = frozenset(
    {
        KIND_CEILING_FAN,
        KIND_COMPOSTER,
        KIND_DIFFUSER,
        KIND_FAN,
        KIND_HEATER,
        KIND_HUMIDIFIER,
        KIND_ICE_MAKER,
        KIND_KETTLE,
        KIND_PURIFIER,
        KIND_TV,
    }
)

_SWITCH_CONTROLS: Final[tuple[tuple[str, str, EntityCategory | None], ...]] = (
    (FEATURE_NIGHT_LIGHT, "Night light", None),
    (FEATURE_DISPLAY, "Display", EntityCategory.CONFIG),
    (FEATURE_LOCK, "Child lock", EntityCategory.CONFIG),
    (FEATURE_UV, "UV sterilisation", EntityCategory.CONFIG),
    (FEATURE_OSCILLATION, "Oscillation", None),
)

_FAN_KINDS: Final[frozenset[str]] = frozenset(
    {KIND_CEILING_FAN, KIND_DEHUMIDIFIER, KIND_FAN, KIND_PURIFIER}
)


def _power_switch(ctx: ControlContext) -> ControlResult:
    profile = ctx.profile
    on = bool(ctx.value)
    if profile.kind == KIND_ICE_MAKER:
        command = commands.ice_power(profile, on)
    elif profile.kind == KIND_HEATER:
        command = commands.heater_power(profile, on)
    else:
        command = commands.power(profile, on)
    return ControlResult(command, {"power": on})


def _gang_switch(index: int) -> ControlBuilder:
    def build(ctx: ControlContext) -> ControlResult:
        on = bool(ctx.value)
        gangs = list(ctx.state.gangs or ())
        while len(gangs) <= index:
            gangs.append(False)
        gangs[index] = on
        return ControlResult(
            commands.gang_power(ctx.profile, index, on),
            {"gangs": tuple(gangs), "power": any(gangs)},
        )

    return build


def _night_light_switch(ctx: ControlContext) -> ControlResult:
    on = bool(ctx.value)
    return ControlResult(
        commands.night_light(
            ctx.profile,
            on,
            ctx.state.night_light_brightness or 100,
            ctx.state.color or (255, 255, 255),
        ),
        {"night_light": on},
    )


def _display_switch(ctx: ControlContext) -> ControlResult:
    on = bool(ctx.value)
    return ControlResult(commands.display(ctx.profile, on), {"display": on})


def _lock_switch(ctx: ControlContext) -> ControlResult:
    on = bool(ctx.value)
    return ControlResult(commands.lock(ctx.profile, on), {"lock": on})


def _uv_switch(ctx: ControlContext) -> ControlResult:
    on = bool(ctx.value)
    return ControlResult(commands.uv(ctx.profile, on), {"uv": on})


def _oscillation_switch(ctx: ControlContext) -> ControlResult:
    on = bool(ctx.value)
    return ControlResult(commands.oscillation(ctx.profile, on), {"oscillation": on})


_SWITCH_CONTROLS_BY_FEATURE: Final[dict[str, ControlBuilder]] = {
    FEATURE_DISPLAY: _display_switch,
    FEATURE_LOCK: _lock_switch,
    FEATURE_NIGHT_LIGHT: _night_light_switch,
    FEATURE_OSCILLATION: _oscillation_switch,
    FEATURE_UV: _uv_switch,
}


def _target_temperature(ctx: ControlContext) -> ControlResult:
    value = float(ctx.value)
    return ControlResult(
        commands.heater_target(ctx.profile, value),
        {"target_temperature": value},
    )


def _night_light_brightness(ctx: ControlContext) -> ControlResult:
    brightness = round(float(ctx.value))
    return ControlResult(
        commands.night_light(
            ctx.profile,
            True,
            brightness,
            ctx.state.color or (255, 255, 255),
        ),
        {"night_light_brightness": brightness, "night_light": True},
    )


def _ice_size(ctx: ControlContext) -> ControlResult:
    option = str(ctx.value)
    return ControlResult(commands.ice_size(ctx.profile, option), {"ice_size": option})


def _heater_speed_select(ctx: ControlContext) -> ControlResult:
    option = str(ctx.value)
    level = ctx.options.index(option) + 1
    percentage = round(level * 100 / len(ctx.options))
    return ControlResult(
        commands.heater_speed(ctx.profile, level),
        {"fan_speed": level, "percentage": percentage},
    )


def _fan_level(profile: DeviceProfile, percentage: int | None) -> int:
    """Map a percentage to the same 1-based level the fan entity reports."""
    speeds = tuple(str(speed) for speed in range(1, profile.fan_speeds + 1))
    if percentage is None or not speeds:
        return 1
    return int(percentage_to_ordered_list_item(list(speeds), percentage))


def _fan_control(ctx: ControlContext) -> ControlResult:
    profile = ctx.profile
    if ctx.operation == FAN_OPERATION_POWER:
        on = bool(ctx.value)
        if profile.kind in {KIND_PURIFIER, KIND_DEHUMIDIFIER}:
            command = commands.power(profile, on)
        else:
            command = commands.fan_power(profile, on, int(ctx.parameters.get("speed", 1)))
        return ControlResult(command, {"power": on})
    if ctx.operation == FAN_OPERATION_SPEED:
        percentage = int(ctx.value)
        level = _fan_level(profile, percentage)
        if profile.kind == KIND_PURIFIER:
            command = commands.purifier_speed(profile, percentage)
        else:
            command = commands.fan_speed(profile, level)
        return ControlResult(command, {"percentage": percentage, "fan_speed": level})
    if ctx.operation == FAN_OPERATION_MODE:
        mode = str(ctx.value)
        if profile.kind == KIND_PURIFIER:
            command = commands.purifier_mode(profile, mode)
        elif profile.kind == KIND_DEHUMIDIFIER:
            command = commands.dehumidifier_mode(profile, mode)
        else:
            command = commands.fan_mode(profile, mode)
        return ControlResult(command, {"mode": mode, "power": True})
    if ctx.operation == FAN_OPERATION_OSCILLATE:
        on = bool(ctx.value)
        return ControlResult(
            commands.oscillation(profile, on),
            {"oscillation": on},
        )
    raise ValueError(f"Unknown fan operation {ctx.operation!r}")


def _light_control(ctx: ControlContext) -> ControlResult:
    """Build the command and optimistic state for one light operation."""
    profile = ctx.profile
    if ctx.operation == LIGHT_OPERATION_POWER:
        on = bool(ctx.value)
        return ControlResult(commands.power(profile, on), {"power": on})
    if ctx.operation == LIGHT_OPERATION_BRIGHTNESS:
        brightness = round(int(ctx.value) * 100 / 255)
        return ControlResult(
            commands.brightness(profile, brightness),
            {"brightness": brightness},
        )
    if ctx.operation == LIGHT_OPERATION_COLOR:
        red, green, blue = ctx.value
        return ControlResult(
            commands.color(red, green, blue),
            {"color": (red, green, blue), "color_temp": None},
        )
    if ctx.operation == LIGHT_OPERATION_COLOR_TEMP:
        kelvin = int(ctx.value)
        return ControlResult(commands.color_temp(kelvin), {"color_temp": kelvin})
    if ctx.operation == LIGHT_OPERATION_EFFECT:
        name = str(ctx.value)
        return ControlResult(
            commands.effect(list(ctx.parameters.get("frames", ()))),
            {"effect": name, "power": True},
        )
    raise ValueError(f"Unknown light operation {ctx.operation!r}")


def _humidifier_control(ctx: ControlContext) -> ControlResult:
    """Build the command and optimistic state for one humidifier operation."""
    profile = ctx.profile
    if ctx.operation == HUMIDIFIER_OPERATION_POWER:
        on = bool(ctx.value)
        return ControlResult(commands.power(profile, on), {"power": on})
    if ctx.operation == HUMIDIFIER_OPERATION_TARGET:
        humidity = int(ctx.value)
        return ControlResult(
            commands.humidifier_target(profile, humidity),
            {"target_humidity": humidity, "mode": "auto"},
        )
    if ctx.operation == HUMIDIFIER_OPERATION_MODE:
        mode = str(ctx.value)
        if mode == "auto":
            target = ctx.state.target_humidity or 50
            return ControlResult(
                commands.humidifier_target(profile, target),
                {"mode": "auto", "power": True},
            )
        if mode == "manual":
            level = ctx.state.fan_speed or 5
            return ControlResult(
                commands.mist_level(profile, level),
                {"mode": "manual", "power": True},
            )
        return ControlResult(commands.humidifier_mode(profile, mode), {"mode": mode})
    raise ValueError(f"Unknown humidifier operation {ctx.operation!r}")


def _binary_sensor_specs(profile: DeviceProfile) -> tuple[EntitySpec, ...]:
    return tuple(
        _BINARY_SENSOR_SPECS[key]
        for key in binary_sensor_keys(profile)
        if key in _BINARY_SENSOR_SPECS
    )


def _fan_specs(profile: DeviceProfile) -> tuple[EntitySpec, ...]:
    if profile.kind in _FAN_KINDS:
        return (EntitySpec(platform=PLATFORM_FAN, key="fan", control=_fan_control),)
    return ()


def _humidifier_specs(profile: DeviceProfile) -> tuple[EntitySpec, ...]:
    if profile.kind == KIND_HUMIDIFIER:
        return (
            EntitySpec(
                platform=PLATFORM_HUMIDIFIER,
                key="humidifier",
                control=_humidifier_control,
            ),
        )
    return ()


def _light_specs(profile: DeviceProfile) -> tuple[EntitySpec, ...]:
    if profile.kind == KIND_LIGHT:
        return (EntitySpec(platform=PLATFORM_LIGHT, key="light", control=_light_control),)
    return ()


def _number_specs(profile: DeviceProfile) -> tuple[EntitySpec, ...]:
    specs: list[EntitySpec] = []
    if FEATURE_TARGET_TEMPERATURE in profile.features:
        specs.append(
            EntitySpec(
                platform=PLATFORM_NUMBER,
                key="target_temperature",
                state_key="target_temperature",
                control=_target_temperature,
                name="Target temperature",
                device_class=NumberDeviceClass.TEMPERATURE,
                unit=UnitOfTemperature.CELSIUS,
                minimum=5,
                maximum=30,
                step=0.5,
            )
        )
    if profile.kind == KIND_HUMIDIFIER and FEATURE_NIGHT_LIGHT in profile.features:
        specs.append(
            EntitySpec(
                platform=PLATFORM_NUMBER,
                key="night_light_brightness",
                state_key="night_light_brightness",
                control=_night_light_brightness,
                name="Night light brightness",
                minimum=1,
                maximum=100,
                step=1,
            )
        )
    return tuple(specs)


def _select_specs(profile: DeviceProfile) -> tuple[EntitySpec, ...]:
    if FEATURE_ICE_SIZE in profile.features and profile.ice_sizes:
        return (
            EntitySpec(
                platform=PLATFORM_SELECT,
                key="ice_size",
                state_key="ice_size",
                control=_ice_size,
                name="Ice size",
                options=profile.ice_sizes,
            ),
        )
    if profile.kind == KIND_HEATER:
        return (
            EntitySpec(
                platform=PLATFORM_SELECT,
                key="fan_speed",
                state_key="fan_speed",
                control=_heater_speed_select,
                name="Fan speed",
                options=profile.modes or ("low", "medium", "high"),
            ),
        )
    return ()


def _sensor_specs(profile: DeviceProfile) -> tuple[EntitySpec, ...]:
    return tuple(_SENSOR_SPECS[key] for key in sensor_keys(profile) if key in _SENSOR_SPECS)


def _gang_specs(profile: DeviceProfile) -> tuple[EntitySpec, ...]:
    return tuple(
        EntitySpec(
            platform=PLATFORM_SWITCH,
            key=f"gang{index}",
            state_key=f"gang{index}",
            control=_gang_switch(index),
            name=f"Gang {index + 1}",
        )
        for index in range(profile.gang_count)
    )


def _switch_specs(profile: DeviceProfile) -> tuple[EntitySpec, ...]:
    specs: list[EntitySpec] = []
    if profile.kind == KIND_SWITCH and profile.gang_count > 1:
        specs.extend(_gang_specs(profile))
    elif profile.kind in _POWER_SWITCH_KINDS:
        specs.append(
            EntitySpec(
                platform=PLATFORM_SWITCH,
                key="power",
                state_key="power",
                control=_power_switch,
            )
        )

    if profile.kind in _CONTROL_SWITCH_KINDS:
        specs.extend(
            EntitySpec(
                platform=PLATFORM_SWITCH,
                key=feature,
                state_key=feature,
                control=_SWITCH_CONTROLS_BY_FEATURE[feature],
                name=name,
                entity_category=category,
            )
            for feature, name, category in _SWITCH_CONTROLS
            if feature in profile.features
        )
    return tuple(specs)


def plan_entities(profile: DeviceProfile) -> tuple[EntitySpec, ...]:
    """Return every entity a profile supports, grouped by platform."""
    return (
        *_binary_sensor_specs(profile),
        *_fan_specs(profile),
        *_humidifier_specs(profile),
        *_light_specs(profile),
        *_number_specs(profile),
        *_select_specs(profile),
        *_sensor_specs(profile),
        *_switch_specs(profile),
    )


def entities_for_platform(profile: DeviceProfile, platform: str) -> tuple[EntitySpec, ...]:
    """Return only the specs a platform instantiates."""
    return tuple(spec for spec in plan_entities(profile) if spec.platform == platform)


__all__ = [
    "FAN_OPERATION_MODE",
    "FAN_OPERATION_OSCILLATE",
    "FAN_OPERATION_POWER",
    "FAN_OPERATION_SPEED",
    "HUMIDIFIER_OPERATION_MODE",
    "HUMIDIFIER_OPERATION_POWER",
    "HUMIDIFIER_OPERATION_TARGET",
    "LIGHT_OPERATION_BRIGHTNESS",
    "LIGHT_OPERATION_COLOR",
    "LIGHT_OPERATION_COLOR_TEMP",
    "LIGHT_OPERATION_EFFECT",
    "LIGHT_OPERATION_POWER",
    "PLATFORM_BINARY_SENSOR",
    "PLATFORM_FAN",
    "PLATFORM_HUMIDIFIER",
    "PLATFORM_LIGHT",
    "PLATFORM_NUMBER",
    "PLATFORM_SELECT",
    "PLATFORM_SENSOR",
    "PLATFORM_SWITCH",
    "ControlContext",
    "ControlResult",
    "EntitySpec",
    "entities_for_platform",
    "plan_entities",
]
