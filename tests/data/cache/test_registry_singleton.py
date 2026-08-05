"""The cache-manager singleton must be built exactly once under concurrency.

Without the construction lock, concurrent first-callers each build a manager and
all but one are discarded. A thread that registered a per-ticker payload spec on
a discarded instance then fails with "Unknown cache payload source" when it
reads back from the winner — observed as dropped symbols in the 8-thread
watchlist scanner and universe price fan-outs.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

from TerraFin.data.cache import registry


def test_concurrent_callers_share_one_manager(monkeypatch) -> None:
    monkeypatch.setattr(registry, "_cache_manager", None)

    built: list[object] = []
    real_ctor = registry.CacheManager

    def counting_ctor(*args, **kwargs):
        manager = real_ctor(*args, **kwargs)
        built.append(manager)
        return manager

    monkeypatch.setattr(registry, "CacheManager", counting_ctor)

    barrier = threading.Barrier(8)

    def race():
        barrier.wait()  # maximise the chance of a simultaneous first call
        return registry.get_cache_manager()

    with ThreadPoolExecutor(max_workers=8) as pool:
        managers = list(pool.map(lambda _: race(), range(8)))

    assert len(built) == 1, f"manager was constructed {len(built)} times; the construction lock is not holding"
    assert len({id(manager) for manager in managers}) == 1, "callers received different manager instances"


def test_payload_registered_by_one_thread_is_visible_to_another(monkeypatch) -> None:
    """The failure mode the lock exists to prevent, reduced to two threads."""

    from TerraFin.data.cache.manager import CachePayloadSpec

    monkeypatch.setattr(registry, "_cache_manager", None)

    def register_then_read(index: int) -> object:
        manager = registry.get_cache_manager()
        source = f"test.parity.{index}"
        manager.register_payload(
            CachePayloadSpec(
                source=source,
                namespace="test_registry_singleton",
                key=f"probe-{index}",
                ttl_seconds=60,
                fetch_fn=lambda: {"ok": index},
            )
        )
        # Reading through a freshly resolved manager must see the spec above.
        return registry.get_cache_manager().get_payload(source).payload

    with ThreadPoolExecutor(max_workers=4) as pool:
        payloads = list(pool.map(register_then_read, range(4)))

    assert payloads == [{"ok": index} for index in range(4)]
