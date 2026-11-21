"""Tests for the Govee frame codec."""

from __future__ import annotations

import base64

import pytest

from custom_components.ultimate_govee.protocol.codec import (
    ProtocolError,
    base64_to_bytes,
    build_frame,
    build_frame_b64,
    bytes_to_base64,
    decode_frame,
    frames_from_command,
)


def test_build_frame_pads_and_checksums() -> None:
    frame = build_frame(0x01, [0x01])

    assert len(frame) == 20
    assert frame[0] == 0x33
    assert frame[1] == 0x01
    assert frame[2] == 0x01
    assert frame[3:19] == bytes(16)

    checksum = 0
    for value in frame[:19]:
        checksum ^= value
    assert frame[19] == checksum


def test_build_frame_accepts_a_custom_opcode() -> None:
    frame = build_frame(0x05, [0x01, 0x02], opcode=0x3A)

    assert frame[0] == 0x3A
    assert frame[1] == 0x05
    assert frame[2:4] == b"\x01\x02"


def test_base64_round_trip() -> None:
    frame = build_frame(0x05, [0x03, 0xFF, 0x00, 0x10])
    encoded = build_frame_b64(0x05, [0x03, 0xFF, 0x00, 0x10])

    assert base64_to_bytes(encoded) == frame
    assert base64_to_bytes(encoded.rstrip("=")) == frame
    assert bytes_to_base64(frame) == base64.b64encode(frame).decode()


def test_decode_frame() -> None:
    register, payload = decode_frame(build_frame(0x05, [0x01, 0x05]))

    assert register == 0x05
    assert payload[:2] == b"\x01\x05"


def test_decode_frame_rejects_short_and_unknown_frames() -> None:
    with pytest.raises(ProtocolError):
        decode_frame(b"")
    with pytest.raises(ProtocolError):
        decode_frame(bytes(20))


def test_frames_from_command_accepts_many_encodings() -> None:
    raw = build_frame(0x01, [0x01])
    encoded = bytes_to_base64(raw)
    hex_frame = " ".join(f"{value:02x}" for value in raw)

    assert frames_from_command([encoded]) == [raw]
    assert frames_from_command(encoded) == [raw]
    assert frames_from_command([hex_frame]) == [raw]
    assert frames_from_command([[0x33, 0x01, 0x01]])[0][:3] == b"\x33\x01\x01"
    assert frames_from_command([raw]) == [raw]
    assert frames_from_command(None) == []
    assert frames_from_command(["not a frame"]) == []
