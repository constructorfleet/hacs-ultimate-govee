"""AWS IoT MQTT transport using Govee's mutual-TLS certificate."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from cryptography.hazmat.primitives.serialization.pkcs12 import (
    load_key_and_certificates,
)

from ..const import AMAZON_ROOT_CA1
from .cloud import GoveeApiError

_LOGGER = logging.getLogger(__name__)

MessageCallback = Callable[[dict[str, Any]], None]


class GoveeIot:
    """Long-lived MQTT connection to Govee's AWS IoT broker."""

    def __init__(
        self,
        *,
        account_id: str,
        client_id: str,
        account_topic: str,
        cert_dir: Path,
        loop: asyncio.AbstractEventLoop,
        on_message: MessageCallback,
    ) -> None:
        self._account_id = account_id
        self._client_id = client_id
        self._account_topic = account_topic
        self._cert_dir = cert_dir
        self._loop = loop
        self._on_message = on_message
        self._client: mqtt.Client | None = None
        self._connected = asyncio.Event()
        self._sequence = 0

    @property
    def connected(self) -> bool:
        """Return whether the MQTT session is currently connected."""
        return self._connected.is_set()

    async def async_start(self, certificate: dict[str, Any]) -> None:
        """Write the certificate files and connect to the broker."""
        endpoint = certificate.get("endpoint") or certificate.get("brokerUrl")
        p12 = certificate.get("p12")
        password = certificate.get("p12Pass") or certificate.get("p12Password") or ""
        if not endpoint or not p12:
            raise GoveeApiError("The IoT certificate is missing its endpoint")
        cert_path, key_path, ca_path = await asyncio.to_thread(
            _write_certificate_files, self._cert_dir, p12, password
        )

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"AP/{self._account_id}/hb{secrets.token_hex(8)}",
            protocol=mqtt.MQTTv311,
        )
        client.tls_set(
            ca_certs=str(ca_path),
            certfile=str(cert_path),
            keyfile=str(key_path),
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_mqtt_message
        self._client = client
        client.connect_async(str(endpoint), 8883, keepalive=60)
        client.loop_start()
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=30)
        except TimeoutError:
            _LOGGER.warning("Timed out connecting to Govee's AWS IoT broker")

    async def async_stop(self) -> None:
        """Disconnect from the broker."""
        self._connected.clear()
        if self._client is None:
            return
        client = self._client
        self._client = None
        await asyncio.to_thread(client.loop_stop)
        client.disconnect()

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish a JSON payload to a device topic."""
        if self._client is None or not self._connected.is_set():
            raise GoveeApiError("The Govee IoT connection is not available")
        self._client.publish(topic, json.dumps(payload), qos=1)

    def send_command(
        self,
        topic: str,
        command: str,
        data: dict[str, Any] | None = None,
        *,
        cmd_version: int = 0,
        msg_type: int = 1,
    ) -> None:
        """Publish a command envelope to a device."""
        message: dict[str, Any] = {
            "cmd": command,
            "cmdVersion": cmd_version,
            "transaction": self._transaction(),
            "type": msg_type,
            "accountTopic": self._account_topic,
        }
        if data is not None:
            message["data"] = data
        self.publish(topic, {"msg": message})

    def request_status(self, topic: str, cmd_version: int = 2) -> None:
        """Ask a device for a full status report."""
        self.send_command(topic, "status", cmd_version=cmd_version, msg_type=0)

    def _transaction(self) -> str:
        self._sequence = (self._sequence + 1) % 1000
        return f"v_{int(time.time() * 1000)}{self._sequence:03d}"

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if reason_code != 0:
            _LOGGER.error("Govee IoT connection failed: %s", reason_code)
            return
        _LOGGER.debug("Connected to Govee IoT, subscribing to %s", self._account_topic)
        client.subscribe(self._account_topic, qos=1)
        self._loop.call_soon_threadsafe(self._connected.set)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        _LOGGER.debug("Disconnected from Govee IoT: %s", reason_code)
        self._loop.call_soon_threadsafe(self._connected.clear)

    def _on_mqtt_message(
        self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage
    ) -> None:
        try:
            payload = json.loads(message.payload)
        except ValueError, UnicodeDecodeError:
            _LOGGER.debug("Ignoring non-JSON Govee IoT message")
            return
        if isinstance(payload, dict):
            self._loop.call_soon_threadsafe(self._on_message, payload)


def _write_certificate_files(
    directory: Path, p12_base64: str, password: str
) -> tuple[Path, Path, Path]:
    """Decode the PKCS#12 bundle and write PEM files for paho."""
    directory.mkdir(parents=True, exist_ok=True)
    raw = base64.b64decode(p12_base64)
    key, certificate, additional = load_key_and_certificates(
        raw, password.encode() if password else None
    )
    if key is None or certificate is None:
        raise GoveeApiError("The IoT certificate bundle is incomplete")

    cert_path = directory / "govee-iot-cert.pem"
    key_path = directory / "govee-iot-key.pem"
    ca_path = directory / "AmazonRootCA1.pem"

    cert_pem = certificate.public_bytes(Encoding.PEM)
    for extra in additional or []:
        cert_pem += extra.public_bytes(Encoding.PEM)
    cert_path.write_bytes(cert_pem)
    key_path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    ca_path.write_text(AMAZON_ROOT_CA1, encoding="utf-8")
    return cert_path, key_path, ca_path
