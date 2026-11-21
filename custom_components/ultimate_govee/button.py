"""Buttons for Govee tap-to-run / one-click scenes."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api.cloud import GoveeApiError
from .const import DOMAIN, MANUFACTURER, NAME
from .coordinator import GoveeCoordinator
from .tap_to_runs import TapToRun

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one button per account tap-to-run."""
    coordinator: GoveeCoordinator = entry.runtime_data
    if not coordinator.enable_tap_to_runs:
        return
    try:
        tap_to_runs = await coordinator.async_get_tap_to_runs()
    except (GoveeApiError, aiohttp.ClientError, OSError) as err:
        _LOGGER.warning("Unable to load Govee tap-to-runs: %s", err)
        return
    async_add_entities(
        GoveeTapToRunButton(coordinator, entry, tap_to_run) for tap_to_run in tap_to_runs
    )


class GoveeTapToRunButton(ButtonEntity):
    """Run a saved Govee one-click scene."""

    _attr_icon = "mdi:play-circle-outline"

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        entry: ConfigEntry,
        tap_to_run: TapToRun,
    ) -> None:
        self.coordinator = coordinator
        self._tap_to_run = tap_to_run
        self._attr_name = tap_to_run.name
        self._attr_unique_id = f"{entry.entry_id}_tap_{tap_to_run.key}"
        self._account_id = coordinator.auth.account_id or entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        """Attach every button to one account-level hub device."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"account_{self._account_id}")},
            manufacturer=MANUFACTURER,
            name=NAME,
            model="Govee account",
        )

    async def async_press(self) -> None:
        """Send every command in the tap-to-run."""
        try:
            await self.coordinator.async_run_tap_to_run(self._tap_to_run)
        except GoveeApiError as err:
            raise HomeAssistantError(str(err)) from err
