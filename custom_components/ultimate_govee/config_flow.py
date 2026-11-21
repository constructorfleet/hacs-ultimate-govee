"""Config and options flows for the Ultimate Govee integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.auth import GoveeAuth, GoveeAuthError, generate_client_id
from .api.cloud import GoveeApiError, GoveeCloud
from .const import (
    CONF_EMAIL,
    CONF_ENABLE_IOT,
    CONF_ENABLE_LAN,
    CONF_LAN_SCAN_INTERVAL,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    DEFAULT_ENABLE_IOT,
    DEFAULT_ENABLE_LAN,
    DEFAULT_LAN_SCAN_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class UltimateGoveeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in to a Govee account."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Ask for the account credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            auth = GoveeAuth(
                async_get_clientsession(self.hass),
                email=user_input[CONF_EMAIL],
                password=user_input[CONF_PASSWORD],
                client_id=generate_client_id(),
            )
            try:
                await auth.login()
                await GoveeCloud(async_get_clientsession(self.hass), auth).get_devices()
            except GoveeAuthError:
                errors["base"] = "invalid_auth"
            except GoveeApiError, aiohttp.ClientError, TimeoutError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating Govee credentials")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(auth.account_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=str(auth.account_id or user_input[CONF_EMAIL]),
                    data={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        **auth.token_data(),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Start reauthentication after a rejected token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for the password again."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="reauth_failed")
        errors: dict[str, str] = {}
        if user_input is not None:
            auth = GoveeAuth(
                async_get_clientsession(self.hass),
                email=entry.data[CONF_EMAIL],
                password=user_input[CONF_PASSWORD],
                client_id=generate_client_id(),
            )
            try:
                await auth.login()
            except GoveeAuthError:
                errors["base"] = "invalid_auth"
            except GoveeApiError, aiohttp.ClientError, TimeoutError:
                errors["base"] = "cannot_connect"
            else:
                if entry.unique_id and auth.account_id and entry.unique_id != auth.account_id:
                    return self.async_abort(reason="wrong_account")
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        **auth.token_data(),
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return UltimateGoveeOptionsFlow()


class UltimateGoveeOptionsFlow(OptionsFlow):
    """Tune transport and polling behaviour."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show the options form."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ENABLE_LAN,
                    default=options.get(CONF_ENABLE_LAN, DEFAULT_ENABLE_LAN),
                ): bool,
                vol.Optional(
                    CONF_ENABLE_IOT,
                    default=options.get(CONF_ENABLE_IOT, DEFAULT_ENABLE_IOT),
                ): bool,
                vol.Optional(
                    CONF_POLL_INTERVAL,
                    default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_POLL_INTERVAL,
                        max=MAX_POLL_INTERVAL,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_LAN_SCAN_INTERVAL,
                    default=options.get(CONF_LAN_SCAN_INTERVAL, DEFAULT_LAN_SCAN_INTERVAL),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_POLL_INTERVAL,
                        max=MAX_POLL_INTERVAL,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
