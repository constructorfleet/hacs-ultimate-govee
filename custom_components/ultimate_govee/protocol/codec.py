"""Protocol codecs for Govee's base64 frame format."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable, Sequence
from typing import Any

FRAME_LENGTH = 19
COMMAND_PREFIX = 0x33
REPORT_PREFIX = 0xAA


class ProtocolError(ValueError):
    """Raised when a Govee frame cannot be decoded."""


def bytes_to_base64(data: bytes) -> str:
    """Encode raw frame bytes as the base64 string Govee expects."""
    return base64.b64encode(data).decode("ascii")


def base64_to_bytes(value: str) -> bytes:
    """Decode a base64 frame, tolerating URL-safe and unpadded input."""
    value = value.strip()
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, validate=False)
    except (binascii.Error, ValueError) as err:
        raise ProtocolError(f"Invalid base64 frame: {value!r}") from err


def build_frame(
    register: int, values: Iterable[int] = (), *, opcode: int = COMMAND_PREFIX
) -> bytes:
    """Build a 20-byte command frame.

    A frame is ``<opcode> <register> <values...>`` padded to 19 bytes, followed
    by an XOR checksum over those 19 bytes. A few purifier models use ``0x3A``
    as the opcode instead of the usual ``0x33``.
    """
    body = bytes([opcode & 0xFF, register & 0xFF]) + bytes(value & 0xFF for value in values)
    if len(body) > FRAME_LENGTH:
        raise ProtocolError(f"Frame is too long: {body.hex(' ')}")
    body = body.ljust(FRAME_LENGTH, b"\x00")
    checksum = 0
    for value in body:
        checksum ^= value
    return body + bytes([checksum])


def build_frame_b64(
    register: int, values: Iterable[int] = (), *, opcode: int = COMMAND_PREFIX
) -> str:
    """Build a command frame and return it base64 encoded."""
    return bytes_to_base64(build_frame(register, values, opcode=opcode))


def decode_frame(frame: bytes) -> tuple[int, bytes]:
    """Return the register and payload bytes of a report frame."""
    if len(frame) < 3:
        raise ProtocolError(f"Frame too short: {frame.hex(' ')}")
    if frame[0] not in (REPORT_PREFIX, COMMAND_PREFIX, 0x3A):
        raise ProtocolError(f"Unknown frame opcode: {frame[0]:#04x}")
    return frame[1], frame[2:]


def frames_from_command(command: Any) -> list[bytes]:
    """Decode the many shapes of ``op.command`` into raw frames."""
    if command is None:
        return []
    if isinstance(command, (str, bytes)):
        command = [command]
    if not isinstance(command, Sequence):
        return []
    frames: list[bytes] = []
    for item in command:
        if isinstance(item, (list, tuple)) and all(isinstance(value, int) for value in item):
            frames.append(bytes(value & 0xFF for value in item))
            continue
        if isinstance(item, bytes):
            frames.append(item)
            continue
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue
        # Some older payloads use comma or space separated hex rather than
        # base64. Base64 never contains either character.
        if "," in text or " " in text:
            try:
                frames.append(
                    bytes(int(part, 16) for part in text.replace(",", " ").split() if part)
                )
            except ValueError:
                continue
            continue
        try:
            frame = base64_to_bytes(text)
        except ProtocolError:
            continue
        if len(frame) >= 3:
            frames.append(frame)
    return frames
