"""Tests for WatchlistService tag/group operations."""

import pytest

from TerraFin.configuration import WatchlistConfig
from TerraFin.interface.watchlist_service import (
    WatchlistConfigurationError,
    WatchlistNotFoundError,
    WatchlistService,
    WatchlistValidationError,
    _normalize_tags,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


class _FakeMongoDB:
    """In-memory MongoDB stub."""

    def __init__(self) -> None:
        self._doc: dict | None = None

    def find_one(self, query: dict) -> dict | None:
        return dict(self._doc) if self._doc is not None else None

    def update_one(self, query: dict, update: dict, upsert: bool = False) -> None:
        set_fields = update.get("$set", {})
        if self._doc is None:
            self._doc = {"_id": query.get("_id", "test")}
        self._doc.update(set_fields)


class _FakeCollection:
    def __init__(self, db: _FakeMongoDB) -> None:
        self._db = db

    def find_one(self, query):
        return self._db.find_one(query)

    def update_one(self, query, update, upsert=False):
        return self._db.update_one(query, update, upsert)


def _make_service(initial_items: list[dict] | None = None) -> tuple[WatchlistService, _FakeMongoDB]:
    import TerraFin.interface.watchlist_service as mod

    fake_db = _FakeMongoDB()
    if initial_items is not None:
        fake_db._doc = {
            "_id": "terrafin_watchlist",
            "Company List": [i["symbol"] for i in initial_items],
            "items": initial_items,
        }

    config = WatchlistConfig(
        uri="mongodb://fake",
        database="db",
        collection="col",
        document_id="terrafin_watchlist",
    )
    svc = WatchlistService(config)

    # Patch MongoClient so the service uses our fake
    import TerraFin.interface.watchlist_service as watchlist_mod

    original_mongo = watchlist_mod.MongoClient

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __getitem__(self, db_name):
            return {config.collection: _FakeCollection(fake_db)}

    watchlist_mod.MongoClient = _FakeClient  # type: ignore
    svc._client = _FakeClient()

    return svc, fake_db


# ─── _normalize_tags ──────────────────────────────────────────────────────────


def test_normalize_tags_preserves_case_dedupes_insensitive():
    result = _normalize_tags(["Tech", "  TECH  ", "commodities", "Commodities"])
    assert result == ["Tech", "commodities"]


def test_normalize_tags_empty_strings_dropped():
    result = _normalize_tags(["", "  ", "ai"])
    assert result == ["ai"]


def test_normalize_tags_empty_list():
    assert _normalize_tags([]) == []


# ─── WatchlistItemRecord ──────────────────────────────────────────────────────


def test_watchlist_item_record_to_dict_includes_tags():
    from TerraFin.interface.watchlist_service import WatchlistItemRecord

    record = WatchlistItemRecord(symbol="AAPL", name="Apple", move="+1.23%", tags=["tech", "mega-cap"])
    d = record.to_dict()
    assert d["tags"] == ["tech", "mega-cap"]


def test_watchlist_item_record_default_empty_tags():
    from TerraFin.interface.watchlist_service import WatchlistItemRecord

    record = WatchlistItemRecord(symbol="AAPL", name="Apple", move="+1.23%")
    assert record.tags == []
    assert record.to_dict()["tags"] == []


# ─── Service: get_watchlist_snapshot with group filter ────────────────────────


def test_get_watchlist_snapshot_all(monkeypatch):
    items = [
        {"symbol": "AAPL", "name": "Apple", "move": "+1%", "tags": ["tech"]},
        {"symbol": "GLD", "name": "Gold ETF", "move": "-0.5%", "tags": ["commodities"]},
    ]
    svc, _ = _make_service(items)
    result = svc.get_watchlist_snapshot()
    assert len(result) == 2


def test_get_watchlist_snapshot_filter_by_group(monkeypatch):
    items = [
        {"symbol": "AAPL", "name": "Apple", "move": "+1%", "tags": ["tech"]},
        {"symbol": "GLD", "name": "Gold ETF", "move": "-0.5%", "tags": ["commodities"]},
        {"symbol": "NVDA", "name": "Nvidia", "move": "+2%", "tags": ["tech", "ai"]},
    ]
    svc, _ = _make_service(items)
    result = svc.get_watchlist_snapshot(group="tech")
    assert {r["symbol"] for r in result} == {"AAPL", "NVDA"}


def test_get_watchlist_snapshot_filter_case_insensitive(monkeypatch):
    items = [{"symbol": "AAPL", "name": "Apple", "move": "+1%", "tags": ["tech"]}]
    svc, _ = _make_service(items)
    result = svc.get_watchlist_snapshot(group="TECH")
    assert len(result) == 1


# ─── Service: set_tags / add_tags / remove_tags ───────────────────────────────


def test_set_tags_replaces(monkeypatch):
    items = [{"symbol": "AAPL", "name": "Apple", "move": "+1%", "tags": ["tech"]}]
    svc, _ = _make_service(items)
    result = svc.set_tags("AAPL", ["mega-cap", "dividends"])
    aapl = next(r for r in result if r["symbol"] == "AAPL")
    assert sorted(aapl["tags"]) == ["dividends", "mega-cap"]


def test_set_tags_normalizes(monkeypatch):
    items = [{"symbol": "AAPL", "name": "Apple", "move": "+1%", "tags": []}]
    svc, _ = _make_service(items)
    result = svc.set_tags("AAPL", ["TECH", "TECH"])
    aapl = next(r for r in result if r["symbol"] == "AAPL")
    assert aapl["tags"] == ["TECH"]


def test_add_tags_merges(monkeypatch):
    items = [{"symbol": "AAPL", "name": "Apple", "move": "+1%", "tags": ["tech"]}]
    svc, _ = _make_service(items)
    result = svc.add_tags("AAPL", ["ai", "tech"])  # "tech" already present
    aapl = next(r for r in result if r["symbol"] == "AAPL")
    assert sorted(aapl["tags"]) == ["ai", "tech"]


def test_remove_tags(monkeypatch):
    items = [{"symbol": "AAPL", "name": "Apple", "move": "+1%", "tags": ["tech", "ai"]}]
    svc, _ = _make_service(items)
    result = svc.remove_tags("AAPL", ["tech"])
    aapl = next(r for r in result if r["symbol"] == "AAPL")
    assert aapl["tags"] == ["ai"]


def test_set_tags_unknown_symbol_raises(monkeypatch):
    svc, _ = _make_service([])
    with pytest.raises(WatchlistNotFoundError):
        svc.set_tags("FAKE", ["tech"])


# ─── Service: rename_group ────────────────────────────────────────────────────


def test_rename_group_updates_all_items(monkeypatch):
    items = [
        {"symbol": "AAPL", "name": "Apple", "move": "+1%", "tags": ["tech", "mega-cap"]},
        {"symbol": "MSFT", "name": "Microsoft", "move": "+0.5%", "tags": ["tech"]},
        {"symbol": "GLD", "name": "Gold", "move": "-0.5%", "tags": ["commodities"]},
    ]
    svc, _ = _make_service(items)
    result = svc.rename_group("tech", "technology")
    by_symbol = {r["symbol"]: r for r in result}
    assert "technology" in by_symbol["AAPL"]["tags"]
    assert "tech" not in by_symbol["AAPL"]["tags"]
    assert "technology" in by_symbol["MSFT"]["tags"]
    assert "commodities" in by_symbol["GLD"]["tags"]


def test_rename_group_empty_name_raises(monkeypatch):
    svc, _ = _make_service([])
    with pytest.raises(WatchlistValidationError):
        svc.rename_group("tech", "")


# ─── Service: list_groups ────────────────────────────────────────────────────


def test_list_groups_counts_correctly(monkeypatch):
    items = [
        {"symbol": "AAPL", "name": "Apple", "move": "+1%", "tags": ["tech", "mega-cap"]},
        {"symbol": "MSFT", "name": "Microsoft", "move": "+0.5%", "tags": ["tech"]},
        {"symbol": "GLD", "name": "Gold", "move": "-0.5%", "tags": []},
    ]
    svc, _ = _make_service(items)
    groups = svc.list_groups()
    by_tag = {g["tag"]: g["count"] for g in groups}
    assert by_tag["tech"] == 2
    assert by_tag["mega-cap"] == 1
    assert "GLD" not in by_tag  # no unnamed items


# ─── Legacy doc: tags load as empty list ──────────────────────────────────────


def test_legacy_doc_without_tags_loads_empty(monkeypatch):
    """Existing Mongo docs without 'tags' key round-trip to tags=[]."""
    items = [{"symbol": "AAPL", "name": "Apple", "move": "+1%"}]  # no tags key
    svc, _ = _make_service(items)
    result = svc.get_watchlist_snapshot()
    assert result[0]["tags"] == []
