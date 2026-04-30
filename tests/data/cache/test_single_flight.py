"""Single-flight semantics for CacheManager.get_payload."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from TerraFin.data.cache.manager import (
    CacheManager,
    CachePayloadSpec,
)


def test_concurrent_get_payload_calls_fetch_fn_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "TerraFin.data.cache.manager._FILE_CACHE_DIR",
        tmp_path,
    )

    call_count = 0
    call_lock = threading.Lock()
    barrier = threading.Barrier(10)

    def fetch_fn():
        nonlocal call_count
        with call_lock:
            call_count += 1
        time.sleep(0.05)
        return {"value": 42}

    manager = CacheManager()
    spec = CachePayloadSpec(
        source="test_source",
        namespace="test_ns",
        key="test_key",
        ttl_seconds=3600,
        fetch_fn=fetch_fn,
        frozen_payload=False,
    )
    manager.register_payload(spec)

    def worker():
        barrier.wait()
        return manager.get_payload("test_source")

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(worker) for _ in range(10)]
        results = [f.result() for f in futures]

    assert call_count == 1
    for result in results:
        assert result.payload == {"value": 42}
        assert result.freshness == "fresh"
