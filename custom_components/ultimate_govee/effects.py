"""Named light effects for Govee devices."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import aiohttp

from .api.cloud import GoveeApiError, GoveeCloud
from .models import GoveeDevice

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Effect:
    """A named effect and the frames that select it."""

    name: str
    frames: tuple[Any, ...]


class EffectsLibrary:
    """Cache the named effects for a SKU.

    The cloud endpoint is keyed by device but the catalogue is identical for
    every device of a SKU, so the cache is shared by SKU. Moving to a
    per-device cache later is an implementation change behind this interface.
    """

    def __init__(self, cloud: GoveeCloud, *, enabled: bool) -> None:
        self._cloud = cloud
        self._enabled = enabled
        self._cache: dict[str, tuple[Effect, ...]] = {}
        self._loaded: set[str] = set()
        self._inflight: dict[str, asyncio.Task[tuple[Effect, ...]]] = {}

    @property
    def enabled(self) -> bool:
        """Return whether the effect library is enabled."""
        return self._enabled

    def effects(self, device: GoveeDevice) -> tuple[Effect, ...]:
        """Return the cached effects for a device's SKU."""
        return self._cache.get(device.sku, ())

    async def async_load(self, device: GoveeDevice) -> tuple[Effect, ...]:
        """Load effects once, coalescing concurrent requests for a SKU."""
        if not self._enabled:
            return ()
        sku = device.sku
        if sku in self._loaded:
            return self._cache.get(sku, ())

        task = self._inflight.get(sku)
        if task is None:
            task = asyncio.create_task(self._fetch(device))
            self._inflight[sku] = task

            def _clear(done: asyncio.Task[tuple[Effect, ...]]) -> None:
                if self._inflight.get(sku) is done:
                    self._inflight.pop(sku, None)

            task.add_done_callback(_clear)
        return await asyncio.shield(task)

    async def _fetch(self, device: GoveeDevice) -> tuple[Effect, ...]:
        try:
            raw = await self._cloud.get_effects(
                device.sku,
                device=device.device_id,
            )
        except (GoveeApiError, aiohttp.ClientError, TimeoutError, OSError) as err:
            _LOGGER.debug("Unable to load effects for %s: %s", device.name, err)
            effects: tuple[Effect, ...] = ()
        else:
            effects = _normalize(raw)
        self._cache[device.sku] = effects
        self._loaded.add(device.sku)
        return effects


def _normalize(raw: Iterable[Mapping[str, Any]]) -> tuple[Effect, ...]:
    effects: list[Effect] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not name:
            continue
        frames = item.get("opCode") or item.get("code")
        if isinstance(frames, str):
            frames = (frames,)
        elif isinstance(frames, (list, tuple)):
            frames = tuple(frames)
        else:
            continue
        if not frames:
            continue
        effects.append(Effect(str(name), frames))
    return tuple(effects)
