"""Decode Govee status messages into a partial device state."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..models import DeviceState
from ..profiles import (
    HEATER2_MODELS,
    KIND_CEILING_FAN,
    KIND_CO2,
    KIND_DEHUMIDIFIER,
    KIND_DIFFUSER,
    KIND_HEATER,
    KIND_HUMIDIFIER,
    KIND_ICE_MAKER,
    KIND_KETTLE,
    KIND_LEAK,
    KIND_LIGHT,
    KIND_MONITOR,
    KIND_PRESENCE,
    KIND_PROBE,
    KIND_PURIFIER,
    KIND_SWITCH,
    KIND_THERMO,
    KIND_TV,
    PURIFIER_3A_MODELS,
    PURIFIER_3A_SPEEDS,
    PURIFIER_H7120_MODELS,
    PURIFIER_H7126_MODELS,
    DeviceProfile,
)
from .codec import ProtocolError, decode_frame, frames_from_command

_LOGGER = logging.getLogger(__name__)

LIGHT_KINDS = {KIND_LIGHT, KIND_TV, KIND_DIFFUSER}


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
        data["brightness"] = _scale_brightness(profile, brightness)

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
            result["brightness"] = _scale_brightness(profile, brightness)
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
            result["brightness"] = _scale_brightness(profile, brightness)
    if "colorTemInKelvin" in message and result.get("color_temp") is None:
        kelvin = _as_int(message["colorTemInKelvin"])
        if kelvin:
            result["color_temp"] = kelvin
    if "mode" in message and result.get("mode") is None:
        result["mode"] = _mode(message["mode"])


def _decode_frames(profile: DeviceProfile, op: Any, result: dict[str, Any]) -> None:
    if not isinstance(op, dict):
        return

    kind = profile.kind
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
        if kind == KIND_MONITOR and len(raw) >= 20:
            _decode_monitor_frame(raw, result)
            continue
        if raw[0] == 0xEE and kind == KIND_LEAK:
            _decode_leak_frame(raw, result)
            continue
        if raw[0] not in (0xAA, 0x33, 0x3A):
            continue
        try:
            register, payload = decode_frame(raw)
        except ProtocolError:
            continue
        if raw[0] == 0xAA and register == 0x0A and kind == KIND_CO2:
            _decode_co2_frame(payload, result)
            continue
        _decode_frame(profile, register, payload, result)


def _decode_monitor_frame(frame: bytes, result: dict[str, Any]) -> None:
    """Decode the H5106's heuristic 20-byte air-quality frame."""
    temperature = ((frame[0] << 8) | frame[1]) / 100
    if not -30 <= temperature <= 80:
        return
    result["temperature"] = round(temperature, 1)
    if len(frame) >= 11:
        result["humidity"] = ((frame[9] << 8) | frame[10]) / 100
    if len(frame) >= 20:
        result["pm25"] = (frame[18] << 8) | frame[19]


def _decode_co2_frame(payload: bytes, result: dict[str, Any]) -> None:
    """Decode the H5140 ``AA 0A`` little-endian temperature/humidity/CO2 frame."""
    if len(payload) < 6:
        return
    # The frame is AA 0A <temp lo> <temp hi> <rh lo> <rh hi> <co2 lo> <co2 hi>.
    temperature = (payload[0] | (payload[1] << 8)) / 100
    if -40 < temperature < 100:
        result["temperature"] = round(temperature, 2)
    humidity = payload[2] | (payload[3] << 8)
    result["humidity"] = max(0, min(100, round(humidity / 100)))
    co2 = payload[4] | (payload[5] << 8)
    if 0 <= co2 <= 40000:
        result["co2"] = co2


def _decode_leak_frame(frame: bytes, result: dict[str, Any]) -> None:
    """Decode the gateway leak frame (``EE 34``) used by newer sensors."""
    if len(frame) < 4:
        return
    # The gateway reports the sensor's alarm bit in the first payload byte.
    result["leak"] = frame[2] != 0


def _decode_frame(
    profile: DeviceProfile,
    register: int,
    payload: bytes,
    result: dict[str, Any],
) -> None:
    kind = profile.kind
    if register == 0x01 and payload:
        if kind == KIND_PRESENCE:
            result["presence"] = payload[0] != 0
        elif kind == KIND_LEAK:
            result["leak"] = payload[0] != 0
        else:
            result["power"] = payload[0] != 0
    elif register == 0x04 and payload:
        result["brightness"] = _scale_brightness(profile, payload[0])
    elif register == 0x05 and payload:
        _decode_register_05(profile, payload, result)
    elif register == 0x0A and len(payload) >= 3 and payload[0] == 0x0B:
        result["timer_enabled"] = payload[1] != 0
        result["timer_minutes"] = (payload[2] << 8) | payload[3] if len(payload) > 3 else None
    elif (register == 0x0A and payload) or (
        register == 0x10 and kind in {KIND_HEATER, KIND_PURIFIER} and payload
    ):
        result["lock"] = payload[0] != 0
    elif register == 0x10 and kind in {KIND_HUMIDIFIER, KIND_DEHUMIDIFIER} and len(payload) >= 4:
        _decode_humidity_frame(payload, result)
    elif register == 0x16 and payload:
        result["display"] = payload[0] != 0
    elif register == 0x18 and payload:
        if kind == KIND_PURIFIER:
            result["night_light"] = payload[0] != 0
        elif kind == KIND_HEATER:
            result["oscillation"] = payload[0] != 0
        else:
            # Humidifiers only report AA 18; there is no display setter.
            result["display"] = payload[0] != 0
    elif register == 0x1B and payload:
        result["night_light"] = payload[0] != 0
        if len(payload) > 1:
            result["night_light_brightness"] = payload[1]
        if len(payload) > 4:
            result["night_light_color"] = (payload[2], payload[3], payload[4])
    elif register == 0x1F and len(payload) >= 3:
        # Heater2 packs swing and child lock into the same report.
        result["oscillation"] = payload[1] != 0
        result["lock"] = payload[2] != 0
    elif register == 0x1A and payload:
        if kind == KIND_HEATER and len(payload) >= 4:
            raw = (payload[2] << 8) | payload[3]
            if raw & 0x8000:
                fahrenheit = (raw & 0x7FFF) / 100
                result["target_temperature"] = round((fahrenheit - 32) * 5 / 9, 1)
        else:
            result["uv"] = payload[0] != 0
    elif register == 0x17 and len(payload) >= 2:
        result["basket_full"] = payload[1] != 0
        result["water_shortage"] = payload[1] != 0
    elif register == 0x19 and payload:
        if kind == KIND_PURIFIER:
            result["air_quality"] = payload[0]
        elif kind == KIND_ICE_MAKER:
            result["basket_full"] = payload[0] != 0
        elif len(payload) >= 14:
            # H5086 outlet power metering: voltage, current and power.
            result["voltage"] = ((payload[7] << 8) | payload[8]) / 100
            result["current"] = ((payload[9] << 8) | payload[10]) / 100
            result["power_usage"] = ((payload[11] << 16) | (payload[12] << 8) | payload[13]) / 100
    elif register == 0x1C and len(payload) >= 3:
        # H7122 PM2.5 is big-endian; the exact byte offset is unconfirmed, so
        # accept the documented bytes 4+5 first.
        result["pm25"] = (payload[2] << 8) | payload[3] if len(payload) > 3 else payload[1]
    elif register == 0x31 and payload:
        # AA 31 <running> <speed> <direction>. Oscillation is OpenAPI-only.
        result["power"] = payload[0] != 0
        if len(payload) > 1:
            result["fan_speed"] = payload[1]
            if profile.fan_speeds:
                result["percentage"] = round(payload[1] * 100 / profile.fan_speeds)
    elif register == 0x36 and payload:
        if kind == KIND_CEILING_FAN:
            # The first byte reports whether the main zone is powered. Keep
            # any power already reported by another frame in the same message.
            result.setdefault("power", payload[0] != 0)
            result["night_light"] = payload[0] != 0
        else:
            _LOGGER.debug(
                "Unhandled 0x36 frame for %s (%s): %s",
                profile.model_name,
                kind,
                payload.hex(),
            )


def _decode_humidity_frame(payload: bytes, result: dict[str, Any]) -> None:
    """Decode ``AA 10 <flags> <3-byte reading>``.

    The low 24 bits pack the humidity as tenths of a percent; the high bits
    carry the temperature in tenths of a degree.
    """
    flags = payload[0]
    if not flags & 0x81:
        return
    reading = (payload[1] << 16) | (payload[2] << 8) | payload[3]
    if reading == 0xFFFFFF:
        return
    result["humidity"] = round((reading & 0x7FFFFF) % 1000 / 10, 1)
    temperature = (reading // 1000) / 10
    if temperature:
        result["temperature"] = temperature


def _decode_register_05(profile: DeviceProfile, payload: bytes, result: dict[str, Any]) -> None:
    kind = profile.kind
    sub = payload[0]
    if kind in LIGHT_KINDS:
        if sub == 0x03 and len(payload) >= 4:
            result["color"] = (payload[1], payload[2], payload[3])
        elif sub == 0x02 and len(payload) >= 3:
            result["effect"] = f"{(payload[1] << 8) | payload[2]:04x}"
        elif sub == 0x15 and len(payload) >= 4:
            result["color"] = (payload[2], payload[3], payload[4] if len(payload) > 4 else 0)
    elif kind == KIND_HUMIDIFIER:
        if sub == 0x00 and len(payload) >= 2:
            result["mode"] = {1: "manual", 2: "program", 3: "auto"}.get(payload[1])
            if payload[1] == 0x03 and len(payload) > 2:
                result["target_humidity"] = payload[2]
        elif sub == 0x01 and len(payload) >= 2:
            result["mode"] = "manual"
            result["fan_speed"] = payload[1]
            result["percentage"] = _gear_percentage(profile, payload[1])
        elif sub == 0x02:
            result["mode"] = "program"
        elif sub == 0x03 and len(payload) >= 2:
            result["mode"] = "auto"
            result["target_humidity"] = payload[1]
    elif kind == KIND_PURIFIER:
        _decode_purifier_speed(profile, payload, result)
    elif kind == KIND_HEATER:
        _decode_heater_speed(profile, payload, result)
    elif kind == KIND_DEHUMIDIFIER:
        if sub == 0x00 and len(payload) >= 2:
            result["mode"] = {1: "low", 2: "high", 3: "auto", 8: "dryer"}.get(
                payload[1], str(payload[1])
            )
        elif sub in (0x01, 0x02) and len(payload) >= 2:
            result["fan_speed"] = payload[1]
            result["percentage"] = _gear_percentage(profile, payload[1])
        elif len(payload) >= 2:
            result["fan_speed"] = payload[1]
    elif kind == KIND_ICE_MAKER:
        index = sub if sub <= 3 else payload[-1]
        sizes = profile.ice_sizes or ("small", "medium", "large")
        size_index = index - 1 if profile.model_name in {"H8121", "H8122"} else len(sizes) - index
        if 0 <= size_index < len(sizes):
            result["ice_size"] = sizes[size_index]
    elif kind == KIND_KETTLE:
        result["mode"] = str(sub)
    else:
        _LOGGER.debug(
            "Unhandled 0x05 frame for %s (%s): %s",
            profile.model_name,
            kind,
            payload.hex(),
        )


def _decode_heater_speed(profile: DeviceProfile, payload: bytes, result: dict[str, Any]) -> None:
    """Decode the two heater speed report layouts.

    Heater1 reports ``AA 05 <level>``. Heater2 reports fan-only as
    ``AA 05 09``, speed as ``AA 05 01 <1-3>`` and auto as ``AA 05 03``.
    """
    if profile.model_name in HEATER2_MODELS:
        sub = payload[0]
        if sub == 0x09:
            result["mode"] = "fan-only"
            result["fan_speed"] = 1
            result["percentage"] = 25
        elif sub == 0x03:
            result["mode"] = "auto"
        elif sub == 0x01 and len(payload) > 1:
            level = max(1, min(3, payload[1])) + 1
            result["fan_speed"] = level
            result["percentage"] = level * 25
            result["mode"] = ("fan-only", "low", "medium", "high")[level - 1]
        return
    level = max(1, min(3, payload[0]))
    result["fan_speed"] = level
    result["percentage"] = (33, 66, 99)[level - 1]
    result["mode"] = ("low", "medium", "high")[level - 1]


def _decode_purifier_speed(profile: DeviceProfile, payload: bytes, result: dict[str, Any]) -> None:
    """Decode the three different purifier speed report layouts."""
    model = profile.model_name
    if model in PURIFIER_3A_MODELS:
        pair = (payload[0], payload[1] if len(payload) > 1 else 0)
        for index, (mode, first, second) in enumerate(PURIFIER_3A_SPEEDS, start=1):
            if pair == (first, second):
                result["mode"] = mode
                result["percentage"] = index * 20
                return
        return
    if model in PURIFIER_H7120_MODELS:
        # Reports put the gear in byte 3 or byte 4 depending on firmware.
        gear = payload[1] if len(payload) > 1 and payload[1] else payload[0]
        gear = max(1, min(4, gear))
        result["fan_speed"] = gear
        result["percentage"] = gear * 25
        result["mode"] = ("sleep", "low", "medium", "high")[gear - 1]
        return
    if model in PURIFIER_H7126_MODELS:
        level = payload[1] if payload[0] == 0x01 and len(payload) > 1 else payload[0]
        level = max(1, min(3, level))
        result["fan_speed"] = level
        result["percentage"] = level * 33
        result["mode"] = ("sleep", "low", "high")[level - 1]
        return
    result["fan_speed"] = payload[0]
    result["percentage"] = _gear_percentage(profile, payload[0])


def _gear_percentage(profile: DeviceProfile, gear: int) -> int:
    """Convert a 1-based gear to a percentage."""
    if profile.fan_speeds <= 0:
        return gear
    return max(0, min(100, round(gear * 100 / profile.fan_speeds)))


def _scale_brightness(profile: DeviceProfile, value: int) -> int:
    if profile.brightness_max > 100:
        return max(0, min(100, round(value * 100 / profile.brightness_max)))
    return max(0, min(100, value))


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
