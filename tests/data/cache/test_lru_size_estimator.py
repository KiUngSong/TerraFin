"""LRU size estimator + eviction for frozen payloads."""

from __future__ import annotations

import pandas as pd

from TerraFin.data.cache import manager as manager_module
from TerraFin.data.cache.manager import (
    CacheManager,
    CachePayloadSpec,
    _default_size_estimator,
)


def test_str_size_matches_utf8_bytes() -> None:
    payload = "hello world"
    assert _default_size_estimator(payload) == len(payload.encode("utf-8"))


def test_dataframe_size_positive() -> None:
    df = pd.DataFrame({"a": range(1000), "b": [f"row_{i}" for i in range(1000)]})
    size = _default_size_estimator(df)
    assert size > 0


def test_frozen_str_payload_recorded_size(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(manager_module, "_FILE_CACHE_DIR", tmp_path)
    manager = CacheManager()
    payload_str = "x" * 1024
    spec = CachePayloadSpec(
        source="frozen_str",
        namespace="ns",
        key="k",
        ttl_seconds=3600,
        fetch_fn=lambda: payload_str,
        frozen_payload=True,
    )
    manager.register_payload(spec)
    manager.get_payload("frozen_str")
    entry = manager._memory_payloads["frozen_str"]
    assert entry.size == len(payload_str.encode("utf-8"))


def test_eviction_fires_when_budget_exceeded(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(manager_module, "_FILE_CACHE_DIR", tmp_path)
    monkeypatch.setattr(manager_module, "MEMORY_LRU_FROZEN_MAX_BYTES", 4096)

    manager = CacheManager()
    big = "y" * 3000  # 3000 bytes utf-8

    for i in range(3):
        source = f"frozen_{i}"
        spec = CachePayloadSpec(
            source=source,
            namespace="ns",
            key=source,
            ttl_seconds=3600,
            fetch_fn=lambda v=big: v,
            frozen_payload=True,
        )
        manager.register_payload(spec)
        manager.get_payload(source)

    total = sum(e.size for e in manager._memory_payloads.values() if e.frozen)
    assert total <= 4096
    assert len(manager._memory_payloads) < 3
