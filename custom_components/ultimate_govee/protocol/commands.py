"""Command builders and family-dialect dispatch.

Builders turn entity intent into a transport-neutral :class:`~.command.Command`.
Family-specific bytes are delegated to the dialect assigned to the SKU; the
cloud/LAN/BLE adapters encode the resulting intent into their own wire form.
"""

from __future__ import annotations

import math
from typing import Any

from ..profiles import DeviceProfile
from .codec import build_frame_b64, bytes_to_base64
from .command import (
    ACTION_DEHUMIDIFIER_MODE,
    ACTION_DISPLAY,
    ACTION_FAN_MODE,
    ACTION_FAN_POWER,
    ACTION_FAN_SPEED,
    ACTION_HEATER_POWER,
    ACTION_HEATER_SPEED,
    ACTION_HEATER_TARGET,
    ACTION_HUMIDIFIER_MODE,
    ACTION_HUMIDIFIER_TARGET,
    ACTION_ICE_POWER,
    ACTION_ICE_SIZE,
    ACTION_LOCK,
    ACTION_MIST_LEVEL,
    ACTION_NIGHT_LIGHT,
    ACTION_OSCILLATION,
    ACTION_PURIFIER_MODE,
    ACTION_PURIFIER_SPEED,
    ACTION_UV,
    Command,
    brightness_command,
    color_command,
    frames_command,
    power_command,
)
from .families import GENERIC, dialect_for


class UnsupportedCommand(ValueError):
    """The profile's dialect has no encoding for an action."""


def _dispatch(profile: DeviceProfile, action: str, parameters: dict[str, Any]) -> Command:
    """Encode ``action`` with the SKU's dialect, then the generic fallback."""
    command = dialect_for(profile).encode(profile, action, parameters)
    if command is None:
        command = GENERIC.encode(profile, action, parameters)
    if command is None:
        raise UnsupportedCommand(f"{action} has no encoding for {profile.model_name}")
    return command


def power(profile: DeviceProfile, on: bool) -> Command:
    """Build a power command."""
    return power_command(on=on)


def gang_power(profile: DeviceProfile, gang: int, on: bool) -> Command:
    """Build a per-gang power command for a double or triple outlet.

    Govee encodes the gang in the magic ``turn`` value rather than in a frame:
    17/16 for gang 1, 34/32 for gang 2 and 68/64 for gang 3. The index is kept
    on the intent; each transport applies the values it needs.
    """
    return power_command(on=on, channel=max(0, min(2, gang)))


def brightness(profile: DeviceProfile, percent: int) -> Command:
    """Build a brightness command on Home Assistant's 0-100 scale."""
    return brightness_command(percent)


def color(red: int, green: int, blue: int) -> Command:
    """Build a colour command."""
    return color_command(rgb=(red, green, blue))


def color_temp(kelvin: int) -> Command:
    """Build a tunable-white command."""
    return color_command(rgb=kelvin_to_rgb(kelvin), kelvin=kelvin)


def pt_real(
    command: str | bytes | list[str] | list[bytes],
    *,
    lan: bool = True,
    cmd: str = "ptReal",
) -> Command:
    """Build a raw frame command from base64 strings or raw frame bytes."""
    return frames_command(command, strategy=cmd, lan=lan)


def night_light(
    profile: DeviceProfile,
    on: bool,
    brightness_value: int = 100,
    rgb: tuple[int, int, int] = (255, 255, 255),
) -> Command:
    """Build a night-light command for the SKU's dialect."""
    return _dispatch(
        profile,
        ACTION_NIGHT_LIGHT,
        {"on": on, "brightness": brightness_value, "rgb": rgb},
    )


def display(profile: DeviceProfile, on: bool) -> Command:
    """Build a display toggle command (purifiers, register 0x16)."""
    return _dispatch(profile, ACTION_DISPLAY, {"on": on})


def lock(profile: DeviceProfile, on: bool) -> Command:
    """Build a child-lock command."""
    return _dispatch(profile, ACTION_LOCK, {"on": on})


def uv(profile: DeviceProfile, on: bool) -> Command:
    """Build a UVC command (H7142 family)."""
    return _dispatch(profile, ACTION_UV, {"on": on})


def timer(enabled: bool, minutes: int) -> Command:
    """Build a countdown timer command."""
    minutes = max(0, min(0xFFFF, minutes))
    return frames_command(
        build_frame_b64(0x0A, [0x0B, 1 if enabled else 0, minutes >> 8, minutes & 0xFF])
    )


def mist_level(profile: DeviceProfile, level: int) -> Command:
    """Build a manual mist-level command (1-9)."""
    return _dispatch(profile, ACTION_MIST_LEVEL, {"level": level})


def humidifier_mode(profile: DeviceProfile, mode: str) -> Command:
    """Build a humidifier work-mode command."""
    return _dispatch(profile, ACTION_HUMIDIFIER_MODE, {"mode": mode})


def humidifier_target(profile: DeviceProfile, target: int) -> Command:
    """Build an automatic target-humidity command."""
    return _dispatch(profile, ACTION_HUMIDIFIER_TARGET, {"target": target})


def purifier_speed(profile: DeviceProfile, percent: int) -> Command:
    """Build a purifier fan-speed command for the model's dialect."""
    return _dispatch(profile, ACTION_PURIFIER_SPEED, {"percent": percent})


def purifier_mode(profile: DeviceProfile, mode: str) -> Command:
    """Build a purifier work-mode command."""
    return _dispatch(profile, ACTION_PURIFIER_MODE, {"mode": mode})


def fan_power(profile: DeviceProfile, on: bool, speed: int = 1) -> Command:
    """Build a fan power command.

    Tower fans use the plain 0x01 power register. Ceiling fans have no separate
    power frame in the AWS protocol; their 0x31 command carries the current
    speed alongside the on/off flag.
    """
    return _dispatch(profile, ACTION_FAN_POWER, {"on": on, "level": speed})


def fan_speed(profile: DeviceProfile, level: int) -> Command:
    """Build a fan speed command from a 1-based level."""
    return _dispatch(profile, ACTION_FAN_SPEED, {"level": level})


def fan_mode(profile: DeviceProfile, mode: str) -> Command:
    """Build a fan auto/manual mode command for tower fans."""
    return _dispatch(profile, ACTION_FAN_MODE, {"mode": mode})


def dehumidifier_mode(profile: DeviceProfile, mode: str) -> Command:
    """Build a dehumidifier work-mode command."""
    return _dispatch(profile, ACTION_DEHUMIDIFIER_MODE, {"mode": mode})


def oscillation(profile: DeviceProfile, on: bool) -> Command:
    """Build a swing/oscillation command for tower fans and heaters."""
    return _dispatch(profile, ACTION_OSCILLATION, {"on": on})


def heater_power(profile: DeviceProfile, on: bool) -> Command:
    """Build a heater power command (register 0x01, not the turn command)."""
    return _dispatch(profile, ACTION_HEATER_POWER, {"on": on})


def heater_speed(profile: DeviceProfile, level: int) -> Command:
    """Build a heater fan-speed command."""
    return _dispatch(profile, ACTION_HEATER_SPEED, {"level": level})


def heater_target(profile: DeviceProfile, celsius: float) -> Command:
    """Build a heater target-temperature command."""
    return _dispatch(profile, ACTION_HEATER_TARGET, {"celsius": celsius})


def ice_power(profile: DeviceProfile, on: bool) -> Command:
    """Build an ice-maker power command."""
    return _dispatch(profile, ACTION_ICE_POWER, {"on": on})


def effect(frames: list[Any]) -> Command:
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


def ice_size(profile: DeviceProfile, size: str) -> Command:
    """Build an ice-size command."""
    return _dispatch(profile, ACTION_ICE_SIZE, {"size": size})


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
