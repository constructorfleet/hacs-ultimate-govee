"""Device profiles and SKU classification.

The SKU lists come from the reverse-engineered protocol work in
constructorfleet/ultimate-govee and the homebridge-govee project. A profile
describes what a device can do, not how Home Assistant should draw it; the
entity plan turns a profile into entities and the platform modules instantiate
them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

KIND_LIGHT = "light"
KIND_SWITCH = "switch"
KIND_FAN = "fan"
KIND_CEILING_FAN = "ceiling_fan"
KIND_HUMIDIFIER = "humidifier"
KIND_PURIFIER = "purifier"
KIND_DEHUMIDIFIER = "dehumidifier"
KIND_DIFFUSER = "diffuser"
KIND_HEATER = "heater"
KIND_ICE_MAKER = "ice_maker"
KIND_KETTLE = "kettle"
KIND_THERMO = "thermo"
KIND_LEAK = "leak"
KIND_PRESENCE = "presence"
KIND_CONTACT = "contact"
KIND_CO2 = "co2"
KIND_PROBE = "probe"
KIND_MONITOR = "monitor"
KIND_TV = "tv"
KIND_COMPOSTER = "composter"
KIND_UNKNOWN = "unknown"

FEATURE_POWER = "power"
FEATURE_BRIGHTNESS = "brightness"
FEATURE_COLOR = "color"
FEATURE_COLOR_TEMP = "color_temp"
FEATURE_NIGHT_LIGHT = "night_light"
FEATURE_DISPLAY = "display"
FEATURE_LOCK = "lock"
FEATURE_UV = "uv"
FEATURE_FILTER = "filter"
FEATURE_WATER_TANK = "water_tank"
FEATURE_OSCILLATION = "oscillation"
FEATURE_ICE_SIZE = "ice_size"
FEATURE_BASKET = "basket"
FEATURE_TARGET_HUMIDITY = "target_humidity"
FEATURE_HUMIDITY = "humidity"
FEATURE_TEMPERATURE = "temperature"
FEATURE_BATTERY = "battery"
FEATURE_MODE = "mode"
FEATURE_FAN = "fan"
FEATURE_PM25 = "pm25"
FEATURE_AIR_QUALITY = "air_quality"
FEATURE_CO2 = "co2"
FEATURE_LEAK = "leak"
FEATURE_PRESENCE = "presence"
FEATURE_CONTACT = "contact"
FEATURE_TARGET_TEMPERATURE = "target_temperature"
FEATURE_POWER_METERING = "power_metering"


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """Capabilities of one device model."""

    kind: str
    features: frozenset[str] = frozenset({FEATURE_POWER})
    fan_speeds: int = 0
    gang_count: int = 1
    min_kelvin: int = 2000
    max_kelvin: int = 9000
    brightness_max: int = 100
    power_on: int = 1
    power_off: int = 0
    status_cmd_version: int = 2
    model_name: str = ""
    ice_sizes: tuple[str, ...] = ()
    modes: tuple[str, ...] = ()
    # Evidence label for the registry row that selected this profile. It is
    # not a taxonomy; see the note above SKU_ROWS.
    evidence: str = "generic"
    # Name of the family dialect that owns this SKU's register frames. The
    # assignment comes from the same SKU row, never from kind or prefix.
    dialect: str = "generic"

    @property
    def supports_color(self) -> bool:
        """Return whether the device can show an arbitrary colour."""
        return FEATURE_COLOR in self.features

    @property
    def supports_color_temp(self) -> bool:
        """Return whether the device can show tunable white."""
        return FEATURE_COLOR_TEMP in self.features

    @property
    def supports_brightness(self) -> bool:
        """Return whether the device has a brightness control."""
        return FEATURE_BRIGHTNESS in self.features


LIGHT_FEATURES = frozenset(
    {
        FEATURE_POWER,
        FEATURE_BRIGHTNESS,
        FEATURE_COLOR,
        FEATURE_COLOR_TEMP,
    }
)
APPLIANCE_FEATURES = frozenset({FEATURE_POWER})

# These lists are intentionally kept as data. Adding a new model is a one-line
# change in exactly one row below, and unknown models still get a power switch
# rather than disappearing. Exact rows are disjoint: the registry rejects a SKU
# that appears in two of them.
CEILING_FAN_MODELS = frozenset({"H1310", "H1370", "R1310"})
TOWER_FAN_MODELS = frozenset(
    {
        "H7100",
        "H7101",
        "H7102",
        "H7103",
        "H7106",
        "H7111",
        "H7112",
    }
)
FAN_H7105_MODELS = frozenset({"H7105", "H7107"})
FAN_MODELS = TOWER_FAN_MODELS | FAN_H7105_MODELS
HEATER1_MODELS = frozenset({"H7130", "H7137", "H713A", "H713C", "H713E"})
HEATER2_MODELS = frozenset({"H7131", "H7132", "H7133", "H7134", "H7135", "H713B"})
HEATER_MODELS = HEATER1_MODELS | HEATER2_MODELS
HUMIDIFIER_MODELS = frozenset(
    {
        "H7140",
        "H7141",
        "H7142",
        "H7143",
        "H7145",
        "H7146",
        "H7147",
        "H7148",
        "H7149",
        "H714E",
        "H7160",
    }
)
HUMIDIFIER_H7141_MODELS = frozenset({"H7141"})
HUMIDIFIER_H7142_MODELS = frozenset({"H7142"})
HUMIDIFIER_GENERIC_MODELS = HUMIDIFIER_MODELS - (HUMIDIFIER_H7141_MODELS | HUMIDIFIER_H7142_MODELS)
PURIFIER_MODELS = frozenset(
    {
        "H7120",
        "H7121",
        "H7122",
        "H7123",
        "H7124",
        "H7126",
        "H7127",
        "H7128",
        "H7129",
        "H712C",
    }
)
PURIFIER_3A_MODELS = frozenset({"H7122", "H7123", "H7124"})
PURIFIER_H7120_MODELS = frozenset({"H7120", "H7121"})
PURIFIER_H7126_MODELS = frozenset({"H7126", "H7127", "H7128", "H7129", "H712C"})
DEHUMIDIFIER_MODELS = frozenset({"H7150", "H7151", "H7152"})
DIFFUSER_MODELS = frozenset({"H7161", "H7162"})
ICE_MAKER_MODELS = frozenset({"H7172", "H717D", "H8102", "H8120", "H8121", "H8122", "H8131"})
ICE_MAKER_H8120_MODELS = frozenset({"H8120"})
ICE_MAKER_ASCENDING_MODELS = frozenset({"H8121", "H8122"})
ICE_MAKER_GENERIC_MODELS = ICE_MAKER_MODELS - (ICE_MAKER_H8120_MODELS | ICE_MAKER_ASCENDING_MODELS)
KETTLE_MODELS = frozenset({"H7170", "H7171", "H7173", "H7175", "H717A"})
COMPOSTER_MODELS = frozenset({"H7184"})
TV_MODELS = frozenset({"H1161", "H1163", "H1167", "H1168", "H1162"})

SWITCH_SINGLE_MODELS = frozenset(
    {"H5001", "H5080", "H5081", "H5083", "H5085", "H5086", "H5901", "H7014"}
)
SWITCH_DOUBLE_MODELS = frozenset({"H5082", "H5089"})
SWITCH_TRIPLE_MODELS = frozenset({"H5160", "H5161"})

# The only switch family that reports voltage, current and power usage.
POWER_METERING_MODELS = frozenset({"H5086"})

LEAK_MODELS = frozenset({"H5054", "H5058", "H5059", "H5830"})
THERMO_MODELS = frozenset(
    {
        "B5178",
        "H5051",
        "H5052",
        "H5053",
        "H5055",
        "H5071",
        "H5072",
        "H5074",
        "H5075",
        "H5100",
        "H5101",
        "H5102",
        "H5103",
        "H5104",
        "H5105",
        "H5107",
        "H5108",
        "H5109",
        "H5110",
        "H5111",
        "H5112",
        "H5171",
        "H5174",
        "H5177",
        "H5179",
        "H5183",
        "H5190",
        "H5220",
        "H5310",
        "R5112",
    }
)
PROBE_MODELS = frozenset(
    {
        "H5181",
        "H5182",
        "H5184",
        "H5185",
        "H5191",
        "H5192",
        "H5194",
        "H5196",
        "H5198",
        "H5199",
        "H5610",
    }
)
MONITOR_MODELS = frozenset({"H5106"})
CO2_MODELS = frozenset({"H5140"})
PRESENCE_MODELS = frozenset({"H5127"})
BUTTON_MODELS = frozenset({"H5122"})
CONTACT_MODELS = frozenset({"H5023", "H5123"})
UNKNOWN_SENSOR_MODELS = frozenset({"H5026", "H5130"})

# Models whose brightness is sent on the 0-254 scale rather than 0-100.
BRIGHTNESS_254_MODELS = frozenset(
    {
        "H6002",
        "H6054",
        "H6083",
        "H6085",
        "H6135",
        "H6137",
        "H6143",
        "H6144",
        "H7005",
    }
)

KELVIN_OVERRIDES: dict[str, tuple[int, int]] = {
    "H601C": (2700, 9000),
    "H6022": (2700, 6500),
    "H60A1": (2200, 6500),
}

# Per-model command quirks.
POWER_OVERRIDES: dict[str, tuple[int, int]] = {
    "H5080": (17, 16),
    "H5083": (17, 16),
}

STATUS_VERSION_OVERRIDES: dict[str, int] = {"H6121": 1}

ICE_SIZES = ("small", "medium", "large")
ICE_SIZES_ASCENDING = frozenset({"H8121", "H8122"})

FAN_SPEEDS: dict[str, int] = {
    "H1310": 6,
    "H1370": 12,
    "R1310": 6,
}


# One SKU row carries the capability factory, the wire dialect, and the
# evidence label. Exact rows are expanded from disjoint model lists, so a SKU
# cannot pick up one row's capabilities and another row's dialect. Prefix and
# fallback rules are explicit and only apply to SKUs no exact row names.
Factory = Callable[[str, list[str] | None, dict[str, Any] | None], DeviceProfile]


@dataclass(frozen=True, slots=True)
class SkuRow:
    """One authoritative per-SKU profile and dialect assignment."""

    sku: str
    name: str
    factory: Factory
    dialect: str
    evidence: str
    source: str

    def build(
        self,
        support_cmds: list[str] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> DeviceProfile:
        """Build this row's profile and stamp it with evidence and dialect."""
        return replace(
            self.factory(self.sku, support_cmds, properties),
            evidence=self.evidence,
            dialect=self.dialect,
        )


@dataclass(frozen=True, slots=True)
class SkuGroup:
    """A compact declaration expanded into one :class:`SkuRow` per SKU.

    ``name`` is the unique rule id; ``evidence`` is the label copied onto every
    profile the group builds. ``dialect`` is explicit even when it is
    ``"generic"``: there is no silent fallback for an exact SKU row.
    """

    name: str
    models: frozenset[str]
    factory: Factory
    dialect: str
    evidence: str
    source: str


def _build_sku_rows(groups: tuple[SkuGroup, ...]) -> dict[str, SkuRow]:
    """Expand groups into per-SKU rows and reject contradictory assignments."""
    rows: dict[str, SkuRow] = {}
    names: set[str] = set()
    for group in groups:
        if group.name in names:
            raise ValueError(f"duplicate profile rule name: {group.name}")
        if not group.models:
            raise ValueError(f"profile rule {group.name} has no models")
        names.add(group.name)
        for sku in sorted(group.models):
            existing = rows.get(sku)
            if existing is not None:
                raise ValueError(f"{sku} is assigned to both {existing.name} and {group.name}")
            rows[sku] = SkuRow(
                sku=sku,
                name=group.name,
                factory=group.factory,
                dialect=group.dialect,
                evidence=group.evidence,
                source=group.source,
            )
    return rows


def _ceiling_fan_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return DeviceProfile(
        kind=KIND_CEILING_FAN,
        features={
            FEATURE_POWER,
            FEATURE_FAN,
            FEATURE_BRIGHTNESS,
            FEATURE_COLOR,
            FEATURE_COLOR_TEMP,
        },
        fan_speeds=FAN_SPEEDS.get(sku, 6),
        model_name=sku,
    )


def _fan_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    features = {
        FEATURE_POWER,
        FEATURE_FAN,
        FEATURE_OSCILLATION,
    }
    if sku in {"H7105", "H7107"}:
        features.add(FEATURE_NIGHT_LIGHT)
    return DeviceProfile(
        kind=KIND_FAN,
        features=features,
        fan_speeds=FAN_SPEEDS.get(sku, 8),
        model_name=sku,
    )


def _heater1_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return DeviceProfile(
        kind=KIND_HEATER,
        features={
            FEATURE_POWER,
            FEATURE_TARGET_TEMPERATURE,
            FEATURE_TEMPERATURE,
            FEATURE_FAN,
            FEATURE_MODE,
            FEATURE_LOCK,
            FEATURE_OSCILLATION,
        },
        fan_speeds=3,
        modes=("low", "medium", "high"),
        model_name=sku,
    )


def _heater2_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return DeviceProfile(
        kind=KIND_HEATER,
        features={
            FEATURE_POWER,
            FEATURE_TARGET_TEMPERATURE,
            FEATURE_TEMPERATURE,
            FEATURE_FAN,
            FEATURE_MODE,
            FEATURE_NIGHT_LIGHT,
            FEATURE_LOCK,
            FEATURE_OSCILLATION,
        },
        fan_speeds=4,
        modes=("fan-only", "low", "medium", "high"),
        model_name=sku,
    )


def _humidifier_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    features: set[str] = {
        FEATURE_POWER,
        FEATURE_TARGET_HUMIDITY,
        FEATURE_HUMIDITY,
        FEATURE_MODE,
        FEATURE_WATER_TANK,
    }
    # Only these models implement the 0x1B night light.
    if sku in {"H7140", "H7142", "H7160"}:
        features.add(FEATURE_NIGHT_LIGHT)
    # Humidity decoding and automatic mode are known on the H7141/H7142.
    if sku not in {"H7141", "H7142"}:
        features -= {FEATURE_TARGET_HUMIDITY, FEATURE_HUMIDITY, FEATURE_MODE}
    # The H7142 is the only humidifier with UVC.
    if sku == "H7142":
        features.add(FEATURE_UV)
    return DeviceProfile(
        kind=KIND_HUMIDIFIER,
        features=frozenset(features),
        fan_speeds=9 if sku in {"H7142", "H7160"} else 8,
        modes=("manual", "auto", "program") if FEATURE_MODE in features else (),
        model_name=sku,
    )


def _purifier_profile(
    sku: str,
    *,
    speeds: int,
    modes: tuple[str, ...],
) -> DeviceProfile:
    features: set[str] = {
        FEATURE_POWER,
        FEATURE_FAN,
        FEATURE_FILTER,
        FEATURE_DISPLAY,
        FEATURE_LOCK,
        FEATURE_NIGHT_LIGHT,
        FEATURE_MODE,
    }
    # PM2.5 is decoded from AA 1C on the H7122; the H7123 reports a
    # five-level air-quality enum instead.
    if sku == "H7122":
        features.add(FEATURE_PM25)
    elif sku == "H7123":
        features.add(FEATURE_AIR_QUALITY)
    return DeviceProfile(
        kind=KIND_PURIFIER,
        features=frozenset(features),
        fan_speeds=speeds,
        modes=modes,
        model_name=sku,
    )


def _purifier_3a_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return _purifier_profile(
        sku,
        speeds=5,
        modes=("sleep", "low", "medium", "high", "auto"),
    )


def _purifier_h7120_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return _purifier_profile(
        sku,
        speeds=4,
        modes=("sleep", "low", "medium", "high"),
    )


def _purifier_h7126_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return _purifier_profile(
        sku,
        speeds=3,
        modes=("sleep", "low", "high"),
    )


def _dehumidifier_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return DeviceProfile(
        kind=KIND_DEHUMIDIFIER,
        features={
            FEATURE_POWER,
            FEATURE_TARGET_HUMIDITY,
            FEATURE_HUMIDITY,
            FEATURE_TEMPERATURE,
            FEATURE_FAN,
            FEATURE_MODE,
            FEATURE_WATER_TANK,
        },
        fan_speeds=8,
        modes=("low", "medium", "high", "auto"),
        model_name=sku,
    )


def _diffuser_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return DeviceProfile(
        kind=KIND_DIFFUSER,
        features={FEATURE_POWER},
        model_name=sku,
    )


def _ice_maker_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    if sku in {"H8102", "H8131"}:
        return DeviceProfile(
            kind=KIND_ICE_MAKER,
            features={FEATURE_POWER},
            model_name=sku,
        )
    features = {FEATURE_POWER}
    ice_sizes: tuple[str, ...] = ()
    if sku != "H8120":
        features.add(FEATURE_ICE_SIZE)
        ice_sizes = ICE_SIZES
    return DeviceProfile(
        kind=KIND_ICE_MAKER,
        features=features,
        ice_sizes=ice_sizes,
        model_name=sku,
    )


def _kettle_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return DeviceProfile(
        kind=KIND_KETTLE,
        features={
            FEATURE_POWER,
            FEATURE_TEMPERATURE,
            FEATURE_MODE,
        },
        modes=("custom", "green_tea", "oolong_tea", "coffee", "black_tea"),
        model_name=sku,
    )


def _composter_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return DeviceProfile(
        kind=KIND_COMPOSTER,
        features={FEATURE_POWER},
        model_name=sku,
    )


def _tv_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return DeviceProfile(
        kind=KIND_TV,
        features={FEATURE_POWER, FEATURE_BRIGHTNESS, FEATURE_COLOR, FEATURE_COLOR_TEMP},
        model_name=sku,
    )


def _switch_triple_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return DeviceProfile(
        kind=KIND_SWITCH,
        gang_count=3,
        features={FEATURE_POWER},
        model_name=sku,
    )


def _switch_double_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return DeviceProfile(
        kind=KIND_SWITCH,
        gang_count=2,
        features={FEATURE_POWER},
        model_name=sku,
    )


def _switch_single_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    on, off = POWER_OVERRIDES.get(sku, (1, 0))
    features = {FEATURE_POWER}
    if sku in POWER_METERING_MODELS:
        features.add(FEATURE_POWER_METERING)
    return DeviceProfile(
        kind=KIND_SWITCH,
        features=features,
        power_on=on,
        power_off=off,
        model_name=sku,
    )


def _sensor_profile(sku: str, kind: str, features: frozenset[str]) -> DeviceProfile:
    return DeviceProfile(kind=kind, features=features | {FEATURE_BATTERY}, model_name=sku)


def _leak_sensor_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return _sensor_profile(sku, KIND_LEAK, {FEATURE_LEAK})


def _co2_sensor_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return _sensor_profile(sku, KIND_CO2, {FEATURE_CO2, FEATURE_TEMPERATURE, FEATURE_HUMIDITY})


def _presence_sensor_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return _sensor_profile(sku, KIND_PRESENCE, {FEATURE_PRESENCE})


def _contact_sensor_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return _sensor_profile(sku, KIND_CONTACT, {FEATURE_CONTACT})


def _probe_sensor_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return _sensor_profile(sku, KIND_PROBE, {FEATURE_TEMPERATURE})


def _monitor_sensor_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return _sensor_profile(sku, KIND_MONITOR, {FEATURE_TEMPERATURE, FEATURE_HUMIDITY})


def _thermo_sensor_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return _sensor_profile(sku, KIND_THERMO, {FEATURE_TEMPERATURE, FEATURE_HUMIDITY})


def _unknown_sensor_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    return _sensor_profile(sku, KIND_UNKNOWN, {FEATURE_BATTERY})


def _light_profile(sku: str, features: frozenset[str]) -> DeviceProfile:
    minimum, maximum = KELVIN_OVERRIDES.get(sku, (2000, 9000))
    return DeviceProfile(
        kind=KIND_LIGHT,
        features=features | {FEATURE_POWER, FEATURE_BRIGHTNESS},
        min_kelvin=minimum,
        max_kelvin=maximum,
        brightness_max=254 if sku in BRIGHTNESS_254_MODELS else 100,
        status_cmd_version=STATUS_VERSION_OVERRIDES.get(sku, 2),
        model_name=sku,
    )


def _light_prefix_profile(
    sku: str,
    support_cmds: list[str] | None = None,
    properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    features = set(LIGHT_FEATURES)
    # A cloud capability list is authoritative when the device provides one.
    command_names = {str(command).lower() for command in support_cmds or []}
    if command_names:
        if not any("color" in command for command in command_names):
            features.discard(FEATURE_COLOR)
        if not any("colortem" in command or "color_tem" in command for command in command_names):
            features.discard(FEATURE_COLOR_TEMP)
    profile = _light_profile(sku, frozenset(features))
    kelvin = (properties or {}).get("colorTem", {}).get("range", {})
    if isinstance(kelvin, dict) and kelvin.get("min") and kelvin.get("max"):
        profile = replace(
            profile,
            min_kelvin=int(kelvin["min"]),
            max_kelvin=int(kelvin["max"]),
        )
    return profile


def _generic_profile(
    sku: str,
    _support_cmds: list[str] | None = None,
    _properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    # Unknown devices still get power, which every appliance the reverse
    # engineering work has seen accepts.
    return DeviceProfile(
        kind=KIND_SWITCH,
        features={FEATURE_POWER},
        model_name=sku,
    )


def is_light_sku(sku: str) -> bool:
    """Return whether a SKU belongs to the light prefix family."""
    if sku.startswith(("H6", "H1", "H2", "H3", "R1", "R2", "R6", "R7")):
        return True
    return bool(sku.startswith(("H70", "H73", "H80", "H86", "H88")))


# Profile evidence labels record why a row matched (an explicit model list or a
# captured handler), not a taxonomy. Two SKUs of one kind may carry different
# labels and different dialects. The exact rows are disjoint, which is what
# makes the prefix collisions explicit rather than order-dependent: H1310/R1310
# are ceiling fans despite the H1/R1 light prefix, the H116x set is a TV set
# despite H1, and H7014 is a switch despite H70.
_SKU_GROUPS: tuple[SkuGroup, ...] = (
    SkuGroup(
        "ceiling_fan",
        CEILING_FAN_MODELS,
        _ceiling_fan_profile,
        "ceiling_fan",
        "ceiling_fan",
        "verified ceiling-fan handler",
    ),
    SkuGroup("fan", TOWER_FAN_MODELS, _fan_profile, "fan", "fan", "verified tower-fan handler"),
    SkuGroup(
        "fan_h7105",
        FAN_H7105_MODELS,
        _fan_profile,
        "fan_h7105",
        "fan",
        "verified H7105/H7107 auto-mode handler",
    ),
    SkuGroup(
        "heater1",
        HEATER1_MODELS,
        _heater1_profile,
        "heater1",
        "heater1",
        "verified heater1 handler",
    ),
    SkuGroup(
        "heater2",
        HEATER2_MODELS,
        _heater2_profile,
        "heater2",
        "heater2",
        "verified H7131 handler",
    ),
    SkuGroup(
        "humidifier_h7141",
        HUMIDIFIER_H7141_MODELS,
        _humidifier_profile,
        "humidifier_h7141",
        "humidifier",
        "verified H7141 handler",
    ),
    SkuGroup(
        "humidifier_h7142",
        HUMIDIFIER_H7142_MODELS,
        _humidifier_profile,
        "humidifier_h7142",
        "humidifier",
        "verified H7142 handler",
    ),
    SkuGroup(
        "humidifier_generic",
        HUMIDIFIER_GENERIC_MODELS,
        _humidifier_profile,
        "generic",
        "humidifier",
        "shipped humidifier model list; no dialect evidence",
    ),
    SkuGroup(
        "purifier_3a",
        PURIFIER_3A_MODELS,
        _purifier_3a_profile,
        "purifier_3a",
        "purifier_3a",
        "verified 0x3A purifier handler",
    ),
    SkuGroup(
        "purifier_h7120",
        PURIFIER_H7120_MODELS,
        _purifier_h7120_profile,
        "purifier_h7120",
        "purifier_h7120",
        "verified H7120 gear handler",
    ),
    SkuGroup(
        "purifier_h7126",
        PURIFIER_H7126_MODELS,
        _purifier_h7126_profile,
        "purifier_h7126",
        "purifier_h7126",
        "verified H7126 speed handler",
    ),
    SkuGroup(
        "dehumidifier",
        DEHUMIDIFIER_MODELS,
        _dehumidifier_profile,
        "dehumidifier",
        "dehumidifier",
        "verified dehumidifier handler",
    ),
    SkuGroup(
        "diffuser",
        DIFFUSER_MODELS,
        _diffuser_profile,
        "generic",
        "diffuser",
        "shipped model list",
    ),
    SkuGroup(
        "ice_maker",
        ICE_MAKER_GENERIC_MODELS,
        _ice_maker_profile,
        "ice_maker",
        "ice_maker",
        "verified ice-maker handler",
    ),
    SkuGroup(
        "ice_maker_h8120",
        ICE_MAKER_H8120_MODELS,
        _ice_maker_profile,
        "ice_maker_h8120",
        "ice_maker",
        "verified H8120 power handler",
    ),
    SkuGroup(
        "ice_maker_ascending",
        ICE_MAKER_ASCENDING_MODELS,
        _ice_maker_profile,
        "ice_maker_ascending",
        "ice_maker",
        "verified H8121/H8122 ice-size handler",
    ),
    SkuGroup("kettle", KETTLE_MODELS, _kettle_profile, "generic", "kettle", "shipped model list"),
    SkuGroup(
        "composter",
        COMPOSTER_MODELS,
        _composter_profile,
        "generic",
        "composter",
        "shipped model list",
    ),
    SkuGroup("tv", TV_MODELS, _tv_profile, "generic", "tv", "explicit TV model list"),
    SkuGroup(
        "switch_triple",
        SWITCH_TRIPLE_MODELS,
        _switch_triple_profile,
        "generic",
        "switch_triple",
        "explicit switch model list",
    ),
    SkuGroup(
        "switch_double",
        SWITCH_DOUBLE_MODELS,
        _switch_double_profile,
        "generic",
        "switch_double",
        "explicit switch model list",
    ),
    SkuGroup(
        "switch_single",
        SWITCH_SINGLE_MODELS,
        _switch_single_profile,
        "generic",
        "switch_single",
        "explicit switch model list",
    ),
    SkuGroup(
        "leak_sensor",
        LEAK_MODELS,
        _leak_sensor_profile,
        "generic",
        "leak_sensor",
        "shipped model list",
    ),
    SkuGroup(
        "co2_sensor",
        CO2_MODELS,
        _co2_sensor_profile,
        "generic",
        "co2_sensor",
        "shipped model list",
    ),
    SkuGroup(
        "presence_sensor",
        PRESENCE_MODELS,
        _presence_sensor_profile,
        "generic",
        "presence_sensor",
        "shipped model list",
    ),
    SkuGroup(
        "contact_sensor",
        CONTACT_MODELS,
        _contact_sensor_profile,
        "generic",
        "contact_sensor",
        "shipped model list",
    ),
    SkuGroup(
        "probe_sensor",
        PROBE_MODELS,
        _probe_sensor_profile,
        "generic",
        "probe_sensor",
        "shipped model list",
    ),
    SkuGroup(
        "monitor_sensor",
        MONITOR_MODELS,
        _monitor_sensor_profile,
        "generic",
        "monitor_sensor",
        "shipped model list",
    ),
    SkuGroup(
        "thermo_sensor",
        THERMO_MODELS,
        _thermo_sensor_profile,
        "generic",
        "thermo_sensor",
        "shipped model list",
    ),
    SkuGroup(
        "unknown_sensor",
        BUTTON_MODELS | UNKNOWN_SENSOR_MODELS,
        _unknown_sensor_profile,
        "generic",
        "unknown_sensor",
        "shipped model list",
    ),
)

# The one authoritative SKU index: profile factory, dialect, and evidence.
SKU_ROWS: dict[str, SkuRow] = _build_sku_rows(_SKU_GROUPS)


def sku_row(sku: str) -> SkuRow | None:
    """Return the exact SKU row, or ``None`` when a prefix rule applies."""
    return SKU_ROWS.get((sku or "").strip().upper())


def profile_for(
    sku: str,
    support_cmds: list[str] | None = None,
    properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    """Build the profile for a model, using the cloud capability list if present."""
    sku = (sku or "").strip().upper()

    row = SKU_ROWS.get(sku)
    if row is not None:
        return row.build(support_cmds, properties)
    if is_light_sku(sku):
        return replace(
            _light_prefix_profile(sku, support_cmds, properties),
            evidence="light_prefix",
            dialect="generic",
        )
    return replace(
        _generic_profile(sku, support_cmds, properties),
        evidence="generic",
        dialect="generic",
    )


def sensor_keys(profile: DeviceProfile) -> tuple[str, ...]:
    """Return the sensor entity keys a profile exposes."""
    keys: list[str] = []
    if FEATURE_TEMPERATURE in profile.features:
        keys.append("temperature")
    if FEATURE_HUMIDITY in profile.features:
        keys.append("humidity")
    if FEATURE_PM25 in profile.features:
        keys.append("pm25")
    if FEATURE_AIR_QUALITY in profile.features:
        keys.append("air_quality")
    if FEATURE_CO2 in profile.features:
        keys.append("co2")
    if FEATURE_FILTER in profile.features:
        keys.append("filter_life")
    if FEATURE_BATTERY in profile.features:
        keys.append("battery")
    if FEATURE_POWER_METERING in profile.features:
        keys.extend(("voltage", "current", "power_usage"))
    return tuple(keys)


def binary_sensor_keys(profile: DeviceProfile) -> tuple[str, ...]:
    """Return the binary sensor entity keys a profile exposes."""
    keys: list[str] = []
    if FEATURE_LEAK in profile.features:
        keys.append("leak")
    if FEATURE_PRESENCE in profile.features:
        keys.append("presence")
    if FEATURE_CONTACT in profile.features:
        keys.append("contact")
    if FEATURE_WATER_TANK in profile.features:
        keys.append("water_shortage")
    if FEATURE_BASKET in profile.features:
        keys.append("basket_full")
    return tuple(keys)
