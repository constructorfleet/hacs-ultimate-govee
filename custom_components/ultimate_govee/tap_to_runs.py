"""Parse Govee one-click/tap-to-run rules into publishable actions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

_WHITESPACE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class TapAction:
    """One device command contained in a tap-to-run."""

    device_name: str
    sku: str
    command: str
    data: dict[str, Any]
    cmd_version: int = 0
    msg_type: int = 1
    device_id: str | None = None


@dataclass(frozen=True, slots=True)
class TapToRun:
    """A named group of commands that should be sent together."""

    name: str
    actions: tuple[TapAction, ...]
    key: str


def parse_tap_to_runs(components: list[dict[str, Any]]) -> list[TapToRun]:
    """Flatten the BFF component response into tap-to-run entities."""
    runs: list[TapToRun] = []
    seen: set[str] = set()

    for component in components:
        one_clicks = component.get("oneClicks")
        if not isinstance(one_clicks, list):
            continue
        for one_click in one_clicks:
            if not isinstance(one_click, dict):
                continue
            actions = _one_click_actions(one_click)
            if not actions:
                continue
            name = str(one_click.get("name") or "Tap to run").strip()
            base = _slug(name) or "tap_to_run"
            key = base
            counter = 2
            while key in seen:
                key = f"{base}_{counter}"
                counter += 1
            seen.add(key)
            runs.append(TapToRun(name=name, actions=tuple(actions), key=key))

    return runs


def _one_click_actions(one_click: dict[str, Any]) -> list[TapAction]:
    actions: list[TapAction] = []

    for iot_rule in _dict_list(one_click.get("iotRules")):
        device = iot_rule.get("deviceObj")
        device = device if isinstance(device, dict) else {}
        name = _text(device.get("name") or iot_rule.get("deviceName"))
        sku = _text(device.get("sku") or iot_rule.get("sku"))
        device_id = _text(
            device.get("device")
            or device.get("deviceId")
            or iot_rule.get("device")
            or iot_rule.get("deviceId")
        )
        for rule in _dict_list(iot_rule.get("rule")):
            action = _rule_action(rule, name, sku, device_id)
            if action is not None:
                actions.append(action)

    for exec_rule in _dict_list(one_click.get("execRules")):
        for device in _dict_list(exec_rule.get("devices")):
            name = _text(device.get("deviceName") or device.get("name"))
            sku = _text(device.get("sku"))
            device_id = _text(device.get("device") or device.get("deviceId"))
            rule = device.get("rule")
            if not isinstance(rule, dict):
                continue
            action = _rule_action(rule, name, sku, device_id)
            if action is not None:
                actions.append(action)

    return actions


def _rule_action(
    rule: dict[str, Any],
    device_name: str,
    sku: str,
    device_id: str | None,
) -> TapAction | None:
    raw = rule.get("iotMsg") or rule.get("effectCommand")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict):
        return None

    message = raw.get("msg") if isinstance(raw.get("msg"), dict) else raw
    command = _text(message.get("cmd"))
    if not command:
        return None
    data = message.get("data")
    if not isinstance(data, dict):
        data = {}
    device_id = device_id or _text(message.get("device") or message.get("deviceId"))
    cmd_version = message.get("cmdVersion", 0)
    msg_type = message.get("type", 1)

    return TapAction(
        device_name=device_name,
        sku=sku,
        command=command,
        data=dict(data),
        cmd_version=_as_int(cmd_version, 0),
        msg_type=_as_int(msg_type, 1),
        device_id=device_id,
    )


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except TypeError, ValueError:
        return default


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _slug(value: str) -> str:
    slug = _WHITESPACE.sub("_", value.lower()).strip("_")
    if not slug:
        return ""
    digest = hashlib.sha1(value.encode(), usedforsecurity=False).hexdigest()[:8]
    return f"{slug}_{digest}"
