import pandas as pd
from fastapi.testclient import TestClient

import TerraFin.interface.chart.routes as chart_routes
from TerraFin.data import DataFactory
from TerraFin.data.contracts import HistoryChunk
from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame
from TerraFin.interface.chart.chart_view import apply_view
from TerraFin.interface.chart.formatters import build_multi_payload as _build_multi_payload
from TerraFin.interface.chart.formatters import build_source_payload as _build_source_payload
from TerraFin.interface.chart.formatters import format_dataframe
from TerraFin.interface.private_data_service import reset_private_data_service
from TerraFin.interface.server import create_app


def test_apply_view_returns_line_payload_for_invalid_or_empty_source() -> None:
    assert apply_view({}, "daily") == {"mode": "multi", "series": [], "dataLength": 0}
    assert apply_view({"mode": "multi", "series": "bad"}, "weekly") == {"mode": "multi", "series": [], "dataLength": 0}


def test_apply_view_keeps_daily_points_for_line_data() -> None:
    payload = {
        "mode": "multi",
        "series": [
            {
                "id": "S1",
                "seriesType": "line",
                "data": [
                    {"time": "2026-01-01", "value": 10.0},
                    {"time": "2026-01-02", "value": 11.0},
                    {"time": "2026-01-03", "value": 12.5},
                ],
            }
        ],
    }
    out = apply_view(payload, "daily")
    assert out["mode"] == "multi"
    assert len(out["series"]) == 1
    assert len(out["series"][0]["data"]) == 3
    assert out["series"][0]["data"][0]["time"] == "2026-01-01"
    assert out["series"][0]["data"][-1]["value"] == 12.5


def test_apply_view_resamples_weekly_monthly_yearly_for_line_data() -> None:
    payload = {
        "mode": "multi",
        "series": [
            {
                "id": "S1",
                "seriesType": "line",
                "data": [
                    {"time": "2026-01-01", "value": 10.0},
                    {"time": "2026-01-07", "value": 12.0},
                    {"time": "2026-01-15", "value": 14.0},
                    {"time": "2026-02-03", "value": 20.0},
                ],
            }
        ],
    }

    weekly = apply_view(payload, "weekly")
    monthly = apply_view(payload, "monthly")
    yearly = apply_view(payload, "yearly")

    assert weekly["mode"] == "multi"
    assert len(weekly["series"][0]["data"]) >= 3

    assert len(monthly["series"][0]["data"]) == 2
    assert monthly["series"][0]["data"][0]["value"] == 14.0
    assert monthly["series"][0]["data"][1]["value"] == 20.0

    assert len(yearly["series"][0]["data"]) == 1
    assert yearly["series"][0]["data"][0]["value"] == 20.0


def test_format_dataframe_contract_for_line_and_ohlc_source() -> None:
    line_df = pd.DataFrame({"time": ["2026-01-01", "2026-01-02"], "close": [100.0, 101.0]})
    ohlc_df = pd.DataFrame(
        {
            "time": ["2026-01-01", "2026-01-02"],
            "open": [99.5, 100.5],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.0, 101.0],
        }
    )

    line_payload = format_dataframe(line_df)
    assert line_payload["mode"] == "multi"
    assert line_payload["series"][0]["seriesType"] == "line"
    assert line_payload["series"][0]["data"][0] == {"time": "2026-01-01", "value": 100.0}

    ohlc_payload = format_dataframe(ohlc_df)
    assert ohlc_payload["mode"] == "multi"
    assert ohlc_payload["series"][0]["seriesType"] == "candlestick"
    assert ohlc_payload["series"][0]["data"][0]["open"] == 99.5
    assert ohlc_payload["series"][0]["data"][0]["close"] == 100.0

    assert format_dataframe(pd.DataFrame()) == {"mode": "multi", "series": [], "dataLength": 0}
    assert format_dataframe(pd.DataFrame({"time": ["2026-01-01"]})) == {"mode": "multi", "series": [], "dataLength": 0}


def test_format_dataframe_includes_zone_metadata_for_vol_regime() -> None:
    df = TimeSeriesDataFrame(
        pd.DataFrame(
            {
                "time": ["2026-01-01", "2026-01-02", "2026-01-03"],
                "close": [12.0, 42.0, 88.0],
            }
        )
    )
    df.name = "Vol Regime"
    df.chart_meta = {
        "zones": [
            {"from": 0, "to": 20, "color": "rgba(76,175,80,0.15)"},
            {"from": 80, "to": 100, "color": "rgba(244,67,54,0.15)"},
        ]
    }

    payload = format_dataframe(df)

    assert payload["series"][0]["zones"] == [
        {"from": 0.0, "to": 20.0, "color": "rgba(76,175,80,0.15)"},
        {"from": 80.0, "to": 100.0, "color": "rgba(244,67,54,0.15)"},
    ]


def test_apply_view_preserves_zone_metadata_for_line_series() -> None:
    payload = {
        "mode": "multi",
        "series": [
            {
                "id": "Vol Regime",
                "seriesType": "line",
                "data": [
                    {"time": "2026-01-01", "value": 10.0},
                    {"time": "2026-01-07", "value": 12.0},
                    {"time": "2026-01-15", "value": 14.0},
                    {"time": "2026-02-03", "value": 20.0},
                ],
                "zones": [
                    {"from": 0, "to": 20, "color": "rgba(76,175,80,0.15)"},
                    {"from": 80, "to": 100, "color": "rgba(244,67,54,0.15)"},
                ],
            }
        ],
    }

    monthly = apply_view(payload, "monthly")

    assert monthly["series"][0]["zones"] == payload["series"][0]["zones"]


def test_chart_view_endpoint_contract_and_transform() -> None:
    reset_private_data_service()
    client = TestClient(create_app())
    headers = {"X-Session-ID": "chart-transform-contract"}
    source = {
        "mode": "multi",
        "series": [
            {
                "id": "S&P 500",
                "seriesType": "line",
                "data": [
                    {"time": "2026-01-01", "value": 10.5},
                    {"time": "2026-01-11", "value": 11.8},
                    {"time": "2026-02-05", "value": 12.4},
                ],
            }
        ],
    }

    write_response = client.post("/chart/api/chart-data", json=source, headers=headers)
    assert write_response.status_code == 200
    assert write_response.json()["ok"] is True

    view_response = client.post("/chart/api/chart-view", json={"view": "monthly"}, headers=headers)
    assert view_response.status_code == 200
    payload = view_response.json()
    assert payload["ok"] is True
    assert payload["view"] == "monthly"
    assert payload["dataLength"] >= 1
    assert isinstance(payload["entries"], list)

    chart_payload = client.get("/chart/api/chart-data", headers=headers).json()
    assert chart_payload["mode"] == "multi"
    assert chart_payload["dataLength"] >= 1
    assert isinstance(chart_payload["entries"], list)
    assert chart_payload["historyBySeries"]["S&P 500"]["isComplete"] is True
    assert chart_payload["historyBySeries"]["S&P 500"]["hasOlder"] is False


def test_chart_view_endpoint_keeps_candlestick_series_when_valid() -> None:
    reset_private_data_service()
    client = TestClient(create_app())
    headers = {"X-Session-ID": "chart-candle-contract"}
    source = {
        "mode": "multi",
        "series": [
            {
                "id": "OHLC",
                "seriesType": "candlestick",
                "data": [
                    {"time": "2026-01-01", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.4},
                    {"time": "2026-01-10", "open": 10.4, "high": 12.0, "low": 10.1, "close": 11.7},
                    {"time": "2026-02-03", "open": 11.7, "high": 12.9, "low": 11.5, "close": 12.5},
                ],
            }
        ],
    }

    write_response = client.post("/chart/api/chart-data", json=source, headers=headers)
    assert write_response.status_code == 200

    view_response = client.post("/chart/api/chart-view", json={"view": "monthly"}, headers=headers)
    assert view_response.status_code == 200

    chart_payload = client.get("/chart/api/chart-data", headers=headers).json()
    assert chart_payload["series"][0]["seriesType"] == "candlestick"
    assert "open" in chart_payload["series"][0]["data"][0]


def test_chart_mfd_defaults_to_single_medium_horizon_series() -> None:
    dates = pd.date_range("2025-01-01", periods=320, freq="D")
    candle_data = [
        {
            "time": dt.strftime("%Y-%m-%d"),
            "open": 100.0 + idx * 0.3,
            "high": 100.5 + idx * 0.3,
            "low": 99.5 + idx * 0.3,
            "close": 100.2 + idx * 0.3,
        }
        for idx, dt in enumerate(dates)
    ]

    overlays = chart_routes.compute_mandelbrot_fractal_dimension(candle_data)

    assert [overlay["id"] for overlay in overlays] == ["MFD 130"]
    assert overlays[0]["priceScaleId"] == "mfd"
    assert overlays[0]["indicatorGroup"] == "mfd"
    assert overlays[0]["priceLevels"] == [
        {"price": 1.0, "color": "#9e9e9e", "title": "Smooth"},
        {"price": 1.5, "color": "#bdbdbd", "title": "Random"},
        {"price": 2.0, "color": "#90a4ae", "title": "Choppy"},
    ]


def test_chart_view_reuses_cached_indicators_for_same_transformed_source(monkeypatch) -> None:
    counts = {
        "ma": 0,
        "bb": 0,
        "rsi": 0,
        "macd": 0,
        "realized_vol": 0,
        "range_vol": 0,
    }

    def _wrap(name: str, fn):
        def _inner(*args, **kwargs):
            counts[name] += 1
            return fn(*args, **kwargs)

        return _inner

    monkeypatch.setattr(chart_routes, "compute_moving_averages", _wrap("ma", chart_routes.compute_moving_averages))
    monkeypatch.setattr(chart_routes, "compute_bollinger_bands", _wrap("bb", chart_routes.compute_bollinger_bands))
    monkeypatch.setattr(chart_routes, "compute_rsi", _wrap("rsi", chart_routes.compute_rsi))
    monkeypatch.setattr(chart_routes, "compute_macd", _wrap("macd", chart_routes.compute_macd))
    monkeypatch.setattr(
        chart_routes,
        "compute_realized_volatility",
        _wrap("realized_vol", chart_routes.compute_realized_volatility),
    )
    monkeypatch.setattr(
        chart_routes,
        "compute_range_volatility",
        _wrap("range_vol", chart_routes.compute_range_volatility),
    )

    reset_private_data_service()
    client = TestClient(create_app())
    headers = {"X-Session-ID": "chart-indicator-cache"}
    dates = pd.date_range("2025-01-01", periods=90, freq="D")
    source = {
        "mode": "multi",
        "series": [
            {
                "id": "OHLC",
                "seriesType": "candlestick",
                "data": [
                    {
                        "time": dt.strftime("%Y-%m-%d"),
                        "open": 100.0 + idx,
                        "high": 101.0 + idx,
                        "low": 99.0 + idx,
                        "close": 100.5 + idx,
                    }
                    for idx, dt in enumerate(dates)
                ],
            }
        ],
    }

    write_response = client.post("/chart/api/chart-data", json=source, headers=headers)
    assert write_response.status_code == 200

    first_monthly = client.post("/chart/api/chart-view", json={"view": "monthly"}, headers=headers)
    assert first_monthly.status_code == 200
    counts_after_first_monthly = dict(counts)

    second_monthly = client.post("/chart/api/chart-view", json={"view": "monthly"}, headers=headers)
    assert second_monthly.status_code == 200
    assert counts == counts_after_first_monthly


def test_build_multi_payload_assigns_price_scale_id_for_one_ohlc_plus_lines() -> None:
    """1 OHLC + N lines: candlestick stays candlestick, gets right; lines get overlay-0, overlay-1, ..."""
    ohlc_df = pd.DataFrame(
        {
            "time": ["2026-01-01", "2026-01-02"],
            "open": [99.5, 100.5],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.0, 101.0],
        }
    )
    line_df1 = pd.DataFrame({"time": ["2026-01-01", "2026-01-02"], "close": [10.0, 11.0]})
    line_df2 = pd.DataFrame({"time": ["2026-01-01", "2026-01-02"], "close": [20.0, 21.0]})
    ohlc_ts = TimeSeriesDataFrame(ohlc_df)
    ohlc_ts.name = "OHLC"
    line_ts1 = TimeSeriesDataFrame(line_df1)
    line_ts1.name = "Line1"
    line_ts2 = TimeSeriesDataFrame(line_df2)
    line_ts2.name = "Line2"

    payload = _build_multi_payload([ohlc_ts, line_ts1, line_ts2])

    assert len(payload["series"]) == 3
    assert payload["series"][0]["seriesType"] == "candlestick"
    assert payload["series"][0]["priceScaleId"] == "right"
    assert payload["series"][1]["seriesType"] == "line"
    assert payload["series"][1]["priceScaleId"] == "overlay-0"
    assert payload["series"][2]["seriesType"] == "line"
    assert payload["series"][2]["priceScaleId"] == "overlay-1"


def test_build_multi_payload_assigns_separate_visible_scales_for_multi_line_series() -> None:
    line_df1 = pd.DataFrame({"time": ["2026-01-01", "2026-01-02"], "close": [18.0, 22.0]})
    line_df2 = pd.DataFrame({"time": ["2026-01-01", "2026-01-02"], "close": [105.0, 115.0]})
    line_df3 = pd.DataFrame({"time": ["2026-01-01", "2026-01-02"], "close": [3.0, 4.0]})

    line_ts1 = TimeSeriesDataFrame(line_df1)
    line_ts1.name = "VIX"
    line_ts2 = TimeSeriesDataFrame(line_df2)
    line_ts2.name = "MOVE"
    line_ts3 = TimeSeriesDataFrame(line_df3)
    line_ts3.name = "Spread"

    payload = _build_multi_payload([line_ts1, line_ts2, line_ts3])

    assert len(payload["series"]) == 3
    assert payload["series"][0]["seriesType"] == "line"
    assert payload["series"][0]["priceScaleId"] == "left"
    assert payload["series"][1]["seriesType"] == "line"
    assert payload["series"][1]["priceScaleId"] == "right"
    assert payload["series"][2]["seriesType"] == "line"
    assert payload["series"][2]["priceScaleId"] == "overlay-0"


def test_build_source_payload_preserves_raw_candlesticks() -> None:
    ohlc_df1 = pd.DataFrame(
        {
            "time": ["2026-01-01", "2026-01-02"],
            "open": [99.5, 100.5],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.0, 101.0],
        }
    )
    ohlc_df2 = pd.DataFrame(
        {
            "time": ["2026-01-01", "2026-01-02"],
            "open": [199.5, 200.5],
            "high": [201.0, 202.0],
            "low": [199.0, 200.0],
            "close": [200.0, 201.0],
        }
    )
    line_df = pd.DataFrame({"time": ["2026-01-01", "2026-01-02"], "close": [10.0, 11.0]})
    ohlc_ts1 = TimeSeriesDataFrame(ohlc_df1)
    ohlc_ts1.name = "OHLC1"
    ohlc_ts2 = TimeSeriesDataFrame(ohlc_df2)
    ohlc_ts2.name = "OHLC2"
    line_ts = TimeSeriesDataFrame(line_df)
    line_ts.name = "Line"

    payload = _build_source_payload([ohlc_ts1, ohlc_ts2, line_ts])

    assert payload["forcePercentage"] if "forcePercentage" in payload else False is False
    assert [series["seriesType"] for series in payload["series"]] == ["candlestick", "candlestick", "line"]


def test_progressive_seed_and_backfill_chart_series_contract(monkeypatch) -> None:
    zones = [
        {"from": 0.0, "to": 20.0, "color": "rgba(76,175,80,0.15)"},
        {"from": 80.0, "to": 100.0, "color": "rgba(244,67,54,0.15)"},
    ]

    def _recent_history(self, _name: str, *, period: str = "3y") -> HistoryChunk:
        frame = TimeSeriesDataFrame(
            pd.DataFrame(
                {
                    "time": ["2024-01-01", "2025-01-01", "2026-01-01"],
                    "close": [100.0, 120.0, 140.0],
                }
            ),
            chart_meta={"zones": zones},
        )
        return HistoryChunk(
            frame=frame,
            loaded_start="2024-01-01",
            loaded_end="2026-01-01",
            requested_period=period,
            is_complete=False,
            has_older=True,
            source_version="test",
        )

    def _backfill_history(self, _name: str, *, loaded_start: str | None = None) -> HistoryChunk:
        assert loaded_start == "2024-01-01"
        frame = TimeSeriesDataFrame(
            pd.DataFrame(
                {
                    "time": ["2021-01-01", "2022-01-01", "2023-01-01"],
                    "close": [70.0, 80.0, 90.0],
                }
            ),
            chart_meta={"zones": zones},
        )
        return HistoryChunk(
            frame=frame,
            loaded_start="2021-01-01",
            loaded_end="2026-01-01",
            requested_period=None,
            is_complete=True,
            has_older=False,
            source_version="test",
        )

    monkeypatch.setattr(DataFactory, "get_recent_history", _recent_history)
    monkeypatch.setattr(DataFactory, "get_full_history_backfill", _backfill_history)

    reset_private_data_service()
    client = TestClient(create_app())
    headers = {"X-Session-ID": "chart-progressive"}

    seed_response = client.post(
        "/chart/api/chart-series/progressive/set",
        json={"name": "AAPL", "pinned": True, "seedPeriod": "3y"},
        headers=headers,
    )
    assert seed_response.status_code == 200
    seed_payload = seed_response.json()
    assert seed_payload["ok"] is True
    assert seed_payload["entries"] == [{"name": "AAPL", "pinned": True}]
    assert seed_payload["historyBySeries"]["AAPL"]["loadedStart"] == "2024-01-01"
    assert seed_payload["historyBySeries"]["AAPL"]["hasOlder"] is True
    assert seed_payload["historyBySeries"]["AAPL"]["backfillInFlight"] is True
    assert seed_payload["series"][0]["zones"] == zones

    backfill_response = client.post(
        "/chart/api/chart-series/progressive/backfill",
        json={"name": "AAPL", "requestToken": seed_payload["requestToken"]},
        headers=headers,
    )
    assert backfill_response.status_code == 200
    backfill_payload = backfill_response.json()
    assert backfill_payload["ok"] is True
    assert backfill_payload["historyBySeries"]["AAPL"]["loadedStart"] == "2021-01-01"
    assert backfill_payload["historyBySeries"]["AAPL"]["isComplete"] is True
    assert backfill_payload["historyBySeries"]["AAPL"]["hasOlder"] is False
    assert backfill_payload["historyBySeries"]["AAPL"]["backfillInFlight"] is False
    assert any(series["id"] == "AAPL" for series in backfill_payload["mutation"]["upsertSeries"])
    assert backfill_payload["mutation"]["upsertSeries"][0]["zones"] == zones

    chart_payload = client.get("/chart/api/chart-data", headers=headers).json()
    assert chart_payload["entries"] == [{"name": "AAPL", "pinned": True}]
    assert chart_payload["series"][0]["data"][0]["time"] == "2021-01-01"
    assert chart_payload["series"][0]["zones"] == zones


def test_progressive_backfill_ignores_stale_request_token(monkeypatch) -> None:
    def _recent_history(self, _name: str, *, period: str = "3y") -> HistoryChunk:
        frame = TimeSeriesDataFrame(pd.DataFrame({"time": ["2024-01-01", "2025-01-01"], "close": [100.0, 110.0]}))
        return HistoryChunk(
            frame=frame,
            loaded_start="2024-01-01",
            loaded_end="2025-01-01",
            requested_period=period,
            is_complete=False,
            has_older=True,
            source_version="test",
        )

    monkeypatch.setattr(DataFactory, "get_recent_history", _recent_history)
    monkeypatch.setattr(
        DataFactory,
        "get_full_history_backfill",
        lambda self, _name, *, loaded_start=None: (_ for _ in ()).throw(AssertionError("should not backfill stale")),
    )

    reset_private_data_service()
    client = TestClient(create_app())
    headers = {"X-Session-ID": "chart-progressive-stale"}

    seed_response = client.post(
        "/chart/api/chart-series/progressive/set",
        json={"name": "AAPL", "pinned": True, "seedPeriod": "3y"},
        headers=headers,
    )
    assert seed_response.status_code == 200

    stale_response = client.post(
        "/chart/api/chart-series/progressive/backfill",
        json={"name": "AAPL", "requestToken": "stale-token"},
        headers=headers,
    )
    assert stale_response.status_code == 200
    stale_payload = stale_response.json()
    assert stale_payload["ok"] is False
    assert stale_payload["stale"] is True

    chart_payload = client.get("/chart/api/chart-data", headers=headers).json()
    assert chart_payload["series"][0]["data"][0]["time"] == "2024-01-01"


def test_chart_data_preserves_price_scale_id_for_mixed_ohlc_and_lines() -> None:
    """POST mixed OHLC + lines with priceScaleId; GET and chart_view preserve priceScaleId."""
    reset_private_data_service()
    client = TestClient(create_app())
    headers = {"X-Session-ID": "chart-multiscale"}
    source = {
        "mode": "multi",
        "series": [
            {
                "id": "OHLC",
                "seriesType": "candlestick",
                "priceScaleId": "right",
                "data": [
                    {"time": "2026-01-01", "open": 5000, "high": 5010, "low": 4990, "close": 5005},
                    {"time": "2026-01-02", "open": 5005, "high": 5020, "low": 5000, "close": 5015},
                ],
            },
            {
                "id": "Line1",
                "seriesType": "line",
                "priceScaleId": "overlay-0",
                "data": [{"time": "2026-01-01", "value": 10}, {"time": "2026-01-02", "value": 20}],
            },
            {
                "id": "Line2",
                "seriesType": "line",
                "priceScaleId": "overlay-1",
                "data": [{"time": "2026-01-01", "value": 30}, {"time": "2026-01-02", "value": 40}],
            },
        ],
    }

    post_response = client.post("/chart/api/chart-data", json=source, headers=headers)
    assert post_response.status_code == 200

    get_payload = client.get("/chart/api/chart-data", headers=headers).json()
    assert get_payload["series"][0]["priceScaleId"] == "right"
    assert get_payload["series"][1]["priceScaleId"] == "overlay-0"
    assert get_payload["series"][2]["priceScaleId"] == "overlay-1"

    view_response = client.post("/chart/api/chart-view", json={"view": "daily"}, headers=headers)
    assert view_response.status_code == 200
    view_payload = client.get("/chart/api/chart-data", headers=headers).json()
    assert view_payload["series"][0]["priceScaleId"] == "right"
    assert view_payload["series"][1]["priceScaleId"] == "overlay-0"
    assert view_payload["series"][2]["priceScaleId"] == "overlay-1"
    assert view_payload["historyBySeries"]["OHLC"]["isComplete"] is True
    assert view_payload["historyBySeries"]["Line1"]["isComplete"] is True
    assert view_payload["historyBySeries"]["Line2"]["isComplete"] is True


def test_chart_data_remove_keeps_forced_percentage_mode_when_raw_three_candles_remain() -> None:
    reset_private_data_service()
    client = TestClient(create_app())
    headers = {"X-Session-ID": "chart-force-pct-remove"}
    source = {
        "mode": "multi",
        "series": [
            {
                "id": "SPY",
                "seriesType": "candlestick",
                "data": [
                    {"time": "2026-01-01", "open": 100, "high": 102, "low": 99, "close": 101},
                    {"time": "2026-01-02", "open": 101, "high": 103, "low": 100, "close": 102},
                ],
            },
            {
                "id": "QQQ",
                "seriesType": "candlestick",
                "data": [
                    {"time": "2026-01-01", "open": 200, "high": 202, "low": 199, "close": 201},
                    {"time": "2026-01-02", "open": 201, "high": 203, "low": 200, "close": 202},
                ],
            },
            {
                "id": "DIA",
                "seriesType": "candlestick",
                "data": [
                    {"time": "2026-01-01", "open": 300, "high": 302, "low": 299, "close": 301},
                    {"time": "2026-01-02", "open": 301, "high": 303, "low": 300, "close": 302},
                ],
            },
            {
                "id": "Fear & Greed",
                "seriesType": "line",
                "data": [
                    {"time": "2026-01-01", "value": 40},
                    {"time": "2026-01-02", "value": 45},
                ],
            },
        ],
    }

    write_response = client.post("/chart/api/chart-data", json=source, headers=headers)
    assert write_response.status_code == 200
    written = write_response.json()
    assert written["forcePercentage"] is True

    remove_response = client.post("/chart/api/chart-series/remove", json={"name": "Fear & Greed"}, headers=headers)
    assert remove_response.status_code == 200
    remove_payload = remove_response.json()
    assert remove_payload["mutation"]["forcePercentage"] is True

    chart_payload = client.get("/chart/api/chart-data", headers=headers).json()
    assert chart_payload["forcePercentage"] is True
    assert len(chart_payload["series"]) == 3
    assert all(series["returnSeries"] is True for series in chart_payload["series"])


def test_chart_data_write_initializes_standard_history_and_named_series(monkeypatch) -> None:
    def _fake_recent_history(self, name: str, *, period: str = "3y") -> HistoryChunk:
        _ = self
        assert name == "QQQ"
        assert period == "3y"
        return HistoryChunk(
            frame=TimeSeriesDataFrame(
                pd.DataFrame(
                    {
                        "time": ["2026-01-01", "2026-01-02"],
                        "close": [200.0, 202.0],
                    }
                )
            ),
            loaded_start="2026-01-01",
            loaded_end="2026-01-02",
            requested_period=period,
            is_complete=False,
            has_older=True,
            source_version="test",
        )

    monkeypatch.setattr(DataFactory, "get_recent_history", _fake_recent_history)
    reset_private_data_service()
    client = TestClient(create_app())
    headers = {"X-Session-ID": "chart-direct-standard"}
    source = {
        "mode": "multi",
        "series": [
            {
                "id": "S&P 500",
                "seriesType": "line",
                "data": [
                    {"time": "2026-01-01", "value": 5000.0},
                    {"time": "2026-01-02", "value": 5010.0},
                ],
            }
        ],
    }

    write_response = client.post("/chart/api/chart-data", json=source, headers=headers)
    assert write_response.status_code == 200
    write_payload = write_response.json()
    assert write_payload["historyBySeries"]["S&P 500"]["isComplete"] is True
    assert write_payload["historyBySeries"]["S&P 500"]["hasOlder"] is False
    assert write_payload["historyBySeries"]["S&P 500"]["backfillInFlight"] is False

    add_response = client.post("/chart/api/chart-series/add", json={"name": "QQQ"}, headers=headers)
    assert add_response.status_code == 200
    add_payload = add_response.json()
    assert add_payload["ok"] is True
    assert add_payload["mutation"]["entries"] == [
        {"name": "S&P 500", "pinned": False},
        {"name": "QQQ", "pinned": False},
    ]
    assert add_payload["mutation"]["seriesOrder"] == ["S&P 500", "QQQ"]
    assert add_payload["historyBySeries"]["S&P 500"]["isComplete"] is True
    assert add_payload["historyBySeries"]["QQQ"]["loadedStart"] == "2026-01-01"
    assert add_payload["historyBySeries"]["QQQ"]["backfillInFlight"] is True


def test_chart_series_set_returns_snapshot_payload_and_entries(monkeypatch) -> None:
    def _fake_recent_history(self, name: str, *, period: str = "3y") -> HistoryChunk:
        _ = self
        assert name == "spy"
        assert period == "3y"
        return HistoryChunk(
            frame=TimeSeriesDataFrame(
                pd.DataFrame(
                    {
                        "time": ["2026-01-01", "2026-01-02"],
                        "close": [100.0, 101.0],
                    }
                )
            ),
            loaded_start="2026-01-01",
            loaded_end="2026-01-02",
            requested_period=period,
            is_complete=False,
            has_older=True,
            source_version="test",
        )

    monkeypatch.setattr(DataFactory, "get_recent_history", _fake_recent_history)
    reset_private_data_service()
    client = TestClient(create_app())

    response = client.post("/chart/api/chart-series/set", json={"name": "spy", "pinned": True})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["mode"] == "multi"
    assert payload["dataLength"] == 2
    assert payload["series"][0]["id"] == "SPY"
    assert payload["entries"] == [{"name": "SPY", "pinned": True}]
    assert payload["historyBySeries"]["SPY"]["loadedStart"] == "2026-01-01"
    assert payload["historyBySeries"]["SPY"]["backfillInFlight"] is True
    assert payload["requestToken"]


def test_chart_series_add_and_remove_return_mutation_patches(monkeypatch) -> None:
    def _fake_recent_history(self, name: str, *, period: str = "3y") -> HistoryChunk:
        _ = self
        series_name = name.upper()
        if series_name not in {"SPY", "QQQ"}:
            raise AssertionError(series_name)
        assert period == "3y"
        return HistoryChunk(
            frame=TimeSeriesDataFrame(
                pd.DataFrame(
                    {
                        "time": ["2026-01-01", "2026-01-02"],
                        "close": [100.0, 101.0] if series_name == "SPY" else [200.0, 202.0],
                    }
                )
            ),
            loaded_start="2026-01-01",
            loaded_end="2026-01-02",
            requested_period=period,
            is_complete=False,
            has_older=True,
            source_version="test",
        )

    monkeypatch.setattr(DataFactory, "get_recent_history", _fake_recent_history)
    reset_private_data_service()
    client = TestClient(create_app())
    headers = {"X-Session-ID": "chart-series-mutation"}

    seed = client.post("/chart/api/chart-series/set", json={"name": "spy", "pinned": True}, headers=headers)
    assert seed.status_code == 200

    add_response = client.post("/chart/api/chart-series/add", json={"name": "qqq"}, headers=headers)
    assert add_response.status_code == 200
    add_payload = add_response.json()
    assert add_payload["ok"] is True
    assert add_payload["mutation"]["entries"] == [
        {"name": "SPY", "pinned": True},
        {"name": "QQQ", "pinned": False},
    ]
    assert add_payload["mutation"]["seriesOrder"] == ["SPY", "QQQ"]
    assert add_payload["historyBySeries"]["QQQ"]["loadedStart"] == "2026-01-01"
    assert add_payload["historyBySeries"]["QQQ"]["backfillInFlight"] is True
    assert [series["id"] for series in add_payload["mutation"]["upsertSeries"]] == ["SPY", "QQQ"]

    remove_response = client.post("/chart/api/chart-series/remove", json={"name": "QQQ"}, headers=headers)
    assert remove_response.status_code == 200
    remove_payload = remove_response.json()
    assert remove_payload["ok"] is True
    assert remove_payload["mutation"]["entries"] == [{"name": "SPY", "pinned": True}]
    assert remove_payload["mutation"]["removedSeriesIds"] == ["QQQ"]
