"""Tests for the fresh-price universe loader behind the relative-strength factor."""

from TerraFin.analytics.factors import universe_prices


def test_fetch_closes_uppercases_and_drops_blanks(monkeypatch) -> None:
    monkeypatch.setattr(universe_prices, "_fetch_closes_one", lambda t: (t, [1.0, 2.0], False))

    closes = universe_prices.fetch_closes(["nvda", "  ", "amd"], use_memo=False)

    assert set(closes) == {"NVDA", "AMD"}


def test_fetch_closes_skips_symbols_that_fail(monkeypatch) -> None:
    """One delisted or renamed member must not void a whole universe ranking."""

    def flaky(ticker: str):
        if ticker == "BAD":
            raise ValueError("no data")
        return ticker, [1.0, 2.0, 3.0], False

    monkeypatch.setattr(universe_prices, "_fetch_closes_one", flaky)

    closes = universe_prices.fetch_closes(["good", "bad"], use_memo=False)

    assert set(closes) == {"GOOD"}


def test_fetch_closes_returns_empty_for_no_symbols() -> None:
    assert universe_prices.fetch_closes([], use_memo=False) == {}


def test_memo_serves_a_repeat_request(monkeypatch) -> None:
    calls: list[str] = []

    def counting(ticker: str):
        calls.append(ticker)
        return ticker, [1.0, 2.0], False

    monkeypatch.setattr(universe_prices, "_fetch_closes_one", counting)
    monkeypatch.setattr(universe_prices, "_memo", {})

    first = universe_prices.fetch_closes(["AAA"])
    second = universe_prices.fetch_closes(["AAA"])

    assert first == second
    assert calls == ["AAA"], "second call must be served from the memo"


def test_memo_expires(monkeypatch) -> None:
    calls: list[str] = []

    def counting(ticker: str):
        calls.append(ticker)
        return ticker, [1.0, 2.0], False

    monkeypatch.setattr(universe_prices, "_fetch_closes_one", counting)
    monkeypatch.setattr(universe_prices, "_memo", {})

    universe_prices.fetch_closes(["AAA"])

    # Age the stored entry past the TTL rather than patching the clock, which
    # would replace `time.monotonic` for everything running in-process.
    key = ("AAA",)
    stored_at, payload = universe_prices._memo[key]
    universe_prices._memo[key] = (stored_at - universe_prices._MEMO_TTL_SECONDS - 1.0, payload)

    universe_prices.fetch_closes(["AAA"])

    assert calls == ["AAA", "AAA"], "an expired memo entry must be refetched"


def test_universe_symbols_watchlist_passes_the_service(monkeypatch) -> None:
    """Regression: `SimilarityPool.from_watchlist` requires the service instance.

    Calling it without one raised TypeError for every `universe="watchlist"`
    request — the universe both LLM-facing surfaces recommend as the cheapest.
    """

    import TerraFin.data.watchlist_service as watchlist_module

    class _Svc:
        def get_watchlist_snapshot(self, group=None):
            return [{"symbol": "NVDA", "tags": []}, {"symbol": "TSLA", "tags": []}]

    monkeypatch.setattr(watchlist_module, "get_watchlist_service", lambda: _Svc())

    assert universe_prices.universe_symbols("watchlist") == ["NVDA", "TSLA"]


def test_universe_symbols_reads_a_bundled_universe() -> None:
    symbols = universe_prices.universe_symbols("nasdaq100")

    assert len(symbols) > 50
    assert all(symbol == symbol.strip() for symbol in symbols)


def test_stale_artifacts_are_reported(monkeypatch) -> None:
    monkeypatch.setattr(
        universe_prices,
        "_fetch_closes_one",
        lambda t: (t, [1.0, 2.0], t == "STALEONE"),
    )

    closes, stale = universe_prices.fetch_closes_detailed(["fresh", "staleone"], use_memo=False)

    assert set(closes) == {"FRESH", "STALEONE"}
    assert stale == ["STALEONE"]
