"""Govee cloud REST endpoints used by the integration."""

from __future__ import annotations

import contextlib
from typing import Any

import aiohttp

from ..const import (
    DEVICE_LIST_URL,
    EFFECT_LIBRARY_URL,
    IOT_CERT_URL,
    TAP_TO_RUN_URL,
)
from .auth import GoveeAuth, GoveeAuthError


class GoveeApiError(Exception):
    """Raised when the Govee API returns an error."""


class GoveeCloud:
    """Small typed wrapper over the endpoints the integration needs."""

    def __init__(self, session: aiohttp.ClientSession, auth: GoveeAuth) -> None:
        self._session = session
        self._auth = auth

    async def get_devices(self) -> list[dict[str, Any]]:
        """Return every device on the account."""
        data = await self._request("POST", DEVICE_LIST_URL, json={})
        devices = data.get("devices") or data.get("data", {}).get("devices") or []
        return [device for device in devices if isinstance(device, dict)]

    async def get_iot_certificate(self) -> dict[str, Any]:
        """Return the mutual-TLS certificate bundle for AWS IoT."""
        data = await self._request("GET", IOT_CERT_URL)
        payload = data.get("data") or data
        if not isinstance(payload, dict) or not payload.get("p12"):
            message = "Govee did not return an IoT certificate"
            raise GoveeApiError(message)
        return payload

    async def get_effects(
        self, sku: str, *, goods_type: int = 0, device: str | None = None
    ) -> list[dict[str, Any]]:
        """Return the light-effect library for a SKU."""
        params = {"sku": sku, "goodsType": str(goods_type)}
        if device:
            params["device"] = device
        data = await self._request("GET", EFFECT_LIBRARY_URL, params=params)
        return _flatten_effects(data.get("data") or data)

    async def get_tap_to_runs(self) -> list[dict[str, Any]]:
        """Return the account's one-click/tap-to-run components."""
        data = await self._request("GET", TAP_TO_RUN_URL)
        payload = data.get("data") or data
        components = payload.get("components") if isinstance(payload, dict) else None
        return [item for item in components or [] if isinstance(item, dict)]

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        await self._auth.ensure_valid()
        for attempt in range(2):
            async with self._session.request(
                method, url, headers=self._auth.headers, **kwargs
            ) as response:
                data = await _json(response)
                if response.status == 401 and attempt == 0:
                    with contextlib.suppress(GoveeAuthError):
                        await self._auth.refresh()
                    continue
                if response.status >= 400:
                    message = data.get("message") or data.get("msg") or response.reason
                    raise GoveeApiError(str(message))
                if data.get("status") not in (None, 200):
                    message = data.get("message") or data.get("msg")
                    raise GoveeApiError(str(message))
                return data
        raise GoveeApiError("Govee rejected the request after refreshing the token")


def _flatten_effects(data: Any) -> list[dict[str, Any]]:
    """Flatten the effect library's category tree into a list of effects."""
    effects: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            effects.extend(_flatten_effects(item))
        return effects
    if not isinstance(data, dict):
        return effects
    if isinstance(data.get("effects"), list):
        for effect in data["effects"]:
            if isinstance(effect, dict) and effect.get("name"):
                effects.append(effect)
    for key in ("categories", "data", "scenes"):
        value = data.get(key)
        if isinstance(value, (list, dict)):
            effects.extend(_flatten_effects(value))
    if data.get("name") and (data.get("opCode") or data.get("code")):
        effects.append(data)
    return effects


async def _json(response: aiohttp.ClientResponse) -> dict[str, Any]:
    try:
        data = await response.json(content_type=None)
    except aiohttp.ContentTypeError, ValueError:
        return {}
    return data if isinstance(data, dict) else {}
