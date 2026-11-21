"""Compatibility dialect for SKUs without a moved, evidenced codec.

The encoders here wrap the pre-dialect behaviour for humidifiers other than
H7141/H7142, dehumidifiers and accessory registers no moved family owns. They
are a fallback, not an inference that those SKUs are byte-identical:
:class:`~.base.FamilyDialect` entries for observed variants take precedence and
are assigned per SKU.

Decoding follows the same rule: an exact dialect answers first, and this module
owns the universal registers plus the pre-dialect meanings that no family has
moved yet. Those remaining kind-keyed meanings are marked ``LEGACY`` so they
are visibly a fallback rather than an assignment.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ...profiles import (
    KIND_CO2,
    KIND_DEHUMIDIFIER,
    KIND_DIFFUSER,
    KIND_HEATER,
    KIND_HUMIDIFIER,
    KIND_KETTLE,
    KIND_LEAK,
    KIND_LIGHT,
    KIND_MONITOR,
    KIND_PRESENCE,
    KIND_PURIFIER,
    KIND_TV,
)
from ..codec import ProtocolError, build_frame_b64, decode_frame
from ..command import (
    ACTION_DISPLAY,
    ACTION_HUMIDIFIER_MODE,
    ACTION_HUMIDIFIER_TARGET,
    ACTION_LOCK,
    ACTION_MIST_LEVEL,
    ACTION_NIGHT_LIGHT,
    ACTION_OSCILLATION,
    ACTION_TIMER,
    ACTION_UV,
    STRATEGY_PT_REAL,
    Command,
    frames_command,
)
from .base import FamilyDialect
from .common import (
    apply_humidity_reading,
    apply_night_light,
    decode_co2_frame,
    decode_humidifier_register_05,
    decode_leak_frame,
    decode_light_register_05,
    decode_monitor_frame,
    scale_brightness,
)

if TYPE_CHECKING:
    from ...profiles import DeviceProfile

_LOGGER = logging.getLogger(__name__)

HUMIDIFIER_MODE_MANUAL = 0x01
HUMIDIFIER_MODE_PROGRAM = 0x02
HUMIDIFIER_MODE_AUTO = 0x03

HUMIDIFIER_MODES: dict[str, int] = {
    "manual": HUMIDIFIER_MODE_MANUAL,
    "program": HUMIDIFIER_MODE_PROGRAM,
    "auto": HUMIDIFIER_MODE_AUTO,
}

FAN_OSCILLATION_REGISTER = 0x1F

# Kinds whose 0x05 register carries light colour/effect sub-commands.
LIGHT_KINDS = {KIND_LIGHT, KIND_TV, KIND_DIFFUSER}


def frame_command(
    register: int,
    values: Any = (),
    *,
    opcode: int = 0x33,
    strategy: str = STRATEGY_PT_REAL,
) -> Command:
    """Build a command from one register frame."""
    return frames_command(
        [build_frame_b64(register, values, opcode=opcode)],
        strategy=strategy,
    )


class GenericDialect(FamilyDialect):
    """The conservative fallback used when no variant was observed."""

    name = "generic"
    source = "pre-dialect behaviour, wrapped"
    confidence = "low"

    def encode(
        self,
        _profile: Any,
        action: str,
        parameters: dict[str, Any],
    ) -> Command | None:
        if action == ACTION_NIGHT_LIGHT:
            return self._night_light(parameters)
        if action == ACTION_DISPLAY:
            return frame_command(0x16, [1 if parameters["on"] else 0])
        if action == ACTION_LOCK:
            return frame_command(0x0A, [1 if parameters["on"] else 0])
        if action == ACTION_UV:
            return frame_command(0x1A, [1 if parameters["on"] else 0])
        if action == ACTION_TIMER:
            minutes = max(0, min(0xFFFF, int(parameters["minutes"])))
            return frame_command(
                0x0A,
                [0x0B, 1 if parameters["enabled"] else 0, minutes >> 8, minutes & 0xFF],
            )
        if action == ACTION_OSCILLATION:
            return frame_command(FAN_OSCILLATION_REGISTER, [0x01, 1 if parameters["on"] else 0])
        if action == ACTION_MIST_LEVEL:
            return frame_command(
                0x05, [HUMIDIFIER_MODE_MANUAL, max(1, min(9, int(parameters["level"])))]
            )
        if action == ACTION_HUMIDIFIER_MODE:
            value = HUMIDIFIER_MODES.get(str(parameters["mode"]).lower(), HUMIDIFIER_MODE_AUTO)
            return frame_command(0x05, [0x00, value])
        if action == ACTION_HUMIDIFIER_TARGET:
            return frame_command(0x05, [HUMIDIFIER_MODE_AUTO, self._humidity(parameters)])
        return None

    def decode_raw(
        self,
        profile: DeviceProfile,
        frame: bytes,
        result: dict[str, Any],
    ) -> bool:
        """Decode the whole-frame reports that do not use the register envelope.

        These layouts belong to one kind today; keeping the kind check here
        makes the legacy exception explicit instead of a state.py ladder.
        """
        kind = profile.kind
        if kind == KIND_MONITOR and len(frame) >= 20:
            decode_monitor_frame(frame, result)
            return True
        if kind == KIND_LEAK and frame[:1] == b"\xee":
            decode_leak_frame(frame, result)
            return True
        if kind == KIND_CO2 and frame[:2] == b"\xaa\x0a":
            try:
                register, payload = decode_frame(frame)
            except ProtocolError:
                return False
            if register == 0x0A:
                decode_co2_frame(payload, result)
                return True
        return False

    def decode_frame(
        self,
        profile: DeviceProfile,
        register: int,
        payload: bytes,
        result: dict[str, Any],
    ) -> bool:
        """Decode the universal registers and the remaining legacy meanings."""
        kind = profile.kind
        if register == 0x01 and payload:
            # LEGACY: the default power meaning; sensors override it.
            if kind == KIND_PRESENCE:
                result["presence"] = payload[0] != 0
            elif kind == KIND_LEAK:
                result["leak"] = payload[0] != 0
            else:
                result["power"] = payload[0] != 0
            return True
        if register == 0x04 and payload:
            result["brightness"] = scale_brightness(profile, payload[0])
            return True
        if register == 0x05 and payload:
            return self._decode_register_05(profile, payload, result)
        if register == 0x0A and len(payload) >= 3 and payload[0] == 0x0B:
            result["timer_enabled"] = payload[1] != 0
            result["timer_minutes"] = (payload[2] << 8) | payload[3] if len(payload) > 3 else None
            return True
        if register == 0x0A and payload:
            # LEGACY: a bare 0x0A report means child lock.
            result["lock"] = payload[0] != 0
            return True
        if register == 0x10 and kind in {KIND_HEATER, KIND_PURIFIER} and payload:
            # LEGACY: heaters and purifiers report lock on 0x10.
            result["lock"] = payload[0] != 0
            return True
        if register == 0x10 and kind in {KIND_HUMIDIFIER, KIND_DEHUMIDIFIER} and len(payload) >= 4:
            apply_humidity_reading(payload, result)
            return True
        if register == 0x16 and payload:
            result["display"] = payload[0] != 0
            return True
        if register == 0x18 and payload:
            # LEGACY: heaters swing on 0x18; other kinds report a display there.
            if kind == KIND_HEATER:
                result["oscillation"] = payload[0] != 0
            else:
                result["display"] = payload[0] != 0
            return True
        if register == 0x1B and payload:
            apply_night_light(payload, result)
            return True
        if register == 0x1F and len(payload) >= 3:
            # LEGACY: heater2 packs swing and child lock into the same report.
            result["oscillation"] = payload[1] != 0
            result["lock"] = payload[2] != 0
            return True
        if register == 0x1A and payload:
            # LEGACY: heaters report a Fahrenheit target; other kinds report UVC.
            if kind == KIND_HEATER and len(payload) >= 4:
                raw = (payload[2] << 8) | payload[3]
                if raw & 0x8000:
                    fahrenheit = (raw & 0x7FFF) / 100
                    result["target_temperature"] = round((fahrenheit - 32) * 5 / 9, 1)
            else:
                result["uv"] = payload[0] != 0
            return True
        if register == 0x17 and len(payload) >= 2:
            result["basket_full"] = payload[1] != 0
            result["water_shortage"] = payload[1] != 0
            return True
        if register == 0x19 and len(payload) >= 14:
            # H5086 outlet power metering: voltage, current and power.
            result["voltage"] = ((payload[7] << 8) | payload[8]) / 100
            result["current"] = ((payload[9] << 8) | payload[10]) / 100
            result["power_usage"] = ((payload[11] << 16) | (payload[12] << 8) | payload[13]) / 100
            return True
        if register == 0x1C and len(payload) >= 3:
            # H7122 PM2.5 is big-endian; the exact byte offset is unconfirmed,
            # so accept the documented bytes 4+5 first.
            result["pm25"] = (payload[2] << 8) | payload[3] if len(payload) > 3 else payload[1]
            return True
        if register == 0x31 and payload:
            # AA 31 <running> <speed> <direction>. Oscillation is OpenAPI-only.
            result["power"] = payload[0] != 0
            if len(payload) > 1:
                result["fan_speed"] = payload[1]
                if profile.fan_speeds:
                    result["percentage"] = round(payload[1] * 100 / profile.fan_speeds)
            return True
        if register == 0x36 and payload:
            _LOGGER.debug(
                "Unhandled 0x36 frame for %s (%s): %s",
                profile.model_name,
                kind,
                payload.hex(),
            )
            return True
        return False

    def _decode_register_05(
        self,
        profile: DeviceProfile,
        payload: bytes,
        result: dict[str, Any],
    ) -> bool:
        kind = profile.kind
        if kind in LIGHT_KINDS:
            decode_light_register_05(payload, result)
            return True
        if kind == KIND_HUMIDIFIER:
            decode_humidifier_register_05(profile, payload, result)
            return True
        if kind == KIND_KETTLE:
            result["mode"] = str(payload[0])
            return True
        _LOGGER.debug(
            "Unhandled 0x05 frame for %s (%s): %s",
            profile.model_name,
            kind,
            payload.hex(),
        )
        return True

    def _night_light(self, parameters: dict[str, Any]) -> Command:
        level = max(0, min(100, int(parameters.get("brightness", 100))))
        red, green, blue = (
            max(0, min(255, int(value))) for value in parameters.get("rgb", (255, 255, 255))
        )
        if not parameters["on"]:
            return frame_command(0x1B, [0])
        return frame_command(0x1B, [1, level, red, green, blue])

    @staticmethod
    def _humidity(parameters: dict[str, Any]) -> int:
        return max(1, min(100, int(parameters["target"])))


GENERIC = GenericDialect()
