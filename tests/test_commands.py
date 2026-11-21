"""Tests for command builders and family-dialect dispatch."""

from __future__ import annotations

from custom_components.ultimate_govee.profiles import profile_for
from custom_components.ultimate_govee.protocol import commands
from custom_components.ultimate_govee.protocol.codec import decode_frame
from custom_components.ultimate_govee.protocol.command import (
    ACTION_BRIGHTNESS,
    ACTION_COLOR,
    ACTION_FRAMES,
    ACTION_POWER,
    STRATEGY_MULTI_SYNC,
    STRATEGY_PT_REAL,
)


def _single_frame(command: commands.Command) -> bytes:
    return command.parameters["frames"][0]


def test_power_is_a_transport_neutral_intent() -> None:
    on = commands.power(profile_for("H6001"), True)
    off = commands.power(profile_for("H6001"), False)

    assert on.action == ACTION_POWER
    assert on.parameters == {"on": True}
    assert off.parameters == {"on": False}


def test_switch_power_override_stays_in_the_profile() -> None:
    profile = profile_for("H5080")

    assert profile.power_on == 17
    assert commands.power(profile, True).parameters == {"on": True}


def test_gang_power_keeps_the_gang_on_the_intent() -> None:
    profile = profile_for("H5160")

    assert commands.gang_power(profile, 0, True).parameters == {"on": True, "channel": 0}
    assert commands.gang_power(profile, 1, True).parameters == {"on": True, "channel": 1}
    assert commands.gang_power(profile, 2, True).parameters == {"on": True, "channel": 2}


def test_brightness_is_a_percentage_intent() -> None:
    assert commands.brightness(profile_for("H6002"), 50).action == ACTION_BRIGHTNESS
    assert commands.brightness(profile_for("H6002"), 50).parameters == {"percent": 50}
    assert commands.brightness(profile_for("H6001"), 150).parameters == {"percent": 100}


def test_colour_intent() -> None:
    command = commands.color(10, 20, 30)

    assert command.action == ACTION_COLOR
    assert command.parameters == {"rgb": (10, 20, 30), "kelvin": 0}


def test_colour_temperature_includes_rgb_hint() -> None:
    command = commands.color_temp(4000)
    red, green, blue = command.parameters["rgb"]

    assert command.parameters["kelvin"] == 4000
    assert 0 <= red <= 255
    assert 0 <= green <= 255
    assert 0 <= blue <= 255


def test_humidifier_night_light_frame() -> None:
    register, payload = decode_frame(
        _single_frame(commands.night_light(profile_for("H7140"), True, 40))
    )

    assert register == 0x1B
    assert payload[:5] == bytes([1, 40, 255, 255, 255])


def test_h7142_night_light_override() -> None:
    command = commands.night_light(profile_for("H7142"), True, 40)
    register, payload = decode_frame(_single_frame(command))

    assert command.parameters["strategy"] == STRATEGY_PT_REAL
    assert register == 0x1B
    assert payload[:5] == bytes([1, 40, 255, 255, 255])


def test_purifier_night_light_and_lock_registers() -> None:
    purifier = profile_for("H7120")

    assert decode_frame(_single_frame(commands.night_light(purifier, True)))[0] == 0x18
    assert decode_frame(_single_frame(commands.lock(purifier, True)))[0] == 0x10
    assert decode_frame(_single_frame(commands.lock(profile_for("H7142"), True)))[0] == 0x0A


def test_purifier_speed_families() -> None:
    h7120 = commands.purifier_speed(profile_for("H7120"), 25)
    h7123 = commands.purifier_speed(profile_for("H7123"), 60)
    h7126 = commands.purifier_speed(profile_for("H7126"), 90)

    assert _single_frame(h7120)[:3] == bytes([0x33, 0x05, 0x10])
    assert _single_frame(h7123)[0] == 0x3A
    assert _single_frame(h7123)[2:4] == bytes([0x01, 0x02])
    assert _single_frame(h7126)[:4] == bytes([0x33, 0x05, 0x01, 0x03])


def test_ceiling_fan_commands() -> None:
    profile = profile_for("H1310")

    assert _single_frame(commands.fan_speed(profile, 4))[:3] == bytes([0x33, 0x31, 0x01])
    assert _single_frame(commands.fan_power(profile, False, 4))[:3] == bytes([0x33, 0x31, 0x00])


def test_oscillation() -> None:
    assert _single_frame(commands.oscillation(profile_for("H7100"), True))[:4] == bytes(
        [0x33, 0x1F, 0x01, 0x01]
    )


def test_heater_target_uses_fahrenheit_hundredths() -> None:
    register, payload = decode_frame(
        _single_frame(commands.heater_target(profile_for("H7130"), 20))
    )

    assert register == 0x1A
    raw = (payload[2] << 8) | payload[3]
    assert raw & 0x8000
    assert round((raw & 0x7FFF) / 100) == 68


def test_heater1_power_and_speed() -> None:
    profile = profile_for("H7130")

    assert _single_frame(commands.heater_power(profile, True))[:3] == bytes([0x33, 0x01, 0x01])
    assert _single_frame(commands.heater_speed(profile, 2))[:3] == bytes([0x33, 0x05, 0x02])
    assert commands.heater_speed(profile, 2).parameters["strategy"] == STRATEGY_PT_REAL
    assert _single_frame(commands.oscillation(profile, True))[:3] == bytes([0x33, 0x18, 0x01])
    assert _single_frame(commands.lock(profile, True))[:3] == bytes([0x33, 0x10, 0x01])


def test_heater2_commands_use_multisync_and_3a_opcode() -> None:
    profile = profile_for("H7131")

    power = commands.heater_power(profile, True)
    assert power.action == ACTION_FRAMES
    assert power.parameters["strategy"] == STRATEGY_MULTI_SYNC
    assert _single_frame(power)[:3] == bytes([0x33, 0x01, 0x01])

    fan_only = commands.heater_speed(profile, 1)
    assert fan_only.parameters["strategy"] == STRATEGY_MULTI_SYNC
    assert _single_frame(fan_only)[:3] == bytes([0x3A, 0x05, 0x09])

    high = _single_frame(commands.heater_speed(profile, 4))
    assert high[:4] == bytes([0x3A, 0x05, 0x01, 0x03])

    target = _single_frame(commands.heater_target(profile, 20))
    assert target[:4] == bytes([0x3A, 0x05, 0x03, 0x01])
    assert ((target[4] << 8) | target[5]) & 0x8000


def test_ice_size_reverses_only_for_older_models() -> None:
    older = _single_frame(commands.ice_size(profile_for("H7172"), "large"))
    newer = _single_frame(commands.ice_size(profile_for("H8121"), "large"))

    assert older[2] == 1
    assert newer[2] == 3


def test_ice_power_uses_register_for_h8120() -> None:
    on = commands.ice_power(profile_for("H8120"), True)
    off = commands.ice_power(profile_for("H7172"), False)
    on_legacy = commands.ice_power(profile_for("H7172"), True)

    assert _single_frame(on)[:3] == bytes([0x33, 0x01, 0x01])
    assert _single_frame(off)[:3] == bytes([0x33, 0x19, 0x00])
    assert on_legacy.action == ACTION_POWER


def test_effect_frames_are_base64_encoded() -> None:
    command = commands.effect([[0x33, 0x05, 0x02, 0x00, 0x01]])

    assert command.action == ACTION_FRAMES
    assert command.parameters["strategy"] == STRATEGY_PT_REAL
    assert _single_frame(command)[:5] == bytes([0x33, 0x05, 0x02, 0x00, 0x01])
