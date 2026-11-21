"""Tests for the config and options flows."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ultimate_govee import config_flow
from custom_components.ultimate_govee.api.auth import GoveeAuthError
from custom_components.ultimate_govee.const import DOMAIN


class FakeAuth:
    """A stand-in for GoveeAuth that does not touch the network."""

    account_id = "account-1"
    account_topic = "topic-1"

    def __init__(self, session: Any, **kwargs: Any) -> None:
        self.email = kwargs["email"]
        self.password = kwargs["password"]
        self.client_id = kwargs.get("client_id") or "client-1"
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0.0

    async def login(self) -> dict[str, Any]:
        self.access_token = "access"
        self.refresh_token = "refresh"
        self.expires_at = 9999999999.0
        return {"accountId": self.account_id}

    def token_data(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_expires_at": self.expires_at,
            "client_id": self.client_id,
            "account_id": self.account_id,
            "account_topic": self.account_topic,
        }


class FakeCloud:
    """A stand-in for GoveeCloud."""

    def __init__(self, session: Any, auth: Any) -> None:
        self.auth = auth

    async def get_devices(self) -> list[dict[str, Any]]:
        return []


class RejectingAuth(FakeAuth):
    """An auth that rejects the credentials."""

    async def login(self) -> dict[str, Any]:
        raise GoveeAuthError("bad password")


@pytest.fixture(autouse=True)
def patch_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the network clients with fakes."""
    monkeypatch.setattr(config_flow, "GoveeAuth", FakeAuth)
    monkeypatch.setattr(config_flow, "GoveeCloud", FakeCloud)


@pytest.fixture(autouse=True)
def patch_coordinator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the config-flow tests from starting real transports."""

    async def _setup(self: Any) -> None:
        self.devices = {}

    async def _refresh(self: Any) -> None:
        self.devices = {}

    monkeypatch.setattr(
        "custom_components.ultimate_govee.coordinator.GoveeCoordinator.async_setup",
        _setup,
    )
    monkeypatch.setattr(
        "custom_components.ultimate_govee.coordinator.GoveeCoordinator.async_config_entry_first_refresh",
        _refresh,
    )


async def test_user_flow_creates_entry(hass: Any) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "account-1"
    assert result["data"][CONF_EMAIL] == "user@example.com"
    assert result["data"]["access_token"] == "access"
    assert result["data"]["account_id"] == "account-1"


async def test_user_flow_rejects_bad_credentials(
    hass: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config_flow, "GoveeAuth", RejectingAuth)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "wrong"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_duplicate_account_aborts(hass: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="account-1",
        data={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_password(hass: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="account-1",
        data={
            CONF_EMAIL: "user@example.com",
            CONF_PASSWORD: "old",
            "account_id": "account-1",
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new"
    assert entry.data["access_token"] == "access"


async def test_options_flow(hass: Any) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "ignored_devices": ["device-1"],
            "enable_effects": False,
            "enable_tap_to_runs": True,
            "enable_lan": False,
            "enable_iot": True,
            "poll_interval": 120,
            "lan_scan_interval": 30,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["enable_lan"] is False
    assert entry.options["enable_effects"] is False
    assert entry.options["enable_tap_to_runs"] is True
    assert entry.options["ignored_devices"] == ["device-1"]
    assert entry.options["poll_interval"] == 120
