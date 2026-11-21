"""Authentication against Govee's app API."""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

import aiohttp

from ..const import (
    APP_VERSION,
    AUTH_URL,
    REFRESH_URL,
    USER_AGENT,
)


class GoveeAuthError(Exception):
    """Raised when Govee rejects the credentials."""


def _base_headers(client_id: str) -> dict[str, str]:
    return {
        "clientType": "1",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "iotVersion": "0",
        "clientId": client_id,
        "User-Agent": USER_AGENT,
        "appVersion": APP_VERSION,
        "AppVersion": APP_VERSION,
    }


def generate_client_id() -> str:
    """Generate the client id the Govee app uses (md5 of a UUID and timestamp)."""
    seed = f"{uuid.uuid4()}{int(time.time() * 1000)}"
    return hashlib.md5(seed.encode(), usedforsecurity=False).hexdigest()


class GoveeAuth:
    """Owns the login/refresh lifecycle for one Govee account."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        email: str,
        password: str,
        client_id: str | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        expires_at: float | None = None,
        account_id: str | None = None,
        account_topic: str | None = None,
    ) -> None:
        self._session = session
        self.email = email
        self.password = password
        self.client_id = client_id or generate_client_id()
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at or 0.0
        self.account_id = account_id
        self.account_topic = account_topic

    @property
    def headers(self) -> dict[str, str]:
        """Return headers for an authenticated request."""
        headers = _base_headers(self.client_id)
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def login(self) -> dict[str, Any]:
        """Log in with the account's email and password."""
        payload = {
            "email": self.email,
            "password": self.password,
            "client": self.client_id,
        }
        async with self._session.post(
            AUTH_URL, json=payload, headers=_base_headers(self.client_id)
        ) as response:
            data = await _json(response)
        if response.status >= 400:
            message = data.get("message") or data.get("msg") or response.reason
            raise GoveeAuthError(str(message))
        client = data.get("client") or data.get("data") or {}
        if not client.get("token"):
            message = data.get("message") or data.get("msg") or "Login failed"
            raise GoveeAuthError(str(message))
        self._apply_login(client)
        return client

    async def refresh(self) -> None:
        """Refresh the access token using the stored refresh token."""
        if not self.access_token:
            await self.login()
            return
        async with self._session.get(REFRESH_URL, headers=self.headers) as response:
            data = await _json(response)
        if response.status >= 400:
            await self.login()
            return
        payload = data.get("data") or data
        token = payload.get("token") or payload.get("accessToken")
        if not token:
            await self.login()
            return
        self.access_token = token
        self.refresh_token = payload.get("refreshToken") or self.refresh_token
        cycle = payload.get("tokenExpireCycle")
        self.expires_at = time.time() + int(cycle) if cycle else time.time() + 86400

    async def ensure_valid(self) -> None:
        """Refresh the token when it is absent or about to expire."""
        if not self.access_token:
            await self.login()
            return
        if self.expires_at and self.expires_at - time.time() < 300:
            await self.refresh()

    def _apply_login(self, client: dict[str, Any]) -> None:
        self.access_token = client.get("token") or client.get("accessToken")
        self.refresh_token = client.get("refreshToken") or self.refresh_token
        cycle = client.get("tokenExpireCycle")
        self.expires_at = time.time() + int(cycle) if cycle else time.time() + 86400
        self.account_id = client.get("accountId") or self.account_id
        self.account_topic = client.get("topic") or self.account_topic
        self.client_id = client.get("clientId") or self.client_id

    def token_data(self) -> dict[str, Any]:
        """Return the token fields to persist in the config entry."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_expires_at": self.expires_at,
            "client_id": self.client_id,
            "account_id": self.account_id,
            "account_topic": self.account_topic,
        }


async def _json(response: aiohttp.ClientResponse) -> dict[str, Any]:
    try:
        data = await response.json(content_type=None)
    except aiohttp.ContentTypeError, ValueError:
        return {}
    return data if isinstance(data, dict) else {}
