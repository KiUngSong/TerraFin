"""Market Voices: contract validation + read-path shaping + API surface."""

from datetime import date, timedelta

import pytest

from TerraFin.data.contracts.voices import MarketView
from TerraFin.data.providers.corporate.market_voices import (
    HISTORY_MAX,
    STALE_AFTER_DAYS,
    MarketVoicesResponse,
    shape_market_voices,
)


def _today() -> str:
    return date.today().isoformat()


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _doc(slug="mike_wilson", **over) -> dict:
    base = {
        "slug": slug,
        "name": "Mike Wilson (Morgan Stanley)",
        "as_of": _today(),
        "stance": "bullish",
        "thesis": "New expansion broadens the trade.",
        "source_url": "https://example.com/x",
        "ingested_at": f"{_today()}T00:00:00Z",
    }
    base.update(over)
    return base


# ── contract ──────────────────────────────────────────────────────────────────

def test_contract_minimal_and_normalizing() -> None:
    v = MarketView(slug=" Mike_Wilson ", name="Mike Wilson", as_of=_today(), stance=" Bullish ", thesis="t")
    assert v.slug == "mike_wilson" and v.stance == "bullish" and v.source_url == ""
    assert set(v.to_doc()) == {"slug", "name", "as_of", "stance", "thesis", "source_url", "ingested_at"}


@pytest.mark.parametrize("bad", [
    dict(slug=""),
    dict(name=""),
    dict(thesis=""),
    dict(thesis="x" * 2001),
    dict(stance="unknown"),           # no unknown: no directional read -> no doc
    dict(as_of="2026-99-99"),
    dict(as_of="2026-07-15T00:00:00"),  # datetime string is not the contract
    dict(as_of=(date.today() + timedelta(days=3)).isoformat()),  # future
    dict(source_url="javascript:alert(1)"),
])
def test_contract_rejects(bad) -> None:
    fields = dict(slug="s", name="N", as_of=_today(), stance="bullish", thesis="t")
    fields.update(bad)
    with pytest.raises(ValueError):
        MarketView(**fields)


def test_contract_allows_one_day_future_slack() -> None:
    # A producer a timezone ahead of UTC may stamp "tomorrow" — slack is
    # measured against the UTC date, so anchor the test there too.
    from datetime import datetime, timezone

    tomorrow_utc = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    v = MarketView(slug="s", name="N", as_of=tomorrow_utc, stance="neutral", thesis="t")
    assert v.as_of == tomorrow_utc


# ── shaping: gate ─────────────────────────────────────────────────────────────

def test_shape_drops_junk_and_normalizes() -> None:
    shaped = shape_market_voices([
        _doc(),
        {"slug": "test", "thesis": "junk"},                      # no name/stance
        _doc(slug="Ed_Yardeni", stance=" Bullish ", name="Ed"),   # cased -> normalized
        _doc(slug="future", as_of="2099-01-01"),                  # future-dated
        _doc(slug="badurl", source_url="javascript:x"),           # url dropped, doc kept
    ])
    slugs = {v["slug"] for v in shaped["views"]}
    assert slugs == {"mike_wilson", "ed_yardeni", "badurl"}
    ed = next(v for v in shaped["views"] if v["slug"] == "ed_yardeni")
    assert ed["stance"] == "bullish"
    assert next(v for v in shaped["views"] if v["slug"] == "badurl")["source_url"] == ""


def test_shape_empty_and_non_list() -> None:
    for raw in ([], None, "garbage", {"views": []}):
        shaped = shape_market_voices(raw)
        assert shaped["views"] == [] and shaped["summary"]["reporting"] == 0


# ── shaping: latest wins ──────────────────────────────────────────────────────

def test_latest_by_as_of_then_ingested_at() -> None:
    shaped = shape_market_voices([
        _doc(as_of=_days_ago(5), thesis="old"),
        _doc(as_of=_days_ago(1), thesis="new"),
        # correction: same as_of, later ingested_at wins
        _doc(as_of=_days_ago(1), thesis="corrected", ingested_at=f"{_today()}T09:00:00Z"),
    ])
    assert len(shaped["views"]) == 1
    assert shaped["views"][0]["thesis"] == "corrected"


def test_history_capped_and_ordered() -> None:
    docs = [_doc(as_of=_days_ago(n), thesis=f"t{n}") for n in range(12)]
    shaped = shape_market_voices(docs)
    hist = shaped["history"]["mike_wilson"]
    assert len(hist) == HISTORY_MAX
    assert hist[0]["as_of"] < hist[-1]["as_of"]  # oldest -> newest
    assert hist[-1]["thesis"] == "t0"


# ── shaping: tally window ─────────────────────────────────────────────────────

def test_old_view_shows_but_does_not_vote() -> None:
    shaped = shape_market_voices([
        _doc(slug="fresh", stance="bullish"),
        _doc(slug="ancient", stance="bearish", as_of=_days_ago(STALE_AFTER_DAYS + 30)),
    ])
    assert {v["slug"] for v in shaped["views"]} == {"fresh", "ancient"}  # card stays
    s = shaped["summary"]
    assert s["bull"] == 1 and s["bear"] == 0 and s["stale"] == 1 and s["reporting"] == 2


def test_response_model_validates_shape() -> None:
    shaped = shape_market_voices([_doc()])
    r = MarketVoicesResponse.model_validate({"views": shaped["views"], "summary": shaped["summary"]})
    assert r.views[0].age_days == 0 and r.summary.reporting == 1
