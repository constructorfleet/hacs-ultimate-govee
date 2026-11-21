"""Set up the Ultimate Govee integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.auth import GoveeAuthError
from .const import DOMAIN, PLATFORMS
from .coordinator import GoveeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ultimate Govee from a config entry."""
    cert_dir = Path(hass.config.path(".storage", DOMAIN, entry.entry_id))
    coordinator = GoveeCoordinator(
        hass,
        entry,
        async_get_clientsession(hass),
        cert_dir,
    )
    try:
        await coordinator.async_setup()
    except GoveeAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _async_remove_ignored_devices(hass, entry, coordinator)
    _persist_tokens(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform(platform) for platform in PLATFORMS]
    )
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and stop its transports."""
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, [Platform(platform) for platform in PLATFORMS]
    )
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _persist_tokens(hass: HomeAssistant, entry: ConfigEntry, coordinator: GoveeCoordinator) -> None:
    """Store refreshed tokens back on the config entry."""
    tokens = coordinator.auth.token_data()
    if all(entry.data.get(key) == value for key, value in tokens.items()):
        return
    hass.config_entries.async_update_entry(entry, data={**entry.data, **tokens})


def _async_remove_ignored_devices(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: GoveeCoordinator
) -> None:
    """Remove registry entries for devices the user has opted out of."""
    if not coordinator.ignored_devices:
        return
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    for device_id in coordinator.ignored_devices:
        registry_device = device_registry.async_get_device_by_identifier(
            (DOMAIN, device_id), entry.entry_id
        )
        if registry_device is None:
            continue
        for entity in er.async_entries_for_device(
            entity_registry, registry_device.id, include_disabled_entities=True
        ):
            entity_registry.async_remove(entity.entity_id)
        device_registry.async_remove_device(registry_device.id)
