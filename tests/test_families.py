"""Per-SKU dialect assignment, collision ordering and round-trip tests.

Round trips are only asserted where the shipped handler proves an inverse.
Command frames that the integration never decodes as a report (heater2 target
and swing, ice power-off) are checked as golden bytes instead of inventing a
report layout.
"""

from __future__ import annotations

import pytest

from custom_components.ultimate_govee.models import DeviceState
from custom_components.ultimate_govee.profiles import (
    KIND_CEILING_FAN,
    KIND_SWITCH,
    KIND_TV,
    SKU_DIALECTS,
    profile_for,
)
from custom_components.ultimate_govee.protocol import commands
from custom_components.ultimate_govee.protocol.codec import bytes_to_base64
from custom_components.ultimate_govee.protocol.command import ACTION_FRAMES, STRATEGY_MULTI_SYNC
from custom_components.ultimate_govee.protocol.families import DIALECTS, dialect_for
from custom_components.ultimate_govee.protocol.state import decode_message


def _frames(command: commands.Command) -> list[bytes]:
    assert command.action == ACTION_FRAMES
    return list(command.parameters["frames"])


def _frame(command: commands.Command) -> bytes:
    return _frames(command)[0]


def _report(sku: str, frame: bytes) -> DeviceState:
    return decode_message(
        profile_for(sku),
        {"op": {"command": [bytes_to_base64(frame)]}},
    )


@pytest.mark.parametrize(
    ("sku", "dialect", "kind"),
    [
        ("H1310", "ceiling_fan", KIND_CEILING_FAN),
        ("R1310", "ceiling_fan", KIND_CEILING_FAN),
        ("H1161", "generic", KIND_TV),
        ("H1162", "generic", KIND_TV),
        ("H1163", "generic", KIND_TV),
        ("H1167", "generic", KIND_TV),
        ("H1168", "generic", KIND_TV),
        ("H7014", "generic", KIND_SWITCH),
        ("H7100", "fan", "fan"),
        ("H7105", "fan_h7105", "fan"),
        ("H7130", "heater1", "heater"),
        ("H7131", "heater2", "heater"),
        ("H7141", "humidifier_h7141", "humidifier"),
        ("H7142", "humidifier_h7142", "humidifier"),
        ("H7120", "purifier_h7120", "purifier"),
        ("H7123", "purifier_3a", "purifier"),
        ("H7126", "purifier_h7126", "purifier"),
        ("H7150", "dehumidifier", "dehumidifier"),
        ("H7172", "ice_maker", "ice_maker"),
        ("H8120", "ice_maker_h8120", "ice_maker"),
        ("H8121", "ice_maker_ascending", "ice_maker"),
    ],
)
def test_dialects_are_assigned_per_sku(sku: str, dialect: str, kind: str) -> None:
    profile = profile_for(sku)

    assert profile.dialect == dialect
    assert profile.kind == kind
    assert dialect_for(profile).name == dialect


def test_dialect_names_all_have_an_implementation() -> None:
    assert set(SKU_DIALECTS.values()) <= set(DIALECTS)
    for sku in ("H1310", "H7130", "H7131", "H7141", "H7142", "H7123", "H7172"):
        assert profile_for(sku).dialect in DIALECTS


def test_every_dialect_records_its_evidence_level() -> None:
    for dialect in DIALECTS.values():
        assert dialect.source
        assert dialect.confidence in {"low", "medium", "high"}


def test_h7141_and_h7142_are_separate_dialects() -> None:
    first = profile_for("H7141")
    second = profile_for("H7142")

    assert first.dialect != second.dialect
    assert first.family == second.family == "humidifier"
    assert "uv" not in first.features
    assert "uv" in second.features


def test_prefix_collisions_do_not_select_a_dialect() -> None:
    # H1310/R1310 look like H1/R1 lights but are ceiling fans.
    assert profile_for("H1310").dialect == profile_for("R1310").dialect == "ceiling_fan"
    # The H116x set is a TV set despite the H1 prefix.
    assert {profile_for(sku).dialect for sku in ("H1161", "H1163", "H1167", "H1168")} == {"generic"}
    # H7014 is a switch despite the H70 prefix.
    assert profile_for("H7014").kind == KIND_SWITCH


def test_h7141_round_trips_its_mode_and_mist_registers() -> None:
    profile = profile_for("H7141")

    manual = _frame(commands.mist_level(profile, 5))
    target = _frame(commands.humidifier_target(profile, 50))

    manual_state = _report("H7141", manual)
    assert manual_state.mode == "manual"
    assert manual_state.fan_speed == 5

    target_state = _report("H7141", target)
    assert target_state.mode == "auto"
    assert target_state.target_humidity == 50


def test_h7142_round_trips_uv_and_night_light_overrides() -> None:
    profile = profile_for("H7142")

    uv_state = _report("H7142", _frame(commands.uv(profile, True)))
    assert uv_state.uv is True

    light = _frame(commands.night_light(profile, True, 40, (10, 20, 30)))
    light_state = _report("H7142", light)
    assert light_state.night_light is True
    assert light_state.night_light_brightness == 40
    assert light_state.night_light_color == (10, 20, 30)

    off = _report("H7142", _frame(commands.night_light(profile, False)))
    assert off.night_light is False


def test_heater1_round_trips_power_speed_target_swing_and_lock() -> None:
    profile = profile_for("H7130")

    assert _report("H7130", _frame(commands.heater_power(profile, True))).power is True
    speed = _report("H7130", _frame(commands.heater_speed(profile, 2)))
    assert (speed.fan_speed, speed.percentage, speed.mode) == (2, 66, "medium")
    assert _report("H7130", _frame(commands.heater_target(profile, 20))).target_temperature == 20
    assert _report("H7130", _frame(commands.oscillation(profile, True))).oscillation is True
    assert _report("H7130", _frame(commands.lock(profile, True))).lock is True


def test_heater2_round_trips_its_speed_layout() -> None:
    profile = profile_for("H7131")

    fan_only = commands.heater_speed(profile, 1)
    assert fan_only.parameters["strategy"] == STRATEGY_MULTI_SYNC
    assert _report("H7131", _frame(fan_only)).mode == "fan-only"

    high = _report("H7131", _frame(commands.heater_speed(profile, 4)))
    assert (high.fan_speed, high.percentage, high.mode) == (4, 100, "high")
    assert _report("H7131", _frame(commands.heater_power(profile, True))).power is True


def test_heater2_night_light_is_a_golden_frame_sequence() -> None:
    profile = profile_for("H7131")

    off = _frames(commands.night_light(profile, False))
    on = _frames(commands.night_light(profile, True, 40, (10, 20, 30)))

    assert [frame[:4] for frame in off] == [bytes([0x33, 0x1B, 0x01, 0x01])]
    assert [frame[:5] for frame in on] == [
        bytes([0x33, 0x1B, 0x01, 0x01, 0x01]),
        bytes([0x33, 0x1B, 0x01, 0x02, 0x28]),
        bytes([0x33, 0x1B, 0x05, 0x0D, 0x0A]),
    ]


def test_heater2_target_and_swing_are_golden_frames() -> None:
    """No verified report inverse exists; lock the command bytes instead."""
    profile = profile_for("H7131")

    target = _frame(commands.heater_target(profile, 20))
    assert target[:4] == bytes([0x3A, 0x05, 0x03, 0x01])
    assert ((target[4] << 8) | target[5]) & 0x8000

    assert _frame(commands.oscillation(profile, True))[:4] == bytes([0x33, 0x1F, 0x01, 0x01])
    assert _frame(commands.lock(profile, True))[:4] == bytes([0x33, 0x1F, 0x02, 0x01])


def test_purifier_speed_round_trips_per_dialect() -> None:
    three_a = _report("H7123", _frame(commands.purifier_speed(profile_for("H7123"), 60)))
    assert (three_a.mode, three_a.percentage) == ("medium", 60)

    h7126 = _report("H7126", _frame(commands.purifier_speed(profile_for("H7126"), 90)))
    assert (h7126.mode, h7126.percentage) == ("high", 99)

    # H7120 encodes sleep as the special gear 0x10; the existing report
    # decoder reads it as the top gear, so only the command bytes are locked.
    gear = _frame(commands.purifier_speed(profile_for("H7120"), 25))
    assert gear[:3] == bytes([0x33, 0x05, 0x10])


def test_dehumidifier_speed_and_mode_round_trip() -> None:
    profile = profile_for("H7150")

    speed = _report("H7150", _frame(commands.fan_speed(profile, 3)))
    assert (speed.fan_speed, speed.percentage) == (3, 38)

    dryer = _report("H7150", _frame(commands.dehumidifier_mode(profile, "dryer")))
    assert dryer.mode == "dryer"


def test_purifier_accessory_registers_round_trip() -> None:
    profile = profile_for("H7120")

    assert _report("H7120", _frame(commands.night_light(profile, True))).night_light is True
    assert _report("H7120", _frame(commands.display(profile, True))).display is True
    assert _report("H7120", _frame(commands.lock(profile, True))).lock is True


def test_ice_size_round_trips_in_both_directions() -> None:
    older = _report("H7172", _frame(commands.ice_size(profile_for("H7172"), "large")))
    newer = _report("H8121", _frame(commands.ice_size(profile_for("H8121"), "large")))

    assert older.ice_size == "large"
    assert newer.ice_size == "large"


def test_ice_maker_power_golden_frames() -> None:
    assert _frame(commands.ice_power(profile_for("H8120"), True))[:3] == bytes([0x33, 0x01, 0x01])
    # The older handler turns off with the 0x19 register and on with ``turn``.
    assert _frame(commands.ice_power(profile_for("H7172"), False))[:3] == bytes([0x33, 0x19, 0x00])
    assert commands.ice_power(profile_for("H7172"), True).action == "power"


def test_ceiling_fan_round_trips_speed_and_power() -> None:
    profile = profile_for("H1310")

    speed = _report("H1310", _frame(commands.fan_speed(profile, 4)))
    assert (speed.power, speed.fan_speed, speed.percentage) == (True, 4, 67)

    off = _report("H1310", _frame(commands.fan_power(profile, False, 4)))
    assert (off.power, off.fan_speed) == (False, 4)


def test_r1310_uses_the_same_ceiling_fan_bytes() -> None:
    h1310 = _frame(commands.fan_speed(profile_for("H1310"), 3))
    r1310 = _frame(commands.fan_speed(profile_for("R1310"), 3))

    assert h1310 == r1310


def test_fan_auto_mode_byte_is_assigned_per_observed_variant() -> None:
    default = _frame(commands.fan_mode(profile_for("H7100"), "auto"))
    special = _frame(commands.fan_mode(profile_for("H7105"), "auto"))

    assert default[:4] == bytes([0x33, 0x05, 0x00, 0x03])
    assert special[:4] == bytes([0x33, 0x05, 0x00, 0x02])


def test_fan_night_light_is_a_golden_frame_sequence() -> None:
    profile = profile_for("H7105")

    off = _frames(commands.night_light(profile, False))
    on = _frames(commands.night_light(profile, True, 50, (1, 2, 3)))

    assert [frame[:5] for frame in off] == [bytes([0x3A, 0x1B, 0x01, 0x01, 0x00])]
    assert [frame[:5] for frame in on] == [
        bytes([0x3A, 0x1B, 0x01, 0x01, 0x01]),
        bytes([0x3A, 0x1B, 0x01, 0x02, 0x32]),
        bytes([0x3A, 0x05, 0x0D, 0x01, 0x02]),
    ]
