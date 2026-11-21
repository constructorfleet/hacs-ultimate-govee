"""Transport-neutral command intents.

A :class:`Command` says *what* a device should do, never how one path spells
it. Each transport encodes the intent into its own wire form, and each family
dialect supplies the register frames for actions whose bytes differ by SKU.

``ptReal``, ``pt``, ``ptUrl`` and ``multiSync`` are strategies carried inside a
frame command, not transports; see ADR 0002.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .codec import frames_from_command

# Direct intents every appliance understands. A transport encodes these into
# its own fields (cloud ``turn``/``brightness``/``colorwc``, LAN ``turn`` …
# or BLE registers 0x01/0x04).
ACTION_POWER = "power"
ACTION_BRIGHTNESS = "brightness"
ACTION_COLOR = "color"

# A command already reduced to register frames by a family dialect.
ACTION_FRAMES = "frames"

# An account action whose wire shape is only defined by the cloud API. LAN and
# BLE decline it because they have no evidence for an encoding.
ACTION_CLOUD = "cloud"

# Family-specific actions. A dialect turns these into frames or, when the
# family uses a direct verb, into one of the direct intents above.
ACTION_ICE_POWER = "ice_power"
ACTION_ICE_SIZE = "ice_size"
ACTION_FAN_POWER = "fan_power"
ACTION_FAN_SPEED = "fan_speed"
ACTION_FAN_MODE = "fan_mode"
ACTION_NIGHT_LIGHT = "night_light"
ACTION_DISPLAY = "display"
ACTION_LOCK = "lock"
ACTION_UV = "uv"
ACTION_TIMER = "timer"
ACTION_OSCILLATION = "oscillation"
ACTION_HEATER_POWER = "heater_power"
ACTION_HEATER_SPEED = "heater_speed"
ACTION_HEATER_TARGET = "heater_target"
ACTION_MIST_LEVEL = "mist_level"
ACTION_HUMIDIFIER_MODE = "humidifier_mode"
ACTION_HUMIDIFIER_TARGET = "humidifier_target"
ACTION_PURIFIER_SPEED = "purifier_speed"
ACTION_PURIFIER_MODE = "purifier_mode"
ACTION_DEHUMIDIFIER_MODE = "dehumidifier_mode"

# Cloud command strategies that carry raw frames.
STRATEGY_PT_REAL = "ptReal"
STRATEGY_MULTI_SYNC = "multiSync"


@dataclass(frozen=True, slots=True)
class Command:
    """A transport-neutral command intent.

    ``parameters`` is action-specific. The direct intents use ``on``,
    ``channel``, ``percent``, ``rgb`` and ``kelvin``; frame commands carry
    ``frames``, ``strategy`` and ``lan``; the cloud passthrough carries
    ``command`` and ``data``.
    """

    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    cmd_version: int = 0
    msg_type: int = 1


def frames_command(
    frames: Any,
    *,
    strategy: str = STRATEGY_PT_REAL,
    lan: bool = True,
) -> Command:
    """Build a frame command from raw frame bytes."""
    return Command(
        ACTION_FRAMES,
        {
            "frames": tuple(frames_from_command(frames)),
            "strategy": strategy,
            "lan": lan,
        },
    )


def cloud_command(command: str, data: dict[str, Any] | None = None) -> Command:
    """Build a cloud passthrough command for an account-defined action."""
    return Command(ACTION_CLOUD, {"command": command, "data": dict(data or {})})


def power_command(*, on: bool, channel: int | None = None) -> Command:
    """Build a power intent for the whole device or one zero-based gang."""
    parameters: dict[str, Any] = {"on": on}
    if channel is not None:
        parameters["channel"] = channel
    return Command(ACTION_POWER, parameters)


def brightness_command(percent: int) -> Command:
    """Build a brightness intent on Home Assistant's 0-100 scale."""
    return Command(ACTION_BRIGHTNESS, {"percent": max(0, min(100, percent))})


def color_command(*, rgb: tuple[int, int, int], kelvin: int = 0) -> Command:
    """Build a colour or colour-temperature intent."""
    return Command(ACTION_COLOR, {"rgb": rgb, "kelvin": kelvin})
