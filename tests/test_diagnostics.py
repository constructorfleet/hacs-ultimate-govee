"""Tests for the diagnostics view of typed transport status."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ultimate_govee.const import DOMAIN
from custom_components.ultimate_govee.coordinator import GoveeCoordinator
from custom_components.ultimate_govee.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_renders_typed_transport_status_as_json(
    hass: Any, tmp_path: Path
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "user@example.com", "password": "secret"},
        options={"enable_lan": True, "enable_iot": False},
    )
    entry.add_to_hass(hass)
    coordinator = GoveeCoordinator(hass, entry, async_get_clientsession(hass), tmp_path)
    entry.runtime_data = coordinator

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["lan"]["enabled"] is True
    assert diagnostics["iot"]["enabled"] is False
    assert diagnostics["iot"]["connected"] is False
    assert diagnostics["transports"]["lan_udp"]["enabled"] is True
    assert diagnostics["transports"]["cloud_mqtt"]["enabled"] is False
    # The payload must survive Home Assistant's JSON serializer.
    assert json.loads(json.dumps(diagnostics))["transports"]["ble_gatt"]["kind"] == "ble_gatt"
