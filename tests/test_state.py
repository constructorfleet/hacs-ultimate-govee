"""Tests for status message decoding."""

from __future__ import annotations

from custom_components.ultimate_govee.profiles import profile_for
from custom_components.ultimate_govee.protocol.codec import build_frame_b64, bytes_to_base64
from custom_components.ultimate_govee.protocol.state import decode_message


def test_light_state_object() -> None:
    result = decode_message(
        profile_for("H6001"),
        {
            "state": {
                "onOff": 1,
                "brightness": 40,
                "colorTemInKelvin": 4000,
                "color": {"r": 10, "g": 20, "b": 30},
            }
        },
    )

    assert result["power"] is True
    assert result["brightness"] == 40
    assert result["color_temp"] == 4000
    assert result["color"] == (10, 20, 30)


def test_light_state_object_uses_scaled_brightness() -> None:
    result = decode_message(
        profile_for("H6002"),
        {"state": {"brightness": 127}},
    )

    assert result["brightness"] == 50


def test_double_encoded_message() -> None:
    payload = '{"msg": "{\\"state\\": {\\"onOff\\": 1}}"}'

    assert decode_message(profile_for("H6001"), payload)["power"] is True


def test_command_frames() -> None:
    frame = build_frame_b64(0x01, [0x01])

    result = decode_message(
        profile_for("H6001"),
        {"device": "AA:BB", "op": {"command": [frame]}},
    )

    assert result["power"] is True


def test_humidifier_frame_reports_mode_speed_and_target() -> None:
    profile = profile_for("H7142")

    manual = decode_message(profile, {"op": {"command": [build_frame_b64(0x05, [0x01, 0x05])]}})
    auto = decode_message(profile, {"op": {"command": [build_frame_b64(0x05, [0x03, 0x32])]}})

    assert manual["mode"] == "manual"
    assert manual["fan_speed"] == 5
    assert auto["mode"] == "auto"
    assert auto["target_humidity"] == 50


def test_purifier_h7120_speed_report() -> None:
    result = decode_message(
        profile_for("H7120"),
        {"op": {"command": [build_frame_b64(0x05, [0x01, 0x03])]}},
    )

    assert result["fan_speed"] == 3
    assert result["percentage"] == 75


def test_purifier_3a_family_speed_report() -> None:
    result = decode_message(
        profile_for("H7123"),
        {"op": {"command": [build_frame_b64(0x05, [0x03, 0x00], opcode=0x3A)]}},
    )

    assert result["mode"] == "auto"
    assert result["percentage"] == 100


def test_co2_frame() -> None:
    # 23.5 C, 56 %, 800 ppm, little endian after AA 0A.
    frame = bytes([0xAA, 0x0A, 0x2E, 0x09, 0xE0, 0x15, 0x20, 0x03])

    result = decode_message(
        profile_for("H5140"),
        {"op": {"command": [bytes_to_base64(frame)]}},
    )

    assert result["temperature"] == 23.5
    assert result["humidity"] == 56
    assert result["co2"] == 800


def test_monitor_frame_fixture() -> None:
    fixture = bytes.fromhex("092e0000000000000015b800000000000000000c")

    result = decode_message(
        profile_for("H5106"),
        {"op": {"command": [bytes_to_base64(fixture)]}},
    )

    assert result["temperature"] == 23.5
    assert result["humidity"] == 55.6
    assert result["pm25"] == 12


def test_double_switch_gangs() -> None:
    result = decode_message(profile_for("H5082"), {"state": {"onOff": 2}})

    assert result["gangs"] == (False, True)
    assert result["power"] is True


def test_triple_switch_gangs() -> None:
    result = decode_message(profile_for("H5160"), {"state": {"onOff": 0x11}})

    assert result["gangs"] == (True, False, False)
    assert result["power"] is True


def test_water_shortage_from_sta() -> None:
    result = decode_message(
        profile_for("H7141"),
        {"state": {"sta": {"curTem": 21.5, "setTem": 50, "stc": [6, 1]}}},
    )

    assert result["water_shortage"] is True
    assert result["temperature"] == 21.5


def test_top_level_sensor_fields() -> None:
    result = decode_message(
        profile_for("H5051"),
        {"temperature": 2350, "humidity": 5600, "battery": 90},
    )

    assert result["temperature"] == 23.5
    assert result["humidity"] == 56
    assert result["battery"] == 90


def test_heater1_speed_and_swing_report() -> None:
    profile = profile_for("H7130")

    speed = decode_message(profile, {"op": {"command": [build_frame_b64(0x05, [0x02])]}})
    swing = decode_message(profile, {"op": {"command": [build_frame_b64(0x18, [0x01])]}})

    assert speed["fan_speed"] == 2
    assert speed["percentage"] == 66
    assert speed["mode"] == "medium"
    assert swing["oscillation"] is True


def test_heater2_speed_swing_and_lock_report() -> None:
    profile = profile_for("H7131")

    fan_only = decode_message(profile, {"op": {"command": [build_frame_b64(0x05, [0x09])]}})
    high = decode_message(profile, {"op": {"command": [build_frame_b64(0x05, [0x01, 0x03])]}})
    swing = decode_message(
        profile, {"op": {"command": [build_frame_b64(0x1F, [0x00, 0x01, 0x01])]}}
    )

    assert fan_only["percentage"] == 25
    assert fan_only["mode"] == "fan-only"
    assert high["fan_speed"] == 4
    assert high["percentage"] == 100
    assert swing["oscillation"] is True
    assert swing["lock"] is True


def test_ceiling_fan_report_sets_power_and_speed() -> None:
    result = decode_message(
        profile_for("H1310"),
        {"op": {"command": [build_frame_b64(0x31, [0x01, 0x03, 0x01, 0, 0, 0, 0, 0x01])]}},
    )

    assert result["power"] is True
    assert result["percentage"] == 50


def test_ice_size_report_maps_model_direction() -> None:
    older = decode_message(
        profile_for("H7172"),
        {"op": {"command": [build_frame_b64(0x05, [0x01])]}},
    )
    newer = decode_message(
        profile_for("H8121"),
        {"op": {"command": [build_frame_b64(0x05, [0x03])]}},
    )

    assert older["ice_size"] == "large"
    assert newer["ice_size"] == "large"


def test_dehumidifier_mode_report() -> None:
    result = decode_message(
        profile_for("H7150"),
        {"op": {"command": [build_frame_b64(0x05, [0x00, 0x08])]}},
    )

    assert result["mode"] == "dryer"
