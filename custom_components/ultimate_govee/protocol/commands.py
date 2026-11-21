"""Command builders for Govee's cloud and LAN protocols."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..profiles import (
    HEATER2_MODELS,
    KIND_CEILING_FAN,
    KIND_FAN,
    KIND_HEATER,
    KIND_PURIFIER,
    PURIFIER_3A_MODELS,
    PURIFIER_3A_SPEEDS,
    PURIFIER_H7120_MODELS,
    PURIFIER_H7126_MODELS,
    DeviceProfile,
)
from .codec import build_frame, build_frame_b64, bytes_to_base64

# Humidifier / purifier mode values on register 0x05.
HUMIDIFIER_MODE_MANUAL = 0x01
HUMIDIFIER_MODE_PROGRAM = 0x02
HUMIDIFIER_MODE_AUTO = 0x03

# H7120/H7121 gear values: 25 % sends the special sleep gear 0x10.
PURIFIER_H7120_GEARS = (0x10, 0x01, 0x02, 0x03)


@dataclass(slots=True)
class WireCommand:
    """A command in both the AWS IoT and LAN dialects."""

    cmd: str
    data: dict[str, Any] = field(default_factory=dict)
    lan_cmd: str | None = None
    lan_data: dict[str, Any] | None = None

    def aws_payload(self) -> tuple[str, dict[str, Any]]:
        """Return the AWS command name and data."""
        return self.cmd, self.data

    def lan_payload(self) -> tuple[str, dict[str, Any]] | None:
        """Return the LAN command name and data, if the device supports it."""
        if self.lan_cmd is None:
            return None
        return self.lan_cmd, self.lan_data or self.data


def power(profile: DeviceProfile, on: bool) -> WireCommand:
    """Build a power command."""
    value = profile.power_on if on else profile.power_off
    return WireCommand(
        cmd="turn",
        data={"val": value},
        lan_cmd="turn",
        lan_data={"value": 1 if on else 0},
    )


def gang_power(profile: DeviceProfile, gang: int, on: bool) -> WireCommand:
    """Build a per-gang power command for a double or triple outlet.

    Govee encodes the gang in the magic ``turn`` value rather than in a frame:
    17/16 for gang 1, 34/32 for gang 2 and 68/64 for gang 3.
    """
    values = ((17, 16), (34, 32), (68, 64))
    index = max(0, min(len(values) - 1, gang))
    on_value, off_value = values[index]
    return WireCommand(
        cmd="turn",
        data={"val": on_value if on else off_value},
        lan_cmd="turn",
        lan_data={"value": on_value if on else off_value},
    )


def brightness(profile: DeviceProfile, percent: int) -> WireCommand:
    """Build a brightness command, applying the model's scale."""
    percent = max(0, min(100, percent))
    raw = round(percent * profile.brightness_max / 100)
    return WireCommand(
        cmd="brightness",
        data={"val": raw},
        lan_cmd="brightness",
        lan_data={"value": percent},
    )


def color(red: int, green: int, blue: int) -> WireCommand:
    """Build a colour command."""
    colour = {"r": red, "g": green, "b": blue}
    return WireCommand(
        cmd="colorwc",
        data={"color": colour, "colorTemInKelvin": 0},
        lan_cmd="colorwc",
        lan_data={"color": colour, "colorTemInKelvin": 0},
    )


def color_temp(kelvin: int) -> WireCommand:
    """Build a tunable-white command."""
    red, green, blue = kelvin_to_rgb(kelvin)
    colour = {"r": red, "g": green, "b": blue}
    return WireCommand(
        cmd="colorwc",
        data={"color": colour, "colorTemInKelvin": kelvin},
        lan_cmd="colorwc",
        lan_data={"color": colour, "colorTemInKelvin": kelvin},
    )


def pt_real(
    command: str | bytes | list[str] | list[bytes],
    *,
    lan: bool = True,
    cmd: str = "ptReal",
) -> WireCommand:
    """Build a raw frame command from base64 strings or raw frame bytes."""
    items = [command] if isinstance(command, (str, bytes)) else list(command)
    frames = [item if isinstance(item, str) else bytes_to_base64(item) for item in items]
    return WireCommand(
        cmd=cmd,
        data={"command": frames},
        lan_cmd="ptReal" if lan else None,
        lan_data={"command": frames} if lan else None,
    )


def night_light(
    profile: DeviceProfile,
    on: bool,
    brightness_value: int = 100,
    rgb: tuple[int, int, int] = (255, 255, 255),
) -> WireCommand:
    """Build a night-light command.

    Humidifiers use register 0x1B with a brightness byte and an RGB triplet.
    Purifiers use register 0x18 and always carry a fixed 50 % brightness.
    """
    level = max(0, min(100, brightness_value))
    if profile.kind == KIND_PURIFIER:
        return pt_real(build_frame_b64(0x18, [1 if on else 0, 0x32]))
    if profile.kind == KIND_HEATER and profile.model_name in HEATER2_MODELS:
        if not on:
            return pt_real(build_frame(0x1B, [0x01, 0x01, 0]), cmd="multiSync")
        red, green, blue = (max(0, min(255, value)) for value in rgb)
        return pt_real(
            [
                build_frame(0x1B, [0x01, 0x01, 0x01]),
                build_frame(0x1B, [0x01, 0x02, level]),
                build_frame(0x1B, [0x05, 0x0D, red, green, blue]),
            ],
            cmd="multiSync",
        )
    if profile.kind == KIND_FAN:
        if not on:
            return pt_real(build_frame(0x1B, [0x01, 0x01, 0x00], opcode=0x3A))
        red, green, blue = (max(0, min(255, value)) for value in rgb)
        return pt_real(
            [
                build_frame(0x1B, [0x01, 0x01, 0x01], opcode=0x3A),
                build_frame(0x1B, [0x01, 0x02, level], opcode=0x3A),
                build_frame(0x1B, [0x05, 0x0D, red, green, blue], opcode=0x3A),
            ]
        )
    if not on:
        return pt_real(build_frame_b64(0x1B, [0]))
    red, green, blue = (max(0, min(255, value)) for value in rgb)
    return pt_real(build_frame_b64(0x1B, [1, level, red, green, blue]))


def display(profile: DeviceProfile, on: bool) -> WireCommand:
    """Build a display toggle command (purifiers, register 0x16)."""
    return pt_real(build_frame_b64(0x16, [1 if on else 0]))


def lock(profile: DeviceProfile, on: bool) -> WireCommand:
    """Build a child-lock command.

    Purifiers and heater1 use register 0x10, heater2 uses 0x1F sub-command 2,
    and older appliance handlers use 0x0A.
    """
    if profile.kind == KIND_HEATER and profile.model_name in HEATER2_MODELS:
        return pt_real(build_frame(0x1F, [0x02, 1 if on else 0]), cmd="multiSync")
    register = 0x10 if profile.kind in {KIND_HEATER, KIND_PURIFIER} else 0x0A
    return pt_real(build_frame_b64(register, [1 if on else 0]))


def uv(on: bool) -> WireCommand:
    """Build a UVC command (H7142 family)."""
    return pt_real(build_frame_b64(0x1A, [1 if on else 0]))


def timer(enabled: bool, minutes: int) -> WireCommand:
    """Build a countdown timer command."""
    minutes = max(0, min(0xFFFF, minutes))
    return pt_real(build_frame_b64(0x0A, [0x0B, 1 if enabled else 0, minutes >> 8, minutes & 0xFF]))


def mist_level(level: int) -> WireCommand:
    """Build a manual mist-level command (1-9)."""
    return pt_real(build_frame_b64(0x05, [HUMIDIFIER_MODE_MANUAL, max(1, min(9, level))]))


HUMIDIFIER_MODES: dict[str, int] = {
    "manual": HUMIDIFIER_MODE_MANUAL,
    "program": HUMIDIFIER_MODE_PROGRAM,
    "auto": HUMIDIFIER_MODE_AUTO,
}


def humidifier_mode(profile: DeviceProfile, mode: str) -> WireCommand:
    """Build a humidifier work-mode command."""
    value = HUMIDIFIER_MODES.get(mode.lower(), HUMIDIFIER_MODE_AUTO)
    return pt_real(build_frame_b64(0x05, [0x00, value]))


def humidifier_target(target: int) -> WireCommand:
    """Build an automatic target-humidity command."""
    return pt_real(build_frame_b64(0x05, [HUMIDIFIER_MODE_AUTO, max(1, min(100, target))]))


def purifier_speed(profile: DeviceProfile, percent: int) -> WireCommand:
    """Build a purifier fan-speed command for the model's protocol family."""
    percent = max(0, min(100, percent))
    model = profile.model_name

    if model in PURIFIER_3A_MODELS:
        # Five 20 % steps: sleep, low, medium, high, auto.
        index = min(4, max(0, (percent - 1) // 20))
        _, mode, value = PURIFIER_3A_SPEEDS[index]
        frame = build_frame(0x05, [mode, value], opcode=0x3A)
        return pt_real(frame)

    if model in PURIFIER_H7120_MODELS:
        index = min(3, max(0, (percent - 1) // 25))
        return pt_real(build_frame_b64(0x05, [PURIFIER_H7120_GEARS[index]]))

    if model in PURIFIER_H7126_MODELS:
        level = 1 if percent <= 33 else 2 if percent <= 66 else 3
        return pt_real(build_frame_b64(0x05, [0x01, level]))

    # Generic appliance speed: byte 3 carries the level.
    level = max(1, min(profile.fan_speeds or 4, round(percent / 25)))
    return pt_real(build_frame_b64(0x05, [level]))


def purifier_mode(profile: DeviceProfile, mode: str) -> WireCommand:
    """Build a purifier work-mode command."""
    mode = mode.lower()
    model = profile.model_name
    if model in PURIFIER_3A_MODELS:
        for name, first, second in PURIFIER_3A_SPEEDS:
            if name == mode:
                return pt_real(build_frame(0x05, [first, second], opcode=0x3A))
        return purifier_speed(profile, 100)
    return purifier_speed(profile, 100)


def fan_power(profile: DeviceProfile, on: bool, speed: int = 1) -> WireCommand:
    """Build a fan power command.

    Tower fans use the plain 0x01 power register. Ceiling fans have no separate
    power frame in the AWS protocol; their 0x31 command carries the current
    speed alongside the on/off flag.
    """
    if profile.kind == KIND_CEILING_FAN:
        level = max(1, min(profile.fan_speeds or 6, speed))
        return pt_real(build_frame_b64(0x31, [1 if on else 0, level]))
    return pt_real(build_frame_b64(0x01, [1 if on else 0]))


def fan_speed(profile: DeviceProfile, level: int) -> WireCommand:
    """Build a fan speed command from a 1-based level."""
    level = max(1, min(profile.fan_speeds or 8, level))
    if profile.kind == KIND_CEILING_FAN:
        return pt_real(build_frame_b64(0x31, [0x01, level]))
    return pt_real(build_frame_b64(0x05, [0x01, level]))


def fan_mode(profile: DeviceProfile, mode: str) -> WireCommand:
    """Build a fan auto/manual mode command for tower fans."""
    automatic = mode.lower() == "auto"
    mode_byte = 0x02 if profile.model_name in {"H7105", "H7107"} else 0x03
    return pt_real(build_frame_b64(0x05, [0x00, mode_byte if automatic else 0x01]))


DEHUMIDIFIER_MODES: dict[str, int] = {
    "low": 0x01,
    "high": 0x02,
    "auto": 0x03,
    "dryer": 0x08,
}


def dehumidifier_mode(mode: str) -> WireCommand:
    """Build a dehumidifier work-mode command."""
    value = DEHUMIDIFIER_MODES.get(mode.lower(), 0x03)
    return pt_real(build_frame_b64(0x05, [0x00, value]))


def oscillation(profile: DeviceProfile, on: bool) -> WireCommand:
    """Build a swing/oscillation command for tower fans and heaters."""
    if profile.kind == KIND_HEATER and profile.model_name not in HEATER2_MODELS:
        return pt_real(build_frame_b64(0x18, [1 if on else 0]))
    command = "multiSync" if profile.kind == KIND_HEATER else "ptReal"
    return pt_real(build_frame(0x1F, [0x01, 1 if on else 0]), cmd=command)


def heater_power(profile: DeviceProfile, on: bool) -> WireCommand:
    """Build a heater power command (register 0x01, not the turn command)."""
    command = "multiSync" if profile.model_name in HEATER2_MODELS else "ptReal"
    return pt_real(build_frame(0x01, [1 if on else 0]), cmd=command)


def heater_speed(profile: DeviceProfile, level: int) -> WireCommand:
    """Build a heater fan-speed command.

    Heater1 puts the 1-3 level directly in register 0x05. Heater2 uses the
    0x3A opcode and its own fan-only/low/medium/high sub-commands.
    """
    if profile.model_name in HEATER2_MODELS:
        level = max(1, min(4, level))
        if level == 1:
            frame = build_frame(0x05, [0x09], opcode=0x3A)
        else:
            frame = build_frame(0x05, [0x01, level - 1], opcode=0x3A)
        return pt_real(frame, cmd="multiSync")
    return pt_real(build_frame_b64(0x05, [max(1, min(3, level))]))


def heater_target(profile: DeviceProfile, celsius: float) -> WireCommand:
    """Build a heater target-temperature command.

    The wire value is hundredths of a degree Fahrenheit with bit 15 set as the
    positive-value flag. Heater1 puts it after a two-byte mode header on
    register 0x1A; heater2 uses the 0x3A auto sub-command.
    """
    fahrenheit = celsius * 9 / 5 + 32
    raw = round(fahrenheit * 100) | 0x8000
    high, low = raw >> 8, raw & 0xFF
    if profile.model_name in HEATER2_MODELS:
        return pt_real(
            build_frame(0x05, [0x03, 0x01, high, low], opcode=0x3A),
            cmd="multiSync",
        )
    return pt_real(build_frame_b64(0x1A, [0x00, 0x00, high, low]))


def ice_power(profile: DeviceProfile, on: bool) -> WireCommand:
    """Build an ice-maker power command."""
    if profile.model_name == "H8120":
        return pt_real(build_frame_b64(0x01, [1 if on else 0]))
    if not on:
        return pt_real(build_frame_b64(0x19, [0]))
    return power(profile, on)


def effect(frames: list[Any]) -> WireCommand:
    """Build an effect command from its opcode frames.

    Effect libraries expose opcodes as arrays of byte values. Each frame is
    turned into the base64 string the ``ptReal`` command expects.
    """
    encoded: list[str] = []
    for frame in frames:
        if isinstance(frame, str):
            encoded.append(frame)
        else:
            encoded.append(bytes_to_base64(bytes(int(value) & 0xFF for value in frame)))
    return pt_real(encoded)


def ice_size(profile: DeviceProfile, size: str) -> WireCommand:
    """Build an ice-size command."""
    sizes = profile.ice_sizes or ("small", "medium", "large")
    try:
        index = sizes.index(size.lower()) + 1
    except ValueError:
        index = 1
    if profile.model_name not in {"H8121", "H8122"}:
        index = len(sizes) + 1 - index
    return pt_real(build_frame_b64(0x05, [index]))


def kelvin_to_rgb(kelvin: int) -> tuple[int, int, int]:
    """Approximate the RGB value matching a colour temperature.

    Govee wants a colour alongside the kelvin value for several models. The
    approximation is only used as a fallback; the kelvin field is what the
    device actually honours.
    """
    temperature = max(1000, min(40000, kelvin)) / 100
    red = 255 if temperature <= 66 else 329.698727446 * (temperature - 60) ** (-0.1332047592)
    if temperature <= 66:
        green = 99.4708025861 * math.log(temperature) - 161.1195681661
    else:
        green = 288.1221695283 * ((temperature - 60) ** -0.0755148492)
    if temperature >= 66:
        blue = 255
    elif temperature <= 19:
        blue = 0
    else:
        blue = 138.5177312231 * math.log(temperature - 10) - 305.0447927307
    return (
        max(0, min(255, round(red))),
        max(0, min(255, round(green))),
        max(0, min(255, round(blue))),
    )
