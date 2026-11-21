"""Tests for tap-to-run parsing."""

from __future__ import annotations

import json

from custom_components.ultimate_govee.tap_to_runs import parse_tap_to_runs

TOPIC = "GA/0123456789abcdef0123456789abcdef"

TURN_ON_RULE = {
    "iotMsg": json.dumps(
        {
            "msg": {
                "type": 1,
                "data": {"val": 1},
                "accountTopic": TOPIC,
                "transaction": "v_1",
                "cmdVersion": 0,
                "cmd": "turn",
                "origin": 35,
            }
        }
    )
}

SCENE_RULE = {
    "iotMsg": json.dumps(
        {
            "msg": {
                "type": 1,
                "data": {
                    "command": [
                        "owABAgIBHQAAAAECAf//AAAAALw=",
                        "o/8A9JYC////j///AAAAAAAAAEw=",
                        "MwUEnAkAAAAAAAAAAAAAAAAAAKc=",
                    ]
                },
                "accountTopic": TOPIC,
                "transaction": "v_2",
                "cmdVersion": 0,
                "cmd": "ptReal",
                "origin": 35,
            }
        }
    )
}

PRESET_RULE = {
    "name": "Meditation Scene",
    "effectCommand": json.dumps(
        {
            "cmdVersion": 0,
            "data": {"command": ["owABBQICIwACCAMCAf+WAAAAAOc="]},
            "cmd": "ptReal",
            "type": 1,
        }
    ),
}


def test_user_tap_to_run_from_iot_rules() -> None:
    runs = parse_tap_to_runs(
        [
            {
                "oneClicks": [
                    {
                        "name": "SceneSwitch",
                        "iotRules": [
                            {
                                "deviceObj": {"name": "Hobbyraum", "sku": "H6076"},
                                "rule": [TURN_ON_RULE, SCENE_RULE],
                            }
                        ],
                    }
                ]
            }
        ]
    )

    assert len(runs) == 1
    assert runs[0].name == "SceneSwitch"
    assert [action.command for action in runs[0].actions] == ["turn", "ptReal"]
    assert runs[0].actions[0].data == {"val": 1}
    assert runs[0].actions[0].device_name == "Hobbyraum"
    assert runs[0].actions[0].sku == "H6076"
    assert runs[0].actions[1].data["command"][0].startswith("owAB")


def test_preset_tap_to_run_from_exec_rules_and_effect_command() -> None:
    runs = parse_tap_to_runs(
        [
            {
                "oneClicks": [
                    {
                        "name": "Meditation",
                        "execRules": [
                            {
                                "name": "Turn on Meditation Scene",
                                "devices": [
                                    {"sku": "H6076", "deviceName": "Lamp A", "rule": PRESET_RULE},
                                    {"sku": "H6076", "deviceName": "Lamp B", "rule": PRESET_RULE},
                                ],
                            }
                        ],
                    }
                ]
            }
        ]
    )

    assert len(runs) == 1
    assert runs[0].name == "Meditation"
    assert len(runs[0].actions) == 2
    assert runs[0].actions[0].command == "ptReal"
    assert runs[0].actions[0].device_name == "Lamp A"
    assert runs[0].actions[0].cmd_version == 0
    assert runs[0].actions[0].msg_type == 1


def test_malformed_or_empty_rules_are_skipped() -> None:
    runs = parse_tap_to_runs(
        [
            {"oneClicks": [{"name": "Empty"}]},
            {
                "oneClicks": [
                    {
                        "name": "Broken",
                        "iotRules": [{"deviceObj": {}, "rule": [{"iotMsg": "{not json"}]}],
                        "execRules": [{"devices": [{"sku": "H6076"}]}],
                    }
                ]
            },
        ]
    )

    assert runs == []


def test_duplicate_one_click_names_get_distinct_keys() -> None:
    one_click = {
        "name": "Party",
        "iotRules": [{"deviceObj": {"name": "Lamp", "sku": "H6076"}, "rule": [TURN_ON_RULE]}],
    }

    runs = parse_tap_to_runs([{"oneClicks": [one_click, one_click]}])

    assert len(runs) == 2
    assert runs[0].key != runs[1].key
