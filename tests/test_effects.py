"""Tests for the effects library."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from custom_components.ultimate_govee.api.cloud import GoveeApiError
from custom_components.ultimate_govee.effects import Effect, EffectsLibrary
from custom_components.ultimate_govee.models import DeviceState, GoveeDevice
from custom_components.ultimate_govee.profiles import profile_for


class FakeCloud:
    """Minimal cloud double for effect lookups."""

    def __init__(self, effects=None, error=None):
        self.effects = effects or []
        self.error = error
        self.calls = []

    async def get_effects(self, sku, *, device=None):
        self.calls.append((sku, device))
        if self.error is not None:
            raise self.error
        return self.effects


def make_device(sku="H6001", device_id="device-1"):
    return GoveeDevice(
        device_id=device_id,
        sku=sku,
        name="Lamp",
        iot_topic=f"topic/{device_id}",
        firmware=None,
        hardware=None,
        settings={},
        profile=profile_for(sku),
        state=DeviceState(online=True),
    )


def test_disabled_library_never_calls_cloud():
    cloud = FakeCloud([{"name": "Sunrise", "opCode": [1, 2, 3]}])
    library = EffectsLibrary(cloud, enabled=False)
    device = make_device()

    asyncio.run(library.async_load(device))

    assert library.effects(device) == ()
    assert cloud.calls == []


def test_library_normalizes_effects_and_caches_by_sku():
    cloud = FakeCloud(
        [
            {"name": "Sunrise", "opCode": "AQID"},
            {"name": "Ocean", "code": [4, 5, 6]},
            {"name": "Broken"},
            {"opCode": "no-name"},
        ]
    )
    library = EffectsLibrary(cloud, enabled=True)
    device = make_device()
    other = make_device(device_id="device-2")

    asyncio.run(library.async_load(device))
    asyncio.run(library.async_load(other))

    assert library.effects(device) == (
        Effect("Sunrise", ("AQID",)),
        Effect("Ocean", (4, 5, 6)),
    )
    assert library.effects(other) == library.effects(device)
    assert cloud.calls == [("H6001", "device-1")]


def test_concurrent_loads_coalesce():
    class SlowCloud(FakeCloud):
        async def get_effects(self, sku, *, device=None):
            self.calls.append((sku, device))
            await asyncio.sleep(0)
            return [{"name": "Sunrise", "opCode": "AQID"}]

    cloud = SlowCloud()
    library = EffectsLibrary(cloud, enabled=True)
    device = make_device()

    async def load_twice():
        await asyncio.gather(library.async_load(device), library.async_load(device))

    asyncio.run(load_twice())

    assert cloud.calls == [("H6001", "device-1")]
    assert len(library.effects(device)) == 1


def test_failed_load_is_negative_cached():
    cloud = FakeCloud(error=aiohttp.ClientError("offline"))
    library = EffectsLibrary(cloud, enabled=True)
    device = make_device()

    asyncio.run(library.async_load(device))
    asyncio.run(library.async_load(device))

    assert library.effects(device) == ()
    assert cloud.calls == [("H6001", "device-1")]


def test_govee_api_error_is_negative_cached():
    cloud = FakeCloud(error=GoveeApiError("nope"))
    library = EffectsLibrary(cloud, enabled=True)
    device = make_device()

    asyncio.run(library.async_load(device))

    assert library.effects(device) == ()


def test_cancelled_waiter_does_not_start_a_second_fetch() -> None:
    """Cancelling one waiter leaves the shared fetch in flight for the next caller."""

    class BlockingCloud(FakeCloud):
        async def get_effects(self, sku, *, device=None):
            self.calls.append((sku, device))
            self.started.set()
            await self.release.wait()
            return [{"name": "Sunrise", "opCode": "AQID"}]

    async def scenario():
        cloud = BlockingCloud()
        cloud.started = asyncio.Event()
        cloud.release = asyncio.Event()
        library = EffectsLibrary(cloud, enabled=True)
        target = make_device()

        first = asyncio.create_task(library.async_load(target))
        await cloud.started.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

        second = asyncio.create_task(library.async_load(target))
        await asyncio.sleep(0)
        assert cloud.calls == [("H6001", "device-1")]

        cloud.release.set()
        await second
        assert library.effects(target) == (Effect("Sunrise", ("AQID",)),)

    asyncio.run(scenario())
