"""Declarative custom-indicator registry: loader merge, executor, catalog.

Hand-rolled in-memory Mongo fakes (house convention, no mongomock). The fake
here supports the operator-dict filters the specs use ({"$ne": None}), which
the shared market-voices fake does not.
"""

import json

import pytest

from TerraFin.interface.pages.chart import custom_indicators as ci


# ── In-memory Mongo fake (supports {"$ne": ...} operator filters) ──────────


def _matches(doc: dict, query: dict) -> bool:
    for key, cond in query.items():
        value = doc.get(key)
        if isinstance(cond, dict):
            for op, operand in cond.items():
                if op == "$ne":
                    if value == operand:
                        return False
                else:
                    raise NotImplementedError(f"fake does not support {op}")
        elif value != cond:
            return False
    return True


class _FakeCursor:
    def __init__(self, docs: list[dict], projection: dict | None) -> None:
        self._docs = docs
        self._projection = projection or {}

    def sort(self, key, direction=1):
        ordered = sorted(self._docs, key=lambda d: d.get(key), reverse=direction < 0)
        return _FakeCursor(ordered, self._projection)

    def _project(self, doc: dict) -> dict:
        included = {k for k, v in self._projection.items() if k != "_id" and v}
        if included:
            return {k: v for k, v in doc.items() if k in included}
        if self._projection.get("_id") == 0:
            return {k: v for k, v in doc.items() if k != "_id"}
        return dict(doc)

    def __iter__(self):
        return iter(self._project(doc) for doc in self._docs)


class _FakeCollection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self._docs = [dict(d) for d in (docs or [])]

    def find(self, query: dict, projection: dict | None = None):
        return _FakeCursor([dict(d) for d in self._docs if _matches(d, query)], projection)


class _FakeClient:
    def __init__(self, collections: dict[str, dict[str, _FakeCollection]] | None = None) -> None:
        self._dbs = collections or {}

    def __getitem__(self, db_name: str):
        return self._dbs.setdefault(db_name, {})


class _BrokenClient:
    def __getitem__(self, db_name: str):
        raise ConnectionError("mongo unreachable")


_NEWS_DOCS = [
    {"as_of_date": "2026-06-01", "pos_share": 0.5, "neu_share": 0.3, "neg_share": 0.2, "entropy_ma20": 0.9},
    # Broken/unfinished row: excluded by both default specs' filters.
    {"as_of_date": "2026-06-02", "pos_share": None, "neu_share": None, "neg_share": None, "entropy_ma20": None},
    {"as_of_date": "2026-05-31", "pos_share": 0.4, "neu_share": 0.4, "neg_share": 0.2, "entropy_ma20": 1.0},
]


# Injected as the default layer so tests don't depend on the (uncommitted,
# git-ignored) local default_indicators.json.
_DEFAULT_SPEC_DOCS = [
    {
        "name": "News Sentiment",
        "description": "News sentiment band.",
        "group": "Sentiment",
        "series_type": "band",
        "source": {
            "kind": "mongo",
            "database": "market_data",
            "collection": "news_sentiment",
            "time_field": "as_of_date",
            "fields": {"pos": "pos_share", "neu": "neu_share", "neg": "neg_share"},
            "filter": {"pos_share": {"$ne": None}},
        },
        "price_scale_id": "news-sentiment",
    },
    {
        "name": "Sentiment Entropy",
        "description": "Sentiment entropy line.",
        "group": "Sentiment",
        "series_type": "line",
        "source": {
            "kind": "mongo",
            "database": "market_data",
            "collection": "news_sentiment",
            "time_field": "as_of_date",
            "value_field": "entropy_ma20",
            "filter": {"entropy_ma20": {"$ne": None}},
        },
    },
    {
        "name": "Sentiment Conviction",
        "description": "Sentiment conviction line.",
        "group": "Sentiment",
        "series_type": "line",
        "source": {
            "kind": "mongo",
            "database": "market_data",
            "collection": "news_sentiment",
            "time_field": "as_of_date",
            "value_field": "conviction",
            "filter": {"conviction": {"$ne": None}},
        },
    },
]


def _install_fake_mongo(monkeypatch, spec_docs: list[dict] | None = None) -> None:
    client = _FakeClient(
        {
            "market_data": {
                "news_sentiment": _FakeCollection(_NEWS_DOCS),
                "indicator_specs": _FakeCollection(spec_docs),
            }
        }
    )
    monkeypatch.setattr(ci, "_client", client)


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch, tmp_path):
    """No live Mongo, no shared client cache, local file defaults to missing."""
    monkeypatch.setattr(ci, "MongoClient", None)
    monkeypatch.setattr(ci, "_client", None)
    monkeypatch.setattr(ci, "_mongo_specs_cache", None)
    monkeypatch.setattr(ci, "DEFAULT_SPECS", _DEFAULT_SPEC_DOCS)
    monkeypatch.setenv(ci.INDICATORS_PATH_ENV, str(tmp_path / "indicators.json"))


# ── Executor ────────────────────────────────────────────────────────────────


def test_executor_band_item_matches_legacy_news_sentiment_shape(monkeypatch):
    _install_fake_mongo(monkeypatch)
    specs = ci.load_custom_indicators()
    item = ci.build_custom_indicator(specs["News Sentiment"])
    assert item == {
        "id": "News Sentiment",
        "seriesType": "band",
        "data": [
            {"time": "2026-05-31", "pos": 0.4, "neu": 0.4, "neg": 0.2},
            {"time": "2026-06-01", "pos": 0.5, "neu": 0.3, "neg": 0.2},
        ],
        "indicator": False,
        "description": "News sentiment band.",
        # band earns its own pane/scale.
        "priceScaleId": "news-sentiment",
        "ownScale": True,
    }


def test_executor_line_item_shape(monkeypatch):
    # A line carries no priceScaleId/ownScale: the layout pass gives it an
    # overlay scale, exactly like any other indicator line.
    _install_fake_mongo(monkeypatch)
    specs = ci.load_custom_indicators()
    item = ci.build_custom_indicator(specs["Sentiment Entropy"])
    assert item == {
        "id": "Sentiment Entropy",
        "seriesType": "line",
        "data": [
            {"time": "2026-05-31", "value": 1.0},
            {"time": "2026-06-01", "value": 0.9},
        ],
        "indicator": False,
        "description": "Sentiment entropy line.",
    }


def test_executor_degrades_to_empty_data_when_mongo_unavailable():
    specs = ci.load_custom_indicators()
    item = ci.build_custom_indicator(specs["News Sentiment"])
    assert item["data"] == []
    assert item["seriesType"] == "band"


def test_executor_drops_broken_client_and_returns_empty(monkeypatch):
    monkeypatch.setattr(ci, "_client", _BrokenClient())
    specs = ci.load_custom_indicators()  # spec layer also fails -> defaults only
    item = ci.build_custom_indicator(specs["Sentiment Entropy"])
    assert item["data"] == []
    assert ci._client is None  # broken client dropped so the next call rebuilds


# ── Loader: 3-layer merge ───────────────────────────────────────────────────


def _spec(name: str, **overrides) -> dict:
    base = {
        "name": name,
        "description": f"{name} description",
        "group": "Sentiment",
        "series_type": "line",
        "source": {
            "kind": "mongo",
            "database": "market_data",
            "collection": "news_sentiment",
            "time_field": "as_of_date",
            "value_field": "entropy_ma20",
            "filter": {"entropy_ma20": {"$ne": None}},
        },
    }
    base.update(overrides)
    return base


def test_merge_precedence_default_lt_mongo_lt_local(monkeypatch, tmp_path):
    _install_fake_mongo(
        monkeypatch,
        spec_docs=[
            _spec("Sentiment Entropy", description="mongo override"),
            _spec("Mongo Only"),
        ],
    )
    local_path = tmp_path / "indicators.json"
    local_path.write_text(
        json.dumps([_spec("Sentiment Entropy", description="local override"), _spec("Local Only")]),
        encoding="utf-8",
    )
    monkeypatch.setenv(ci.INDICATORS_PATH_ENV, str(local_path))

    specs = ci.load_custom_indicators()
    assert specs["Sentiment Entropy"].description == "local override"
    assert "Mongo Only" in specs
    assert "Local Only" in specs
    # Untouched default survives the merge.
    assert specs["News Sentiment"].series_type == "band"


def test_loader_defaults_survive_mongo_failure(monkeypatch):
    monkeypatch.setattr(ci, "_client", _BrokenClient())
    specs = ci.load_custom_indicators()
    assert set(specs) == {"News Sentiment", "Sentiment Entropy", "Sentiment Conviction"}
    assert ci._client is None


def test_loader_ignores_malformed_local_json(monkeypatch, tmp_path):
    local_path = tmp_path / "indicators.json"
    local_path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(ci.INDICATORS_PATH_ENV, str(local_path))
    assert set(ci.load_custom_indicators()) == {"News Sentiment", "Sentiment Entropy", "Sentiment Conviction"}

    local_path.write_text(json.dumps({"name": "not a list"}), encoding="utf-8")
    assert set(ci.load_custom_indicators()) == {"News Sentiment", "Sentiment Entropy", "Sentiment Conviction"}


def test_loader_skips_invalid_specs_keeps_valid_ones(monkeypatch, tmp_path):
    local_path = tmp_path / "indicators.json"
    local_path.write_text(
        json.dumps(
            [
                _spec("Bad Type", series_type="scatter"),
                {"name": "No Source", "series_type": "line"},
                _spec(
                    "Both Value And Fields",
                    source={
                        "kind": "mongo",
                        "database": "db",
                        "collection": "col",
                        "time_field": "t",
                        "value_field": "v",
                        "fields": {"pos": "p", "neu": "n", "neg": "g"},
                    },
                ),
                "not even a dict",
                _spec("Good Local"),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(ci.INDICATORS_PATH_ENV, str(local_path))
    specs = ci.load_custom_indicators()
    assert set(specs) == {"News Sentiment", "Sentiment Entropy", "Sentiment Conviction", "Good Local"}


def test_price_scale_id_defaults_to_slug_of_name(monkeypatch, tmp_path):
    local_path = tmp_path / "indicators.json"
    local_path.write_text(json.dumps([_spec("Fund Flows Total")]), encoding="utf-8")
    monkeypatch.setenv(ci.INDICATORS_PATH_ENV, str(local_path))
    assert ci.load_custom_indicators()["Fund Flows Total"].price_scale_id == "fund-flows-total"


# ── Catalog wiring ──────────────────────────────────────────────────────────


def test_build_indicator_entries_uses_per_spec_groups(monkeypatch, tmp_path):
    from TerraFin.interface.infra.ticker_search.routes import _build_indicator_entries

    local_path = tmp_path / "indicators.json"
    local_path.write_text(json.dumps([_spec("Fund Flows", group="Flows")]), encoding="utf-8")
    monkeypatch.setenv(ci.INDICATORS_PATH_ENV, str(local_path))

    by_symbol = {entry["symbol"]: entry for entry in _build_indicator_entries()}
    assert by_symbol["News Sentiment"]["group"] == "Sentiment"
    assert by_symbol["Sentiment Entropy"]["group"] == "Sentiment"
    assert by_symbol["Fund Flows"] == {
        "symbol": "Fund Flows",
        "name": "Fund Flows description",
        "group": "Flows",
    }


# ── Spec validation: band keys ──────────────────────────────────────────────


def test_band_fields_keys_must_be_pos_neu_neg(monkeypatch, tmp_path):
    # The band pipeline (backend resample + frontend stacking) is keyed to
    # exactly pos/neu/neg; any other keys must reject at parse time so a bad
    # user spec degrades to a skipped spec instead of a broken chart.
    local_path = tmp_path / "indicators.json"
    band_source = {
        "kind": "mongo",
        "database": "market_data",
        "collection": "flows",
        "time_field": "as_of_date",
        "fields": {"inflow": "in_share", "outflow": "out_share"},
    }
    local_path.write_text(
        json.dumps([{"name": "Bad Band", "series_type": "band", "source": band_source}]),
        encoding="utf-8",
    )
    monkeypatch.setenv(ci.INDICATORS_PATH_ENV, str(local_path))
    assert "Bad Band" not in ci.load_custom_indicators()


# ── ownScale layout contract ────────────────────────────────────────────────


def test_own_scale_band_does_not_suppress_layout_for_other_series(monkeypatch):
    # Two plain lines + the ownScale band: the lines still get their left/right
    # layout scales; the band's own scale is never reassigned.
    from TerraFin.interface.pages.chart.formatters import build_multi_payload_from_items
    from TerraFin.interface.pages.chart.routes import _payload_needs_layout

    _install_fake_mongo(monkeypatch)
    band = ci.build_custom_indicator(ci.load_custom_indicators()["News Sentiment"])
    lines = [
        {"id": "AAPL", "seriesType": "line", "data": [{"time": "2026-06-01", "value": 1.0}]},
        {"id": "MSFT", "seriesType": "line", "data": [{"time": "2026-06-01", "value": 2.0}]},
    ]
    payload = {"mode": "multi", "series": lines + [band]}
    assert _payload_needs_layout(payload) is True

    laid_out = build_multi_payload_from_items(payload["series"])
    by_id = {item["id"]: item for item in laid_out["series"]}
    assert by_id["AAPL"]["priceScaleId"] == "left"
    assert by_id["MSFT"]["priceScaleId"] == "right"
    assert by_id["News Sentiment"]["priceScaleId"] == "news-sentiment"


def test_custom_line_indicator_gets_overlay_scale_beside_price(monkeypatch):
    # A custom sentiment LINE beside a price candlestick lands on a hidden
    # overlay scale (recognized via _is_line_only), not the visible left axis.
    from TerraFin.interface.pages.chart.formatters import build_multi_payload_from_items

    _install_fake_mongo(monkeypatch)
    entropy = ci.build_custom_indicator(ci.load_custom_indicators()["Sentiment Entropy"])
    price = {
        "id": "SPY",
        "seriesType": "candlestick",
        "data": [{"time": "2026-06-01", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}],
    }
    by_id = {i["id"]: i for i in build_multi_payload_from_items([price, entropy])["series"]}
    assert by_id["SPY"]["priceScaleId"] == "right"
    assert by_id["Sentiment Entropy"]["priceScaleId"].startswith("overlay-")
    assert "ownScale" not in by_id["Sentiment Entropy"]


def test_payload_of_only_the_band_needs_no_layout(monkeypatch):
    _install_fake_mongo(monkeypatch)
    band = ci.build_custom_indicator(ci.load_custom_indicators()["News Sentiment"])
    from TerraFin.interface.pages.chart.routes import _payload_needs_layout

    assert _payload_needs_layout({"mode": "multi", "series": [band]}) is False


def test_own_scale_survives_apply_view_resample(monkeypatch):
    from TerraFin.interface.pages.chart.chart_view import apply_view

    _install_fake_mongo(monkeypatch)
    specs = ci.load_custom_indicators()
    series = [ci.build_custom_indicator(specs[name]) for name in ("News Sentiment", "Sentiment Entropy")]
    out = apply_view({"mode": "multi", "series": series}, "weekly")
    by_id = {item["id"]: item for item in out["series"]}
    assert by_id["News Sentiment"]["ownScale"] is True
    assert "ownScale" not in by_id["Sentiment Entropy"]
    assert {item["seriesType"] for item in out["series"]} == {"band", "line"}


# ── HTTP-level: add/remove dispatch + case handling ─────────────────────────


def test_api_add_remove_custom_indicator_and_case_variants(monkeypatch):
    from fastapi.testclient import TestClient

    from TerraFin.interface.server import create_app

    _install_fake_mongo(monkeypatch)
    client = TestClient(create_app())

    # Add via canonical name -> band item lands in the payload with ownScale.
    r = client.post("/chart/api/chart-series/add", json={"name": "News Sentiment"})
    assert r.status_code == 200 and r.json()["ok"] is True

    # Case-variant re-add is caught as a duplicate (remap runs BEFORE dup check).
    r = client.post("/chart/api/chart-series/add", json={"name": "news sentiment"})
    assert r.json() == {**r.json(), "ok": False, "error": "Already added"}

    # Case-variant add of the OTHER spec works (lands under the canonical name).
    r = client.post("/chart/api/chart-series/add", json={"name": "sentiment entropy"})
    assert r.json()["ok"] is True
    names = client.get("/chart/api/chart-series/names").json()["entries"]
    assert {e["name"] for e in names} == {"News Sentiment", "Sentiment Entropy"}

    # Payload: the band keeps its own scale; the lone line takes the main axis.
    payload = client.get("/chart/api/chart-data").json()
    by_id = {s["id"]: s for s in payload["series"]}
    assert by_id["News Sentiment"]["priceScaleId"] == "news-sentiment"
    assert by_id["Sentiment Entropy"]["priceScaleId"] == "right"
    # description survives the add→rebuild→payload path (feeds the legend info button).
    assert by_id["News Sentiment"]["description"] == "News sentiment band."

    # Case-variant remove resolves to the canonical name.
    client.post("/chart/api/chart-series/remove", json={"name": "sentiment entropy"})
    names = client.get("/chart/api/chart-series/names").json()["entries"]
    assert {e["name"] for e in names} == {"News Sentiment"}
