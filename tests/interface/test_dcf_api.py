from fastapi.testclient import TestClient

import TerraFin.interface.market_insights.data_routes as market_insights_routes
import TerraFin.interface.stock.data_routes as stock_routes
from TerraFin.analytics.analysis.risk.models import BetaEstimate
from TerraFin.interface.private_data_service import reset_private_data_service
from TerraFin.interface.server import create_app
from TerraFin.interface.watchlist_service import reset_watchlist_service


def _client() -> TestClient:
    reset_watchlist_service()
    reset_private_data_service()
    return TestClient(create_app())


def _ready_payload(symbol: str, entity_type: str) -> dict:
    return {
        "status": "ready",
        "entityType": entity_type,
        "symbol": symbol,
        "asOf": "2026-04-05",
        "currentPrice": 100.0,
        "currentIntrinsicValue": 112.0,
        "upsidePct": 12.0,
        "scenarios": {
            "base": {
                "key": "base",
                "label": "Base",
                "status": "ready",
                "growthShiftPct": 0.0,
                "discountRateShiftBps": 0,
                "terminalGrowthShiftBps": 0,
                "intrinsicValue": 112.0,
                "upsidePct": 12.0,
                "terminalValue": 80.0,
                "terminalGrowthPct": 3.0,
                "terminalDiscountRatePct": 9.0,
                "projectedCashFlows": [],
            }
        },
        "assumptions": {"baseGrowthPct": 6.0},
        "sensitivity": {
            "discountRateShiftBps": [-100, 0, 100],
            "terminalGrowthShiftBps": [-100, 0, 100],
            "cells": [],
        },
        "rateCurve": {
            "source": "test",
            "asOf": "2026-04-05",
            "fitRmse": 0.01,
            "fallbackUsed": False,
            "points": [],
            "fittedPoints": [],
        },
        "dataQuality": {"mode": "live", "sources": ["test"]},
        "warnings": [],
        "methods": None,
    }


def test_market_insights_sp500_dcf_endpoint_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        market_insights_routes,
        "build_sp500_dcf_payload",
        lambda *args, **kwargs: {
            **_ready_payload("S&P 500", "index"),
            "methods": [
                {
                    "key": "shareholder_yield",
                    "label": "Shareholder Yield",
                    "description": "Case A",
                    "weight": 0.5,
                    "currentIntrinsicValue": 105.0,
                    "upsidePct": 5.0,
                },
                {
                    "key": "earnings_power",
                    "label": "Earnings Power",
                    "description": "Case B",
                    "weight": 0.5,
                    "currentIntrinsicValue": 119.0,
                    "upsidePct": 19.0,
                },
            ],
        },
    )
    client = _client()

    response = client.get("/market-insights/api/dcf/sp500")
    assert response.status_code == 200
    body = response.json()
    assert body["entityType"] == "index"
    assert body["symbol"] == "S&P 500"
    assert body["currentIntrinsicValue"] == 112.0
    assert len(body["methods"]) == 2


def test_market_insights_sp500_dcf_post_accepts_overrides(monkeypatch) -> None:
    captured = {}

    def _build(*args, **kwargs):
        captured["overrides"] = kwargs.get("overrides")
        return _ready_payload("S&P 500", "index")

    monkeypatch.setattr(market_insights_routes, "build_sp500_dcf_payload", _build)
    client = _client()

    response = client.post(
        "/market-insights/api/dcf/sp500",
        json={
            "baseYearEps": 240.0,
            "terminalGrowthPct": 3.8,
            "terminalEquityRiskPremiumPct": 4.4,
            "terminalRoePct": 19.5,
            "yearlyAssumptions": [
                {
                    "yearOffset": 1,
                    "growthPct": 12.0,
                    "payoutRatioPct": 30.0,
                    "buybackRatioPct": 45.0,
                    "equityRiskPremiumPct": 5.5,
                }
            ],
        },
    )
    assert response.status_code == 200
    assert captured["overrides"].base_year_eps == 240.0
    assert captured["overrides"].terminal_growth_pct == 3.8
    assert len(captured["overrides"].yearly_assumptions) == 1


def test_stock_dcf_endpoint_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        stock_routes,
        "build_stock_dcf_payload",
        lambda ticker, *args, **kwargs: _ready_payload(ticker.upper(), "stock"),
    )
    client = _client()

    response = client.get("/stock/api/dcf?ticker=aapl")
    assert response.status_code == 200
    body = response.json()
    assert body["entityType"] == "stock"
    assert body["symbol"] == "AAPL"
    assert "base" in body["scenarios"]


def test_stock_dcf_endpoint_allows_insufficient_data(monkeypatch) -> None:
    monkeypatch.setattr(
        stock_routes,
        "build_stock_dcf_payload",
        lambda ticker, *args, **kwargs: {
            **_ready_payload(ticker.upper(), "stock"),
            "status": "insufficient_data",
            "currentIntrinsicValue": None,
            "upsidePct": None,
            "scenarios": {},
            "warnings": ["Free cash flow per share is not positive."],
        },
    )
    client = _client()

    response = client.get("/stock/api/dcf?ticker=loss")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_data"
    assert body["warnings"] == ["Free cash flow per share is not positive."]


def test_stock_beta_estimate_endpoint_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        stock_routes,
        "estimate_beta_5y_monthly",
        lambda ticker: BetaEstimate(
            symbol=ticker.upper(),
            benchmark_symbol="^SPX",
            benchmark_label="S&P 500",
            method_id="beta_5y_monthly",
            lookback_years=5,
            frequency="monthly",
            beta=1.11,
            observations=60,
            r_squared=0.42,
            status="ready",
            warnings=[],
        ),
    )
    monkeypatch.setattr(
        stock_routes,
        "estimate_beta_5y_monthly_adjusted",
        lambda ticker: BetaEstimate(
            symbol=ticker.upper(),
            benchmark_symbol="^SPX",
            benchmark_label="S&P 500",
            method_id="beta_5y_monthly_adjusted",
            lookback_years=5,
            frequency="monthly",
            beta=1.07,
            observations=60,
            r_squared=0.42,
            status="ready",
            warnings=[],
        ),
    )
    client = _client()

    response = client.get("/stock/api/beta-estimate?ticker=googl")
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "GOOGL"
    assert body["benchmarkSymbol"] == "^SPX"
    assert body["methodId"] == "beta_5y_monthly"
    assert body["adjustedMethodId"] == "beta_5y_monthly_adjusted"
    assert body["beta"] == 1.11
    assert body["adjustedBeta"] == 1.07
    assert body["observations"] == 60
    assert body["rSquared"] == 0.42


def test_stock_dcf_post_accepts_overrides(monkeypatch) -> None:
    captured = {}

    def _build(ticker, *args, **kwargs):
        captured["ticker"] = ticker
        captured["overrides"] = kwargs.get("overrides")
        return _ready_payload(ticker.upper(), "stock")

    monkeypatch.setattr(stock_routes, "build_stock_dcf_payload", _build)
    client = _client()

    response = client.post(
        "/stock/api/dcf?ticker=nvda",
        json={
            "baseCashFlowPerShare": 4.2,
            "baseGrowthPct": 18.0,
            "terminalGrowthPct": 3.4,
            "beta": 1.3,
            "equityRiskPremiumPct": 4.9,
            "fcfBaseSource": "ttm",
        },
    )
    assert response.status_code == 200
    assert captured["ticker"] == "nvda"
    assert captured["overrides"].base_cash_flow_per_share == 4.2
    assert captured["overrides"].beta == 1.3
    assert captured["overrides"].fcf_base_source == "ttm"


def test_fcf_history_endpoint_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        stock_routes,
        "build_fcf_history_payload",
        lambda ticker, **kwargs: {
            "ticker": ticker.upper(),
            "sharesOutstanding": 100.0,
            "ttmFcfPerShare": 0.85,
            "ttmSource": "quarterly_ttm",
            "candidates": {
                "threeYearAvg": 0.43,
                "latestAnnual": -0.50,
                "ttm": 0.85,
            },
            "autoSelectedSource": "3yr_avg",
            "sharesNote": "Per-year FCF/share is computed using current sharesOutstanding.",
            "history": [
                {"year": "2022", "fcf": 80.0, "fcfPerShare": 0.80},
                {"year": "2023", "fcf": 100.0, "fcfPerShare": 1.00},
                {"year": "2024", "fcf": -50.0, "fcfPerShare": -0.50},
            ],
        },
    )
    client = _client()
    response = client.get("/stock/api/fcf-history?ticker=moh&years=5")
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "MOH"
    assert body["ttmFcfPerShare"] == 0.85
    assert body["candidates"]["threeYearAvg"] == 0.43
    assert body["candidates"]["latestAnnual"] == -0.50
    assert body["candidates"]["ttm"] == 0.85
    assert body["autoSelectedSource"] == "3yr_avg"
    assert len(body["history"]) == 3
    assert body["history"][2]["year"] == "2024"
    assert body["history"][2]["fcfPerShare"] == -0.50


def test_stock_dcf_post_accepts_turnaround_and_horizon(monkeypatch) -> None:
    captured = {}

    def _build(ticker, *args, **kwargs):
        captured["ticker"] = ticker
        captured["overrides"] = kwargs.get("overrides")
        captured["projection_years"] = kwargs.get("projection_years")
        return _ready_payload(ticker.upper(), "stock")

    monkeypatch.setattr(stock_routes, "build_stock_dcf_payload", _build)
    client = _client()

    response = client.post(
        "/stock/api/dcf?ticker=moh",
        json={
            "projectionYears": 10,
            "breakevenYear": 3,
            "breakevenCashFlowPerShare": 2.5,
            "postBreakevenGrowthPct": 12.0,
        },
    )
    assert response.status_code == 200
    assert captured["ticker"] == "moh"
    assert captured["projection_years"] == 10
    assert captured["overrides"].breakeven_year == 3
    assert captured["overrides"].breakeven_cash_flow_per_share == 2.5
    assert captured["overrides"].post_breakeven_growth_pct == 12.0
