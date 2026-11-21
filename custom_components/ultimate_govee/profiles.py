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
    # Evidence label for the registry rule that selected this profile. It is
    # not a taxonomy; see the note above PROFILE_REGISTRY.
    family: str = "generic"
    # Name of the family dialect that owns this SKU's register frames. The
    # assignment comes from SKU_DIALECTS below, never from kind or prefix.
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
# change, and unknown models still get a power switch rather than disappearing.
FAN_MODELS = frozenset(
    {
        "H1310",
        "H1370",
        "H7100",
        "H7101",
        "H7102",
        "H7103",
        "H7105",
        "H7106",
        "H7107",
        "H7111",
        "H7112",
        "R1310",
    }
)
CEILING_FAN_MODELS = frozenset({"H1310", "H1370", "R1310"})
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


# Per-SKU dialect assignment. One line per SKU, even when several SKUs point at
# the same observed variant: sharing is an optimisation for SKUs the shipped
# handler already treated as byte-identical, never an inference from kind or
# prefix. ``H7141`` and ``H7142`` stay separate because H7142 adds UVC and the
# night light. Names map to implementations in ``protocol/families``.
SKU_DIALECTS: dict[str, str] = {
    # Ceiling fans: exact SKUs despite the H1/R1 light-looking prefixes.
    "H1310": "ceiling_fan",
    "H1370": "ceiling_fan",
    "R1310": "ceiling_fan",
    # Tower fans; H7105/H7107 are the shipped auto-mode-0x02 variant.
    "H7100": "fan",
    "H7101": "fan",
    "H7102": "fan",
    "H7103": "fan",
    "H7105": "fan_h7105",
    "H7106": "fan",
    "H7107": "fan_h7105",
    "H7111": "fan",
    "H7112": "fan",
    # Heater1 (plain 0x33 handler).
    "H7130": "heater1",
    "H7137": "heater1",
    "H713A": "heater1",
    "H713C": "heater1",
    "H713E": "heater1",
    # Heater2 (0x3A sub-commands and multiSync).
    "H7131": "heater2",
    "H7132": "heater2",
    "H7133": "heater2",
    "H7134": "heater2",
    "H7135": "heater2",
    "H713B": "heater2",
    # Humidifiers: the first concrete pair, kept as individual entries.
    "H7141": "humidifier_h7141",
    "H7142": "humidifier_h7142",
    # Dehumidifiers: the shipped handler did not separate these three.
    "H7150": "dehumidifier",
    "H7151": "dehumidifier",
    "H7152": "dehumidifier",
    # Purifier speed layouts; each line stays explicit even where the shipped
    # handler grouped SKUs into one observed variant.
    "H7120": "purifier_h7120",
    "H7121": "purifier_h7120",
    "H7122": "purifier_3a",
    "H7123": "purifier_3a",
    "H7124": "purifier_3a",
    "H7126": "purifier_h7126",
    "H7127": "purifier_h7126",
    "H7128": "purifier_h7126",
    "H7129": "purifier_h7126",
    "H712C": "purifier_h7126",
    # Ice makers: power register and ice-size direction differ by SKU.
    "H7172": "ice_maker",
    "H717D": "ice_maker",
    "H8102": "ice_maker",
    "H8131": "ice_maker",
    "H8120": "ice_maker_h8120",
    "H8121": "ice_maker_ascending",
    "H8122": "ice_maker_ascending",
}


# Profile family names are evidence labels for selection bookkeeping, not a
# taxonomy. A name records why a SKU matched (an explicit model list, a
# captured handler, or a prefix observed on this profile surface); two SKUs of
# one kind may carry different names, and one prefix may span several names.
# Never infer a name from kind, category, or SKU prefix. The explicit
# priorities encode the collisions that make those guesses wrong: H1310/R1310
# are ceiling fans despite the H1/R1 light prefix, the H116x set is a TV set
# despite H1, and H7014 is a switch despite H70.
PRIORITY_PREFIX = 500
PRIORITY_FALLBACK = 1000

Factory = Callable[[str, list[str] | None, dict[str, Any] | None], DeviceProfile]


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    """One ordered rule in the SKU profile registry.

    ``matches`` runs in ascending ``priority`` order. Exact-model rules use
    priorities below ``PRIORITY_PREFIX`` so they always beat prefix rules,
    regardless of where they appear in the declaration.
    """

    name: str
    priority: int
    matches: Callable[[str], bool]
    factory: Factory

    def build(
        self,
        sku: str,
        support_cmds: list[str] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> DeviceProfile:
        """Build this rule's profile and stamp it with the family and dialect."""
        return replace(
            self.factory(sku, support_cmds, properties),
            family=self.name,
            dialect=SKU_DIALECTS.get(sku, "generic"),
        )


def _exact(models: frozenset[str]) -> Callable[[str], bool]:
    """Match one of the listed SKUs exactly."""
    return models.__contains__


def _matches_any(sku: str) -> bool:
    """Match every SKU; the registry uses this for its fallback rule."""
    return True


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


def _sorted_registry(*specs: ProfileSpec) -> tuple[ProfileSpec, ...]:
    """Order specs by explicit priority and reject ambiguous registries."""
    ordered = tuple(sorted(specs, key=lambda spec: spec.priority))
    priorities = [spec.priority for spec in ordered]
    names = [spec.name for spec in ordered]
    if len(set(priorities)) != len(priorities):
        raise ValueError("profile registry priorities must be unique")
    if len(set(names)) != len(names):
        raise ValueError("profile registry names must be unique")
    return ordered


# Ordered registry: exact-model rules (priorities below PRIORITY_PREFIX) run
# before the light prefix rule, and the catch-all generic rule runs last.
# Priority values are explicit because source order is not the contract.
# Family labels for the model lists below are homebridge-derived unless a code
# comment above names a captured variant; they are selection evidence only.
PROFILE_REGISTRY: tuple[ProfileSpec, ...] = _sorted_registry(
    ProfileSpec("ceiling_fan", 10, _exact(CEILING_FAN_MODELS), _ceiling_fan_profile),
    ProfileSpec("fan", 20, _exact(FAN_MODELS), _fan_profile),
    ProfileSpec("heater1", 30, _exact(HEATER1_MODELS), _heater1_profile),
    ProfileSpec("heater2", 40, _exact(HEATER2_MODELS), _heater2_profile),
    ProfileSpec("humidifier", 50, _exact(HUMIDIFIER_MODELS), _humidifier_profile),
    ProfileSpec("purifier_3a", 60, _exact(PURIFIER_3A_MODELS), _purifier_3a_profile),
    ProfileSpec("purifier_h7120", 70, _exact(PURIFIER_H7120_MODELS), _purifier_h7120_profile),
    ProfileSpec("purifier_h7126", 80, _exact(PURIFIER_H7126_MODELS), _purifier_h7126_profile),
    ProfileSpec("dehumidifier", 90, _exact(DEHUMIDIFIER_MODELS), _dehumidifier_profile),
    ProfileSpec("diffuser", 100, _exact(DIFFUSER_MODELS), _diffuser_profile),
    ProfileSpec("ice_maker", 110, _exact(ICE_MAKER_MODELS), _ice_maker_profile),
    ProfileSpec("kettle", 120, _exact(KETTLE_MODELS), _kettle_profile),
    ProfileSpec("composter", 130, _exact(COMPOSTER_MODELS), _composter_profile),
    # Exact-model TV rule: these SKUs look like H1 lights but are not.
    ProfileSpec("tv", 140, _exact(TV_MODELS), _tv_profile),
    ProfileSpec("switch_triple", 150, _exact(SWITCH_TRIPLE_MODELS), _switch_triple_profile),
    ProfileSpec("switch_double", 160, _exact(SWITCH_DOUBLE_MODELS), _switch_double_profile),
    # Exact-model switch rule: H7014 looks like an H70 light but is not.
    ProfileSpec("switch_single", 170, _exact(SWITCH_SINGLE_MODELS), _switch_single_profile),
    ProfileSpec("leak_sensor", 180, _exact(LEAK_MODELS), _leak_sensor_profile),
    ProfileSpec("co2_sensor", 190, _exact(CO2_MODELS), _co2_sensor_profile),
    ProfileSpec("presence_sensor", 200, _exact(PRESENCE_MODELS), _presence_sensor_profile),
    ProfileSpec("contact_sensor", 210, _exact(CONTACT_MODELS), _contact_sensor_profile),
    ProfileSpec("probe_sensor", 220, _exact(PROBE_MODELS), _probe_sensor_profile),
    ProfileSpec("monitor_sensor", 230, _exact(MONITOR_MODELS), _monitor_sensor_profile),
    ProfileSpec("thermo_sensor", 240, _exact(THERMO_MODELS), _thermo_sensor_profile),
    ProfileSpec(
        "unknown_sensor",
        250,
        lambda sku: sku in BUTTON_MODELS or sku in UNKNOWN_SENSOR_MODELS,
        _unknown_sensor_profile,
    ),
    ProfileSpec("light_prefix", PRIORITY_PREFIX, is_light_sku, _light_prefix_profile),
    ProfileSpec("generic", PRIORITY_FALLBACK, _matches_any, _generic_profile),
)


def profile_for(
    sku: str,
    support_cmds: list[str] | None = None,
    properties: dict[str, Any] | None = None,
) -> DeviceProfile:
    """Build the profile for a model, using the cloud capability list if present."""
    sku = (sku or "").strip().upper()

    for spec in PROFILE_REGISTRY:
        if spec.matches(sku):
            return spec.build(sku, support_cmds, properties)

    # The generic rule matches every SKU, so this is unreachable.
    raise AssertionError("profile registry is missing its catch-all rule")


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
