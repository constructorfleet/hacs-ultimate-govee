"""Shared entity plumbing for the Ultimate Govee integration."""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.cloud import GoveeApiError
from .const import DOMAIN, MANUFACTURER
from .coordinator import GoveeCoordinator
from .models import GoveeDevice
from .protocol.command import Command


class GoveeEntity(CoordinatorEntity[GoveeCoordinator]):
    """Base class for every entity backed by a Govee device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GoveeCoordinator, device_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_{key}"

    @property
    def device(self) -> GoveeDevice:
        """Return the device this entity belongs to."""
        return self.coordinator.devices[self._device_id]

    @property
    def available(self) -> bool:
        """Return whether the device is reachable."""
        return super().available and self.device.available

    @property
    def device_info(self) -> DeviceInfo:
        """Return the registry information for the device."""
        device = self.device
        return DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            manufacturer=MANUFACTURER,
            name=device.name,
            model=device.sku or device.profile.model_name,
            sw_version=device.firmware,
            hw_version=device.hardware,
        )

    async def _send(self, command: Command, optimistic: dict[str, Any] | None = None) -> None:
        try:
            await self.coordinator.async_send(self.device, command, optimistic=optimistic)
        except GoveeApiError as err:
            raise HomeAssistantError(str(err)) from err
