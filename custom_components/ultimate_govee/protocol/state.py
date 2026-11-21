"""Decode Govee status messages into a partial device state."""

from __future__ import annotations

import json
from typing import Any

from ..models import DeviceState
from ..profiles import (
    KIND_CO2,
    KIND_MONITOR,
    KIND_PROBE,
    KIND_SWITCH,
    KIND_THERMO,
    DeviceProfile,
)
from .codec import ProtocolError, decode_frame, frames_from_command
from .families import decode_raw, decode_register
from .families.common import scale_brightness


def decode_message(profile: DeviceProfile, payload: Any) -> DeviceState:
    """Decode one incoming AWS IoT or LAN message.

    Govee sends the same logical payload in several wrappers depending on the
    device generation, so this walks all of them and degrades to an empty
    result rather than failing a status update.
    """
    message = _unwrap(payload)
    result: dict[str, Any] = {}

    for candidate in _message_layers(message):
        _decode_state_object(profile, candidate.get("state"), result)
        _decode_state_object(profile, candidate.get("data"), result)
        _decode_known_fields(profile, candidate, result)
        _decode_frames(profile, candidate.get("op"), result)

    if "waterShortage" in message:
        result["water_shortage"] = _as_bool(message["waterShortage"])
    if "leakDetected" in message:
        result["leak"] = _as_bool(message["leakDetected"])
    if "temperature" in message and result.get("temperature") is None:
        result["temperature"] = _temperature(profile, message["temperature"])
    if "humidity" in message and result.get("humidity") is None:
        result["humidity"] = _humidity(profile, message["humidity"])
    if "battery" in message and result.get("battery") is None:
        result["battery"] = _as_int(message["battery"])

    return DeviceState.from_mapping(result)


def decode_cloud_snapshot(
    profile: DeviceProfile,
    settings: dict[str, Any],
    last: dict[str, Any],
) -> DeviceState:
    """Decode the cached snapshot in a cloud device listing.

    This is a different payload shape from :func:`decode_message`: it carries
    only the fields Govee caches for the account, not a live status report. It
    shares the same field normalisers so brightness, temperature, and humidity
    use the profile's units.
    """
    data: dict[str, Any] = {}
    data["online"] = True if last.get("online") is None else _as_bool(last["online"])

    if last.get("isOnOff") is not None:
        data["power"] = _as_bool(last["isOnOff"])

    brightness = _as_int(last.get("brightness"))
    if brightness is not None:
        data["brightness"] = scale_brightness(profile, brightness)

    temperature = _temperature(profile, last.get("tem"))
    if temperature is not None:
        data["temperature"] = temperature

    humidity = _humidity(profile, last.get("hum"))
    if humidity is not None:
        data["humidity"] = humidity

    battery = _as_int(settings.get("battery"))
    if battery is not None:
        data["battery"] = battery

    filter_life = _as_int(settings.get("filterLife"))
    if filter_life is not None:
        data["filter_life"] = filter_life

    return DeviceState.from_mapping(data)


def _unwrap(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    if not isinstance(payload, dict):
        return {}
    message = dict(payload)
    # Older devices double-encode the message under "msg".
    inner = message.get("msg")
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except json.JSONDecodeError:
            inner = None
    if isinstance(inner, dict):
        merged = dict(inner)
        merged.update({key: value for key, value in message.items() if key != "msg"})
        return merged
    return message


def _message_layers(message: dict[str, Any]) -> list[dict[str, Any]]:
    layers = [message]
    data = message.get("data")
    if isinstance(data, str) and data.lstrip().startswith("{"):
        try:
            decoded = json.loads(data)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            layers.append(decoded)
    elif isinstance(data, dict):
        layers.append(data)
    return layers


def _decode_state_object(profile: DeviceProfile, value: Any, result: dict[str, Any]) -> None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return
    if not isinstance(value, dict):
        return

    if "onOff" in value:
        result["power"] = _as_bool(value["onOff"])
        if profile.kind == KIND_SWITCH and profile.gang_count > 1:
            raw = _as_int(value["onOff"]) or 0
            if profile.gang_count == 2:
                gangs = tuple(bool(raw & (1 << index)) for index in range(2))
            else:
                gangs = tuple(bool(raw & (0x11 << index)) for index in range(3))
            result["gangs"] = gangs
            result["power"] = any(gangs)
    if "isOnOff" in value:
        result["power"] = _as_bool(value["isOnOff"])
    if "connected" in value:
        result["online"] = _as_bool(value["connected"])
    if "brightness" in value:
        brightness = _as_int(value["brightness"])
        if brightness is not None:
            result["brightness"] = scale_brightness(profile, brightness)
    if "colorTemInKelvin" in value:
        kelvin = _as_int(value["colorTemInKelvin"])
        if kelvin:
            result["color_temp"] = kelvin
    if "color" in value and isinstance(value["color"], dict):
        result["color"] = _colour(value["color"])
    if "mode" in value:
        result["mode"] = _mode(value["mode"])
    if "setTemperature" in value:
        result["target_temperature"] = _as_number(value["setTemperature"])
    if "targetTemperature" in value:
        result["target_temperature"] = _as_number(value["targetTemperature"])
    if "setTem" in value:
        result["target_temperature"] = _as_number(value["setTem"])
    if "humidity" in value:
        result["humidity"] = _humidity(profile, value["humidity"])
    if "temperature" in value:
        result["temperature"] = _temperature(profile, value["temperature"])
    if "battery" in value:
        result["battery"] = _as_int(value["battery"])
    if "filterLife" in value:
        result["filter_life"] = _as_int(value["filterLife"])
    if "waterShortage" in value:
        result["water_shortage"] = _as_bool(value["waterShortage"])

    sta = value.get("sta")
    if isinstance(sta, dict):
        if "curTem" in sta:
            result["temperature"] = _temperature(profile, sta["curTem"])
        if "setTem" in sta:
            result["target_temperature"] = _as_number(sta["setTem"])
        stc = sta.get("stc")
        if isinstance(stc, list) and len(stc) >= 2 and stc[0] == 0x06:
            result["water_shortage"] = stc[1] != 0


def _decode_known_fields(
    profile: DeviceProfile, message: dict[str, Any], result: dict[str, Any]
) -> None:
    if "onOff" in message:
        result["power"] = _as_bool(message["onOff"])
    if "brightness" in message:
        brightness = _as_int(message["brightness"])
        if brightness is not None:
            result["brightness"] = scale_brightness(profile, brightness)
    if "colorTemInKelvin" in message and result.get("color_temp") is None:
        kelvin = _as_int(message["colorTemInKelvin"])
        if kelvin:
            result["color_temp"] = kelvin
    if "mode" in message and result.get("mode") is None:
        result["mode"] = _mode(message["mode"])


def _decode_frames(profile: DeviceProfile, op: Any, result: dict[str, Any]) -> None:
    """Unwrap report frames and hand each one to the SKU's dialect."""
    if not isinstance(op, dict):
        return

    # Newer firmware nests the frames under `op.command`; some models use
    # `op.mode`/`op.value` or `op.opCode` + `op.modeValue` instead.
    raw_frames = frames_from_command(op.get("command"))
    raw_frames.extend(frames_from_command(op.get("opCode")))
    mode = op.get("mode")
    value = op.get("value")
    if isinstance(mode, (list, tuple)) and isinstance(value, (list, tuple)):
        raw_frames.append(bytes([0xAA, 0x05, *mode, *value]))
    mode_value = op.get("modeValue")
    if isinstance(mode_value, (list, tuple)):
        raw_frames.append(bytes([0xAA, 0x05, *mode_value]))

    for raw in raw_frames:
        if decode_raw(profile, raw, result):
            continue
        if raw[0] not in (0xAA, 0x33, 0x3A):
            continue
        try:
            register, payload = decode_frame(raw)
        except ProtocolError:
            continue
        decode_register(profile, register, payload, result)


def _colour(value: dict[str, Any]) -> tuple[int, int, int]:
    red = _as_int(value.get("r", value.get("red", 0))) or 0
    green = _as_int(value.get("g", value.get("green", 0))) or 0
    blue = _as_int(value.get("b", value.get("blue", 0))) or 0
    return (red, green, blue)


def _mode(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    number = _as_int(value)
    if number is None:
        return None
    return str(number)


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "on", "true", "yes"}:
            return True
        if text in {"0", "off", "false", "no", ""}:
            return False
        try:
            return int(float(text)) != 0
        except ValueError:
            return False
    return bool(value)


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except TypeError, ValueError:
        return None


def _as_number(value: Any) -> float | None:
    try:
        return float(value)
    except TypeError, ValueError:
        return None


SENSOR_KINDS = frozenset({KIND_THERMO, KIND_MONITOR, KIND_PROBE, KIND_CO2})


def _temperature(profile: DeviceProfile, value: Any) -> float | None:
    """Normalise a temperature.

    Thermo-hygrometer, monitor and CO2 payloads use hundredths of a degree;
    appliance payloads already use degrees.
    """
    number = _as_number(value)
    if number is None:
        return None
    if profile.kind in SENSOR_KINDS and abs(number) > 200:
        return round(number / 100, 2)
    return number


def _humidity(profile: DeviceProfile, value: Any) -> float | None:
    """Normalise a humidity reading, which sensors send in hundredths of a %."""
    number = _as_number(value)
    if number is None:
        return None
    if profile.kind in SENSOR_KINDS and number > 100:
        number /= 100
    return max(0, min(100, round(number, 2)))
