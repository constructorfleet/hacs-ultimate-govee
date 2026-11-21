"""Local-network UDP transport for Govee devices."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from collections.abc import Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)

MULTICAST_ADDRESS = "239.255.255.250"
SCAN_PORT = 4001
LISTEN_PORT = 4002
CONTROL_PORT = 4003

LanCallback = Callable[[str, str, dict[str, Any], str], None]


class GoveeLan:
    """Scan for and talk to Govee devices on the local network."""

    def __init__(self, loop: asyncio.AbstractEventLoop, on_message: LanCallback) -> None:
        self._loop = loop
        self._on_message = on_message
        self._listener: asyncio.DatagramTransport | None = None
        self._sender: asyncio.DatagramTransport | None = None

    async def async_start(self) -> None:
        """Bind the reply listener and the multicast sender."""
        if self._listener is not None:
            return
        listener, _ = await self._loop.create_datagram_endpoint(
            _LanProtocol(self._handle_datagram),
            local_addr=("0.0.0.0", LISTEN_PORT),
            allow_broadcast=True,
        )
        self._listener = listener

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.bind(("0.0.0.0", 0))
        sender, _ = await self._loop.create_datagram_endpoint(asyncio.DatagramProtocol, sock=sock)
        self._sender = sender
        await self.async_scan()

    async def async_stop(self) -> None:
        """Close both sockets."""
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        if self._sender is not None:
            self._sender.close()
            self._sender = None

    async def async_scan(self) -> None:
        """Send the multicast scan request."""
        await self._send(
            {"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}},
            (MULTICAST_ADDRESS, SCAN_PORT),
        )

    async def async_send_command(self, ip: str, command: str, data: dict[str, Any]) -> None:
        """Send a control command to a device's IP."""
        await self._send({"msg": {"cmd": command, "data": data}}, (ip, CONTROL_PORT))

    async def async_request_status(self, ip: str) -> None:
        """Ask a LAN device for a status report."""
        await self.async_send_command(ip, "devStatus", {})

    async def _send(self, payload: dict[str, Any], address: tuple[str, int]) -> None:
        if self._sender is None:
            raise RuntimeError("LAN transport is not started")
        self._sender.sendto(json.dumps(payload).encode(), address)

    def _handle_datagram(self, payload: dict[str, Any], address: tuple[str, int]) -> None:
        message = payload.get("msg")
        if not isinstance(message, dict):
            return
        command = str(message.get("cmd") or "")
        data = message.get("data")
        if not isinstance(data, dict):
            data = {}
        device_id = data.get("device") or message.get("device")
        if not device_id:
            return
        ip = data.get("ip") or address[0]
        self._on_message(str(device_id), command, data, str(ip))


class _LanProtocol(asyncio.DatagramProtocol):
    def __init__(self, callback: Callable[[dict[str, Any], tuple[str, int]], None]) -> None:
        self._callback = callback

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            payload = json.loads(data)
        except ValueError, UnicodeDecodeError:
            _LOGGER.debug("Ignoring non-JSON LAN datagram from %s", addr[0])
            return
        if isinstance(payload, dict):
            self._callback(payload, addr)
