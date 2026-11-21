"""One owner for per-device BLE GATT links.

The transport encodes frames and reports status; this module owns the actual
link set: opening on demand, reusing a live link, evicting an address change or
the least-recently-used link when the set is full, and closing everything on
stop. A stop is terminal until an explicit start, so shutdown cannot be undone
by a command that races it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

_LOGGER = logging.getLogger(__name__)


class BleLinkSetClosed(Exception):
    """The link set was stopped and will not reopen without a start."""


class BleLinkState(StrEnum):
    """The lifecycle state of a link set."""

    NEW = "new"
    STARTED = "started"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class BleLinkSpec:
    """What the connection owner needs to open one device link."""

    device_id: str
    address: str
    name: str


@dataclass(slots=True)
class _Link:
    handle: Any
    address: str
    last_used: float


class BleLinkSet:
    """A bounded set of BLE links, keyed by Govee device id."""

    def __init__(
        self,
        factory: Callable[[BleLinkSpec], Any],
        *,
        max_links: int = 8,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_links < 1:
            raise ValueError("max_links must be at least 1")
        self._factory = factory
        self._max_links = max_links
        self._clock = clock
        self._links: dict[str, _Link] = {}
        self._state = BleLinkState.NEW
        self._lock = asyncio.Lock()

    @property
    def state(self) -> BleLinkState:
        """Return the lifecycle state of the set."""
        return self._state

    @property
    def started(self) -> bool:
        """Whether the set is open for links (a first use starts it lazily)."""
        return self._state is BleLinkState.STARTED

    @property
    def connected(self) -> bool:
        """Whether any tracked link reports itself connected."""
        return any(bool(getattr(link.handle, "connected", False)) for link in self._links.values())

    @property
    def count(self) -> int:
        """Return the number of tracked links."""
        return len(self._links)

    def get(self, device_id: str) -> Any | None:
        """Return the tracked link handle for ``device_id``, if any."""
        link = self._links.get(device_id)
        return link.handle if link is not None else None

    def owns(self, device_id: str, handle: Any) -> bool:
        """Whether ``handle`` is still the current link for ``device_id``."""
        link = self._links.get(device_id)
        return link is not None and link.handle is handle

    async def async_close(self, handle: Any) -> None:
        """Close a handle that has already left the set."""
        await self._async_close(handle)

    async def async_start(self) -> None:
        """Allow links to be opened again after a stop."""
        async with self._lock:
            self._state = BleLinkState.STARTED

    async def async_stop(self) -> None:
        """Close every link and refuse new ones until the next start."""
        async with self._lock:
            self._state = BleLinkState.STOPPED
            links = list(self._links.values())
            self._links.clear()
            for link in links:
                await self._async_close(link.handle)

    async def async_evict(self, device_id: str) -> None:
        """Close and forget the link for ``device_id``."""
        async with self._lock:
            link = self._links.pop(device_id, None)
            if link is not None:
                await self._async_close(link.handle)

    async def async_acquire(self, spec: BleLinkSpec) -> Any:
        """Return a usable link for ``spec``, opening or evicting as needed.

        A set that was never started starts implicitly: entity commands can
        race setup and the alternative is a spurious "not sent". A set that was
        explicitly stopped stays stopped.
        """
        async with self._lock:
            if self._state is BleLinkState.STOPPED:
                raise BleLinkSetClosed("The BLE link set is stopped")
            if self._state is BleLinkState.NEW:
                self._state = BleLinkState.STARTED

            link = self._links.get(spec.device_id)
            if link is not None and link.address != spec.address:
                self._links.pop(spec.device_id)
                await self._async_close(link.handle)
                link = None
            if link is not None:
                link.last_used = self._clock()
                return link.handle

            while len(self._links) >= self._max_links:
                victim_id = min(self._links, key=lambda key: self._links[key].last_used)
                victim = self._links.pop(victim_id)
                _LOGGER.debug("Evicting idle BLE link for %s", victim_id)
                await self._async_close(victim.handle)

            handle = self._factory(spec)
            self._links[spec.device_id] = _Link(handle, spec.address, self._clock())
            return handle

    async def _async_close(self, handle: Any) -> None:
        stop = getattr(handle, "async_stop", None)
        if stop is None:
            return
        try:
            await stop()
        except Exception as err:  # cleanup must not mask the caller's result
            _LOGGER.debug("BLE link cleanup failed: %s", err)
