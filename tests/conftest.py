"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from homeassistant.components import bluetooth as _bluetooth  # noqa: F401

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Make Home Assistant discover the custom integration in every test."""


@pytest.fixture(autouse=True)
def mock_bluetooth_history() -> Iterator[None]:
    """Avoid loading real BlueZ history on non-Linux test hosts."""
    with patch(
        "homeassistant.components.bluetooth.manager.async_load_history_from_system",
        return_value=({}, {}),
    ):
        yield


@pytest.fixture(autouse=True)
def auto_enable_bluetooth(mock_bluetooth_history: None, enable_bluetooth: None) -> None:
    """Provide the Bluetooth dependency the integration now declares.

    The fixtures come from pytest-homeassistant-custom-component and mock the
    scanner/adapters, so no real Bluetooth adapter is required.
    """
