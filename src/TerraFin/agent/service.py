import math
from typing import Any, Iterable

import pandas as pd

from TerraFin.analytics.analysis.fundamental.dcf import (
    build_stock_dcf_payload,
    build_stock_reverse_dcf_payload,
)
from TerraFin.analytics.analysis.fundamental.dcf.presenters import build_sp500_dcf_payload
from TerraFin.analytics.analysis.fundamental.screen import run_fundamental_screen
from TerraFin.analytics.analysis.risk.profile import run_risk_profile
from TerraFin.analytics.analysis.risk.returns import extract_close_series
from TerraFin.analytics.analysis.technical import DEFAULT_MFD_WINDOWS
from TerraFin.data import DataFactory
from TerraFin.data.contracts import TimeSeriesDataFrame
from TerraFin.data.providers.corporate.investor_positioning import get_portfolio_data
from TerraFin.interface.chart.chart_view import apply_view
from TerraFin.interface.chart.formatters import build_multi_payload
from TerraFin.interface.chart.indicators.adapter import (
    compute_bollinger_bands,
    compute_macd,
    compute_mandelbrot_fractal_dimension,
    compute_moving_averages,
    compute_range_volatility,
    compute_realized_volatility,
    compute_rsi,
    compute_trend_signal,
)
from TerraFin.interface.market_insights.payloads import (
    build_macro_info_payload,
    canonical_macro_name,
    get_macro_description,
    resolve_macro_type,
)
from TerraFin.interface.private_data_service import get_private_data_service
from TerraFin.interface.stock.data_routes import build_beta_estimate_payload
from TerraFin.interface.stock.payloads import (
    build_company_info_payload,
    build_earnings_payload,
    build_filing_document_payload,
    build_filings_list_payload,
    build_financial_statement_payload,
    resolve_ticker_query,
)
from TerraFin.interface.watchlist_service import get_watchlist_service

from .models import ChartView, DepthMode, ProcessingMetadata


DEFAULT_RECENT_PERIOD = "3y"
VALID_DEPTHS = {"auto", "recent", "full"}
VALID_VIEWS = {"daily", "weekly", "monthly", "yearly"}


def _normalize_depth(depth: str | None) -> DepthMode:
    text = (depth or "auto").strip().lower()
    if text not in VALID_DEPTHS:
        raise ValueError(f"Unsupported depth: {depth}")
    return text  # type: ignore[return-value]


def _normalize_view(view: str | None) -> ChartView:
    text = (view or "daily").strip().lower()
    if text not in VALID_VIEWS:
        raise ValueError(f"Unsupported view: {view}")
    return text  # type: ignore[return-value]


def _frame_bounds(frame: TimeSeriesDataFrame) -> tuple[str | None, str | None]:
    if frame.empty or "time" not in frame.columns:
        return None, None
    times = pd.to_datetime(frame["time"], errors="coerce").dropna()
    if times.empty:
        return None, None
    return times.iloc[0].strftime("%Y-%m-%d"), times.iloc[-1].strftime("%Y-%m-%d")


def _full_processing(
    *,
    requested_depth: DepthMode,
    source_version: str,
    view: ChartView | None,
    frame: TimeSeriesDataFrame | None = None,
) -> dict[str, Any]:
    loaded_start, loaded_end = (None, None) if frame is None else _frame_bounds(frame)
    return ProcessingMetadata(
        requestedDepth=requested_depth,
        resolvedDepth="full",
        loadedStart=loaded_start,
        loadedEnd=loaded_end,
        isComplete=True,
        hasOlder=False,
        sourceVersion=source_version,
        view=view,
    ).model_dump()


def _chunk_processing(*, requested_depth: DepthMode, view: ChartView, history_chunk) -> dict[str, Any]:
    resolved_depth = "full" if history_chunk.is_complete else "recent"
    return ProcessingMetadata(
        requestedDepth=requested_depth,
        resolvedDepth=resolved_depth,
        loadedStart=history_chunk.loaded_start,
        loadedEnd=history_chunk.loaded_end,
        isComplete=history_chunk.is_complete,
        hasOlder=history_chunk.has_older,
        sourceVersion=history_chunk.source_version,
        view=view,
    ).model_dump()


def _primary_series(frame: TimeSeriesDataFrame, *, view: ChartView) -> dict[str, Any]:
    payload = build_multi_payload([frame])
    transformed = apply_view(payload, view)
    series = transformed.get("series", [])
    if not series:
        raise LookupError(f"No chartable data found for '{frame.name or 'series'}'.")
    return dict(series[0])


def _series_points(series: dict[str, Any]) -> list[dict[str, Any]]:
    points = series.get("data", [])
    return [dict(point) for point in points if isinstance(point, dict)]


def _series_closes(series: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for point in _series_points(series):
        if point.get("close") is not None:
            values.append(float(point["close"]))
        elif point.get("value") is not None:
            values.append(float(point["value"]))
    return values


def _indicator_input(series: dict[str, Any]) -> list[dict[str, Any]]:
    points = _series_points(series)
    if series.get("seriesType") == "candlestick":
        return points
    converted: list[dict[str, Any]] = []
    for point in points:
        value = point.get("value")
        if value is None:
            continue
        converted.append({"time": point.get("time"), "close": float(value)})
    return converted


def _offset_for(base_points: list[dict[str, Any]], values: list[dict[str, Any]]) -> int:
    return max(len(base_points) - len(values), 0)


def _line_values(series: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for point in series.get("data", []):
        if isinstance(point, dict) and point.get("value") is not None:
            values.append(float(point["value"]))
    return values


def _compute_indicator_results(
    series: dict[str, Any], requested: list[str]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    input_points = _indicator_input(series)
    base_points = _series_points(series)
    results: dict[str, dict[str, Any]] = {}
    unknown: list[str] = []

    ma_map = {}
    for overlay in compute_moving_averages(input_points):
        indicator_id = str(overlay.get("id", ""))
        if indicator_id.startswith("MA "):
            ma_map[f"sma_{indicator_id.split(' ', 1)[1]}"] = overlay

    cache: dict[str, list[dict[str, Any]]] = {
        "rsi": compute_rsi(input_points),
        "bb": compute_bollinger_bands(input_points),
        "macd": compute_macd(input_points),
        "realized_vol": compute_realized_volatility(input_points),
        "range_vol": compute_range_volatility(input_points),
        "trend_signal": compute_trend_signal(input_points),
        "mfd": compute_mandelbrot_fractal_dimension(input_points, windows=DEFAULT_MFD_WINDOWS),
    }
    mfd_map = {}
    for overlay in cache["mfd"]:
        indicator_id = str(overlay.get("id", ""))
        if indicator_id.startswith("MFD "):
            mfd_map[f"mfd_{indicator_id.split(' ', 1)[1]}"] = overlay

    for name in requested:
        if name in ma_map:
            overlay = ma_map[name]
            values = _line_values(overlay)
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, overlay.get("data", [])),
                "values": {
                    "value": values[-1] if values else None,
                    "series": values,
                },
            }
            continue

        if name == "rsi":
            overlays = cache["rsi"]
            overlay = overlays[0] if overlays else {"data": []}
            values = _line_values(overlay)
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, overlay.get("data", [])),
                "values": {"value": values[-1] if values else None, "series": values},
            }
            continue

        if name == "bb":
            overlays = cache["bb"]
            upper = overlays[0] if len(overlays) > 0 else {"data": []}
            lower = overlays[1] if len(overlays) > 1 else {"data": []}
            upper_values = _line_values(upper)
            lower_values = _line_values(lower)
            latest_close = _series_closes(series)
            position = None
            if latest_close and upper_values and lower_values:
                midpoint = (upper_values[-1] + lower_values[-1]) / 2
                if latest_close[-1] > midpoint:
                    position = "upper"
                elif latest_close[-1] < midpoint:
                    position = "lower"
                else:
                    position = "middle"
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, upper.get("data", [])),
                "values": {
                    "position": position,
                    "upper": upper_values,
                    "lower": lower_values,
                },
            }
            continue

        if name == "macd":
            overlays = cache["macd"]
            histogram = next(
                (overlay for overlay in overlays if overlay.get("seriesType") == "histogram"), {"data": []}
            )
            macd_line = next((overlay for overlay in overlays if overlay.get("id") == "MACD"), {"data": []})
            signal_line = next((overlay for overlay in overlays if overlay.get("id") == "Signal"), {"data": []})
            hist_values = _line_values(histogram)
            last_hist = hist_values[-1] if hist_values else 0.0
            signal_label = "bullish" if last_hist > 0 else "bearish" if last_hist < 0 else "neutral"
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, macd_line.get("data", [])),
                "values": {
                    "signal": signal_label if hist_values else None,
                    "histogram_value": last_hist if hist_values else None,
                    "series": {
                        "macd": _line_values(macd_line),
                        "signal": _line_values(signal_line),
                        "histogram": hist_values,
                    },
                },
            }
            continue

        if name == "realized_vol":
            overlays = cache["realized_vol"]
            overlay = overlays[0] if overlays else {"data": []}
            values = _line_values(overlay)
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, overlay.get("data", [])),
                "values": {"value": values[-1] if values else None, "series": values},
            }
            continue

        if name == "range_vol":
            overlays = cache["range_vol"]
            overlay = overlays[0] if overlays else {"data": []}
            values = _line_values(overlay)
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, overlay.get("data", [])),
                "values": {"value": values[-1] if values else None, "series": values},
            }
            continue

        if name == "trend_signal":
            overlays = cache["trend_signal"]
            overlay = overlays[0] if overlays else {"data": []}
            values = _line_values(overlay)
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, overlay.get("data", [])),
                "values": {"value": values[-1] if values else None, "series": values},
            }
            continue

        if name in {"mfd", "mfd_65", "mfd_130", "mfd_260"}:
            if name == "mfd":
                latest: dict[str, float | None] = {}
                series_map: dict[str, list[float]] = {}
                offsets: dict[str, int] = {}
                for key in ("mfd_65", "mfd_130", "mfd_260"):
                    overlay = mfd_map.get(key, {"data": []})
                    values = _line_values(overlay)
                    window = key.split("_", 1)[1]
                    latest[window] = values[-1] if values else None
                    series_map[window] = values
                    offsets[window] = (
                        _offset_for(base_points, overlay.get("data", [])) if overlay.get("data") else int(window)
                    )
                results[name] = {
                    "name": name,
                    "offset": min(offsets.values()),
                    "values": {
                        "latest": latest,
                        "series": series_map,
                        "offsets": offsets,
                    },
                }
            else:
                overlay = mfd_map.get(name, {"data": []})
                values = _line_values(overlay)
                window = int(name.split("_", 1)[1])
                results[name] = {
                    "name": name,
                    "offset": _offset_for(base_points, overlay.get("data", [])) if overlay.get("data") else window,
                    "values": {"value": values[-1] if values else None, "series": values},
                }
            continue

        unknown.append(name)

    return results, unknown


def _price_action(series: dict[str, Any]) -> dict[str, float | None]:
    closes = _series_closes(series)
    current = closes[-1] if closes else None
    change_1d = round(((closes[-1] / closes[-2]) - 1) * 100, 2) if len(closes) >= 2 else None
    change_5d = round(((closes[-1] / closes[-6]) - 1) * 100, 2) if len(closes) >= 6 else None
    return {"current": current, "change_1d": change_1d, "change_5d": change_5d}


def _calendar_processing() -> dict[str, Any]:
    return _full_processing(requested_depth="full", source_version="calendar", view=None, frame=None)


class TerraFinAgentService:
    def __init__(self, data_factory: DataFactory | None = None) -> None:
        self._data_factory = data_factory or DataFactory()

    def _market_series(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        requested_depth = _normalize_depth(depth)
        resolved_view = _normalize_view(view)
        display_name = name.strip()
        if not display_name:
            raise ValueError("Name is required")
        canonical_name = canonical_macro_name(display_name)
        if resolve_macro_type(canonical_name) is not None:
            display_name = canonical_name

        if requested_depth == "full":
            frame = self._data_factory.get(display_name)
            if frame is None or frame.empty:
                raise LookupError(f"No data found for '{display_name}'")
            frame.name = display_name
            series = _primary_series(frame, view=resolved_view)
            processing = _full_processing(
                requested_depth=requested_depth,
                source_version="datafactory-full",
                view=resolved_view,
                frame=frame,
            )
            return {"name": display_name, "series": series, "processing": processing, "frame": frame}

        history_chunk = self._data_factory.get_recent_history(display_name, period=DEFAULT_RECENT_PERIOD)
        if history_chunk.frame is None or history_chunk.frame.empty:
            raise LookupError(f"No data found for '{display_name}'")
        history_chunk.frame.name = display_name
        series = _primary_series(history_chunk.frame, view=resolved_view)
        processing = _chunk_processing(
            requested_depth=requested_depth,
            view=resolved_view,
            history_chunk=history_chunk,
        )
        return {"name": display_name, "series": series, "processing": processing, "frame": history_chunk.frame}

    def resolve(self, query: str) -> dict[str, Any]:
        payload = resolve_ticker_query(query)
        payload["processing"] = _full_processing(
            requested_depth="full",
            source_version="resolver",
            view=None,
            frame=None,
        )
        return payload

    def market_data(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        payload = self._market_series(name, depth=depth, view=view)
        series = payload["series"]
        return {
            "ticker": payload["name"],
            "seriesType": series.get("seriesType", "line"),
            "count": len(series.get("data", [])),
            "data": _series_points(series),
            "processing": payload["processing"],
        }

    def indicators(
        self, name: str, indicators: str | Iterable[str], *, depth: str = "auto", view: str = "daily"
    ) -> dict[str, Any]:
        payload = self._market_series(name, depth=depth, view=view)
        requested = (
            [item.strip() for item in indicators.split(",") if item.strip()]
            if isinstance(indicators, str)
            else [str(item).strip() for item in indicators if str(item).strip()]
        )
        results, unknown = _compute_indicator_results(payload["series"], requested)
        return {
            "ticker": payload["name"],
            "indicators": results,
            "unknown": unknown,
            "processing": payload["processing"],
        }

    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        """Per-ticker price action + indicators only.

        Previously bundled market-wide `market_breadth` and `watchlist`
        inside this response, which mixed a per-ticker view with
        whole-market state — the agent would reference breadth numbers
        alongside a ticker snapshot and risk diverging from the
        standalone MarketBreadthCard widget if the widget refreshed on
        its own. Use the `market_breadth` and `watchlist` capabilities
        for those (matching the standalone widgets).
        """
        payload = self._market_series(name, depth=depth, view=view)
        series = payload["series"]
        indicator_results, _ = _compute_indicator_results(series, ["rsi", "macd", "bb"])
        return {
            "ticker": payload["name"],
            "price_action": _price_action(series),
            "indicators": {
                "rsi": indicator_results.get("rsi", {}).get("values", {}).get("value"),
                "macd_signal": indicator_results.get("macd", {}).get("values", {}).get("signal"),
                "bb_position": indicator_results.get("bb", {}).get("values", {}).get("position"),
            },
            "processing": payload["processing"],
        }

    def lppl_analysis(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        from TerraFin.analytics.analysis.technical.lppl import lppl

        payload = self._market_series(name, depth=depth, view=view)
        closes = _series_closes(payload["series"])
        result = lppl(closes)

        pct = result.confidence * 100
        if pct < 5:
            interpretation, market_state = "No LPPL pattern", "Normal market"
        elif pct < 15:
            interpretation, market_state = "Some bubble possibility", "Caution warranted"
        elif pct < 25:
            interpretation, market_state = "Growing bubble formation", "Warning level"
        elif pct < 40:
            interpretation, market_state = "High confidence", "Overheated (crash likely)"
        else:
            interpretation, market_state = "Very high confidence", "Bubble peak, crash imminent"

        fits = [
            {
                "tc": f.tc,
                "m": f.m,
                "omega": f.omega,
                "b": f.b,
                "c_over_b": f.c / abs(f.b) if abs(f.b) > 1e-12 else 0.0,
                "residual": f.residual,
            }
            for f in result.qualifying_fits
        ]
        return {
            "name": payload["name"],
            "confidence": result.confidence,
            "interpretation": interpretation,
            "market_state": market_state,
            "qualifying_count": len(result.qualifying_fits),
            "total_windows": result.total_windows,
            "qualifying_fits": fits,
            "processing": payload["processing"],
        }

    def company_info(self, ticker: str) -> dict[str, Any]:
        payload = build_company_info_payload(ticker)
        payload["processing"] = _full_processing(
            requested_depth="full",
            source_version="stock-company",
            view=None,
            frame=None,
        )
        return payload

    def earnings(self, ticker: str) -> dict[str, Any]:
        payload = build_earnings_payload(ticker)
        payload["processing"] = _full_processing(
            requested_depth="full",
            source_version="stock-earnings",
            view=None,
            frame=None,
        )
        return payload

    def financials(self, ticker: str, *, statement: str = "income", period: str = "annual") -> dict[str, Any]:
        payload = build_financial_statement_payload(ticker, statement=statement, period=period)
        payload["processing"] = _full_processing(
            requested_depth="full",
            source_version="stock-financials",
            view=None,
            frame=None,
        )
        return payload

    def sec_filings(self, ticker: str) -> dict[str, Any]:
        """List recent 10-K / 10-Q / 8-K filings for a ticker with EDGAR links."""
        payload = build_filings_list_payload(ticker)
        return {
            **payload,
            "processing": _full_processing(
                requested_depth="full",
                source_version="sec-filings-list",
                view=None,
                frame=None,
            ),
        }

    def sec_filing_document(
        self,
        ticker: str,
        accession: str,
        primaryDocument: str,
        *,
        form: str = "10-Q",
    ) -> dict[str, Any]:
        """Fetch a filing's structured table of contents without the full markdown body.

        Agents use this to decide which sections are worth reading before pulling
        their prose via ``sec_filing_section`` — keeps the model's working
        context small even for 60 KB+ filings.
        """
        payload = build_filing_document_payload(ticker, accession, primaryDocument, form=form)
        return {
            "ticker": payload["ticker"],
            "accession": payload["accession"],
            "primaryDocument": payload["primaryDocument"],
            "toc": payload["toc"],
            "charCount": payload["charCount"],
            "indexUrl": payload["indexUrl"],
            "documentUrl": payload["documentUrl"],
            "processing": _full_processing(
                requested_depth="full",
                source_version="sec-filing-document",
                view=None,
                frame=None,
            ),
        }

    def sec_filing_section(
        self,
        ticker: str,
        accession: str,
        primaryDocument: str,
        sectionSlug: str,
        *,
        form: str = "10-Q",
    ) -> dict[str, Any]:
        """Fetch a single section body by slug from a filing.

        Returns only the target section's markdown, keeping the agent's context
        small for iterative section-by-section analysis.
        """
        payload = build_filing_document_payload(ticker, accession, primaryDocument, form=form)
        toc = payload["toc"]
        try:
            entry = next(e for e in toc if e["slug"] == sectionSlug)
        except StopIteration as exc:
            # Surface the FULL TOC with sizes so the agent has everything it
            # needs to retry without another `sec_filing_document` round-trip.
            # Sort suggestions by charCount descending — when the intended
            # section wasn't caught by the parser (common for 10-K Item 7/8),
            # the wanted content usually lives inside the largest neighbor.
            sorted_entries = sorted(
                ({"slug": e["slug"], "text": e["text"], "charCount": e["charCount"]} for e in toc),
                key=lambda e: e["charCount"],
                reverse=True,
            )
            top_hint = ", ".join(
                f"{e['slug']} ({e['charCount']:,} chars, '{e['text']}')"
                for e in sorted_entries[:5]
            )
            raise LookupError(
                f"Section '{sectionSlug}' not found. "
                f"Do NOT report 'section doesn't exist' — retry this tool with one of the available "
                f"slugs. The 5 largest sections in this filing are: {top_hint}. "
                f"If the user asked about earnings/financials/MD&A and no slug matches those names "
                f"directly, pick the LARGEST slug in Part II — 10-K parsers often leave MD&A and "
                f"Financial Statements inside an oversized neighbor section. "
                f"All {len(toc)} available slugs: "
                + ", ".join(e["slug"] for e in toc)
            ) from exc

        # Upper bound = next raw TOC entry (by ascending lineIndex), so the body
        # stops at the exact next heading in the markdown.
        lines = payload["markdown"].split("\n")
        later = [e for e in toc if e["lineIndex"] > entry["lineIndex"]]
        end_line = later[0]["lineIndex"] if later else len(lines)
        body = "\n".join(lines[entry["lineIndex"] + 1 : end_line]).strip()

        return {
            "ticker": payload["ticker"],
            "accession": payload["accession"],
            "sectionSlug": sectionSlug,
            "sectionTitle": entry["text"],
            "markdown": body,
            "charCount": len(body),
            "documentUrl": payload["documentUrl"],
            "processing": _full_processing(
                requested_depth="full",
                source_version="sec-filing-section",
                view=None,
                frame=None,
            ),
        }

    def portfolio(self, guru: str) -> dict[str, Any]:
        output = get_portfolio_data(guru)
        # Mirror the route's `topHoldings` pre-computation so the agent and
        # the UI's treemap/ranking use the same top 8. Without this, the
        # agent would have to re-sort the full `holdings` list and could
        # diverge on ties or sort-key interpretation (DA Med-9).
        df = output.df
        if not df.empty and {"Stock", "% of Portfolio", "Recent Activity", "Updated"}.issubset(df.columns):
            top_holdings = (
                df[["Stock", "% of Portfolio", "Recent Activity", "Updated"]]
                .sort_values(by="% of Portfolio", ascending=False)
                .head(8)
                .to_dict(orient="records")
            )
        else:
            top_holdings = []
        return {
            "guru": guru,
            "info": dict(output.info),
            "holdings": df.to_dict(orient="records"),
            "topHoldings": top_holdings,
            "count": len(df),
            "processing": _full_processing(
                requested_depth="full",
                source_version="portfolio",
                view=None,
                frame=None,
            ),
        }

    def economic(self, indicators: str | Iterable[str]) -> dict[str, Any]:
        requested = (
            [item.strip() for item in indicators.split(",") if item.strip()]
            if isinstance(indicators, str)
            else [str(item).strip() for item in indicators if str(item).strip()]
        )
        results: dict[str, dict[str, Any]] = {}
        for name in requested:
            display_name = canonical_macro_name(name)
            try:
                if display_name in indicator_registry._indicators:
                    data = self._data_factory.get_economic_data(display_name)
                else:
                    raw_name = name.strip()
                    data = self._data_factory.get_fred_data(raw_name)
                    display_name = raw_name
            except Exception:
                data = TimeSeriesDataFrame.make_empty()
            if data is not None and not data.empty:
                series = [
                    {"time": str(row.get("time", "")), "value": float(row["close"])} for _, row in data.iterrows()
                ]
                results[display_name] = {
                    "name": display_name,
                    "latest_value": round(float(data["close"].iloc[-1]), 4),
                    "latest_time": str(data["time"].iloc[-1]),
                    "series": series,
                }
            else:
                results[display_name] = {
                    "name": display_name,
                    "latest_value": None,
                    "latest_time": None,
                    "series": [],
                }
        return {
            "indicators": results,
            "processing": _full_processing(
                requested_depth="full",
                source_version="economic",
                view=None,
                frame=None,
            ),
        }

    def macro_focus(
        self,
        name: str,
        *,
        depth: str = "auto",
        view: str = "daily",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Macro summary + chart-ready series for a named instrument.

        If `session_id` is supplied and the user has stored a named series
        on that session (e.g. a custom range loaded into the macro chart
        via the market-insights page), prefer that session-local frame —
        matches `/market-insights/api/macro-info`'s behavior, where the
        frontend sends `X-Session-ID` to avoid ignoring the user's chart
        state. Without session-awareness the agent would answer questions
        about a different time range than the user was staring at.
        """
        resolved_name = canonical_macro_name(name)
        indicator_type = resolve_macro_type(resolved_name)
        if indicator_type is None:
            raise LookupError(f"Unknown macro instrument: '{resolved_name}'")

        session_frame = None
        if session_id:
            try:
                from TerraFin.interface.chart.state import get_named_series

                session_frame = get_named_series(session_id).get(resolved_name)
            except Exception:
                session_frame = None

        if session_frame is not None:
            # User has a custom macro series loaded in their session. Use it
            # verbatim so agent's view matches what they're looking at.
            session_frame.name = resolved_name
            series_payload = _primary_series(session_frame, view=_normalize_view(view))
            info = build_macro_info_payload(
                resolved_name,
                get_macro_description(resolved_name),
                session_frame,
                indicator_type=indicator_type,
            )
            processing = _full_processing(
                requested_depth=_normalize_depth(depth),
                source_version="macro-session",
                view=_normalize_view(view),
                frame=session_frame,
            )
            return {
                "name": resolved_name,
                "info": info,
                "seriesType": series_payload.get("seriesType", "line"),
                "count": len(series_payload.get("data", [])),
                "data": _series_points(series_payload),
                "processing": processing,
            }

        payload = self._market_series(resolved_name, depth=depth, view=view)
        frame = payload["frame"]
        info = build_macro_info_payload(
            resolved_name,
            get_macro_description(resolved_name),
            frame,
            indicator_type=indicator_type,
        )
        return {
            "name": resolved_name,
            "info": info,
            "seriesType": payload["series"].get("seriesType", "line"),
            "count": len(payload["series"].get("data", [])),
            "data": _series_points(payload["series"]),
            "processing": payload["processing"],
        }

    def calendar_events(
        self,
        *,
        year: int,
        month: int,
        categories: str | Iterable[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        category_filter = None
        if isinstance(categories, str) and categories.strip():
            category_filter = {item.strip() for item in categories.split(",") if item.strip()}
        elif categories is not None:
            category_filter = {str(item).strip() for item in categories if str(item).strip()}

        events = get_private_data_service().get_calendar_events(
            year=year,
            month=month,
            categories=category_filter,
            limit=limit,
        )
        return {
            "events": [dict(event) for event in events],
            "count": len(events),
            "month": month,
            "year": year,
            "processing": _calendar_processing(),
        }

    def fundamental_screen(self, ticker: str) -> dict[str, Any]:
        normalized = ticker.upper()
        income = self._data_factory.get_corporate_data(normalized, "income", period="annual")
        balance = self._data_factory.get_corporate_data(normalized, "balance", period="annual")
        cashflow = self._data_factory.get_corporate_data(normalized, "cashflow", period="annual")

        result = run_fundamental_screen(
            normalized,
            income=income,
            balance=balance,
            cashflow=cashflow,
        )
        return {
            "ticker": result.ticker,
            "moat": result.moat,
            "earnings_quality": result.earnings_quality,
            "balance_sheet": result.balance_sheet,
            "capital_allocation": result.capital_allocation,
            "pricing_power": result.pricing_power,
            "warnings": result.warnings,
            "processing": _full_processing(
                requested_depth="full",
                source_version="fundamental-screen",
                view=None,
                frame=None,
            ),
        }

    def risk_profile(self, name: str, *, depth: str = "auto") -> dict[str, Any]:
        payload = self._market_series(name, depth=depth, view="daily")
        frame = payload["frame"]
        prices = extract_close_series(frame)

        benchmark_frame = self._data_factory.get_market_data("SPY")
        benchmark_prices = extract_close_series(benchmark_frame) if benchmark_frame is not None else None

        result = run_risk_profile(payload["name"], prices, benchmark_prices=benchmark_prices)
        return {
            "ticker": result.ticker,
            "tail_risk": result.tail_risk,
            "convexity": result.convexity,
            "volatility": result.volatility,
            "drawdown": result.drawdown,
            "warnings": result.warnings,
            "processing": payload["processing"],
        }

    def valuation(
        self,
        ticker: str,
        *,
        projection_years: int | None = None,
        fcf_base_source: str | None = None,
        breakeven_year: int | None = None,
        breakeven_cash_flow_per_share: float | None = None,
        post_breakeven_growth_pct: float | None = None,
    ) -> dict[str, Any]:
        normalized = ticker.upper()
        # Build the DCF with optional overrides so the agent can mirror the
        # frontend's DCF input form (Forecast Horizon, FCF Base Source picker,
        # Turnaround Mode). When all three turnaround fields are supplied the
        # template switches to the explicit per-year schedule path; otherwise
        # the standard single-base × growth-curve model runs.
        from TerraFin.analytics.analysis.fundamental.dcf.models import StockDCFOverrides

        overrides_kwargs: dict[str, Any] = {}
        if fcf_base_source is not None:
            overrides_kwargs["fcf_base_source"] = fcf_base_source  # type: ignore[arg-type]
        if breakeven_year is not None:
            overrides_kwargs["breakeven_year"] = int(breakeven_year)
        if breakeven_cash_flow_per_share is not None:
            overrides_kwargs["breakeven_cash_flow_per_share"] = float(breakeven_cash_flow_per_share)
        if post_breakeven_growth_pct is not None:
            overrides_kwargs["post_breakeven_growth_pct"] = float(post_breakeven_growth_pct)
        overrides = StockDCFOverrides(**overrides_kwargs) if overrides_kwargs else None

        dcf = build_stock_dcf_payload(
            normalized,
            overrides=overrides,
            projection_years=projection_years,
        )
        reverse_dcf = build_stock_reverse_dcf_payload(normalized)

        info = build_company_info_payload(normalized)
        trailing_pe = info.get("trailingPE")
        forward_pe = info.get("forwardPE")
        trailing_eps = info.get("trailingEps")
        current_price = info.get("currentPrice")

        balance = self._data_factory.get_corporate_data(normalized, "balance", period="annual")
        bvps = None
        graham_number = None
        if balance is not None and not balance.empty:
            equity_col = None
            shares_col = None
            for col in balance.columns:
                cl = str(col).lower().replace(" ", "")
                if cl in ("totalstockholdersequity", "stockholdersequity", "totalequity"):
                    equity_col = col
                if cl in ("ordinarysharesoutstanding", "sharesoutstanding", "commonstock"):
                    shares_col = col
            if equity_col is not None and shares_col is not None:
                try:
                    eq = float(balance[equity_col].iloc[-1])
                    sh = float(balance[shares_col].iloc[-1])
                    if sh > 0:
                        bvps = round(eq / sh, 2)
                except (TypeError, ValueError, IndexError):
                    pass

        if trailing_eps and bvps and trailing_eps > 0 and bvps > 0:
            graham_number = round(math.sqrt(22.5 * trailing_eps * bvps), 2)

        margin_of_safety = None
        intrinsic_value = dcf.get("currentIntrinsicValue") if dcf.get("status") == "ready" else None
        if intrinsic_value and current_price and current_price > 0:
            margin_of_safety = round((intrinsic_value - current_price) / current_price * 100, 2)

        # Pass the full route payloads through verbatim so the agent sees the
        # exact same `DCFValuationResponse` / `ReverseDCFResponse` structure
        # that renders in the frontend's DcfValuationPanel — scenarios,
        # sensitivity matrix, methods, rateCurve, dataQuality, all of it.
        # Previously this method cherry-picked 4 fields from each, which
        # broke user↔agent view parity (audit: DA High-1, High-2).
        return {
            "ticker": normalized,
            "dcf": dcf,
            "reverseDcf": reverse_dcf,
            "relative": {
                "trailingPE": trailing_pe,
                "forwardPE": forward_pe,
                "priceToBook": (
                    round(current_price / bvps, 2)
                    if current_price and bvps and bvps > 0 else None
                ),
            },
            "grahamNumber": graham_number,
            "marginOfSafetyPct": margin_of_safety,
            "currentPrice": current_price,
            "processing": _full_processing(
                requested_depth="full",
                source_version="valuation",
                view=None,
                frame=None,
            ),
        }

    # -----------------------------------------------------------------
    # Capabilities that expose standalone widgets the dashboard and
    # market-insights pages render. Before these existed, the agent
    # could not answer questions about data the user was clearly
    # looking at (Fear & Greed, S&P 500 DCF, beta R², top companies,
    # regime summary, trailing-forward P/E). Every method here returns
    # the route's payload verbatim (camelCase intact) so the agent
    # sees the same fields the frontend renders.
    # -----------------------------------------------------------------

    def fear_greed(self) -> dict[str, Any]:
        """CNN Fear & Greed index — matches `/dashboard/api/fear-greed`."""
        payload = dict(get_private_data_service().get_fear_greed_current())
        payload["processing"] = _full_processing(
            requested_depth="full",
            source_version="fear-greed",
            view=None,
            frame=None,
        )
        return payload

    def sp500_dcf(self) -> dict[str, Any]:
        """Full S&P 500 DCF — matches `/market-insights/api/dcf/sp500`.

        Returns the same DCFValuationResponse shape (scenarios, sensitivity,
        methods, rateCurve, dataQuality) the SP500 DCF panel renders.
        """
        payload = dict(build_sp500_dcf_payload())
        payload["processing"] = _full_processing(
            requested_depth="full",
            source_version="sp500-dcf",
            view=None,
            frame=None,
        )
        return payload

    def beta_estimate(self, ticker: str) -> dict[str, Any]:
        """5-year monthly beta estimate — matches `/stock/api/beta-estimate`.

        Returns beta, adjusted beta, R², observations, benchmark, warnings.
        The `company_info` tool only surfaces a string `beta` field; use this
        capability when you need the statistical quality of the estimate.
        """
        payload = dict(build_beta_estimate_payload(ticker))
        payload["processing"] = _full_processing(
            requested_depth="full",
            source_version="beta-estimate",
            view=None,
            frame=None,
        )
        return payload

    def top_companies(self) -> dict[str, Any]:
        """Market-insights top-companies list — matches `/market-insights/api/top-companies`."""
        try:
            companies = get_private_data_service().get_top_companies()
        except Exception:
            companies = []
        return {
            "companies": companies,
            "count": len(companies),
            "processing": _full_processing(
                requested_depth="full",
                source_version="top-companies",
                view=None,
                frame=None,
            ),
        }

    def market_regime(self) -> dict[str, Any]:
        """Market regime summary — matches `/market-insights/api/regime`.

        The route currently returns a static placeholder; the agent sees the
        same placeholder so the two views never diverge. If the route is
        upgraded to a real regime model later, this capability will
        automatically reflect the change without code edits here.
        """
        # Mirror the route's placeholder exactly — user↔agent parity trumps
        # "placeholder data should be obvious to callers". If the route is
        # updated to a real model, update both sides together.
        return {
            "summary": "Mixed regime with selective risk-taking and elevated event sensitivity.",
            "confidence": "low",
            "signals": [
                "Breadth is improving in pockets but still uneven.",
                "Macro event concentration this week can raise short-term volatility.",
                "Leadership remains concentrated in a handful of large-cap names.",
            ],
            "processing": _full_processing(
                requested_depth="full",
                source_version="market-regime-placeholder",
                view=None,
                frame=None,
            ),
        }

    def trailing_forward_pe(self) -> dict[str, Any]:
        """Trailing minus forward P/E spread — matches `/dashboard/api/trailing-forward-pe-spread`."""
        private_service = get_private_data_service()
        payload = private_service.get_trailing_forward_pe() or {}
        summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
        coverage = payload.get("coverage", {}) if isinstance(payload, dict) else {}
        history = payload.get("history", []) if isinstance(payload, dict) else []
        return {
            "date": str(payload.get("date", "")) if isinstance(payload, dict) else "",
            "description": (
                "Trailing P/E minus forward P/E, used as a rough proxy for how much "
                "future earnings expectations diverge from trailing earnings."
            ),
            "latestValue": summary.get("trailing_forward_pe_spread"),
            "usableCount": coverage.get("usable"),
            "requestedCount": coverage.get("requested"),
            "history": list(history),
            "processing": _full_processing(
                requested_depth="full",
                source_version="trailing-forward-pe",
                view=None,
                frame=None,
            ),
        }

    def market_breadth(self) -> dict[str, Any]:
        """Market breadth metrics — matches `/dashboard/api/market-breadth`.

        Was previously bundled inside `market_snapshot`, which mixed a
        per-ticker view with whole-market state. Now a standalone capability
        so agent and the MarketBreadthCard widget query the same data.
        """
        metrics = get_private_data_service().get_market_breadth()
        return {
            "metrics": list(metrics),
            "processing": _full_processing(
                requested_depth="full",
                source_version="market-breadth",
                view=None,
                frame=None,
            ),
        }

    def watchlist(self) -> dict[str, Any]:
        """User's watchlist — matches the WatchlistSection dashboard widget.

        Was previously bundled inside `market_snapshot`. Standalone here so
        agent and the widget query the same list without ticker-scoped
        confusion.
        """
        snapshot = get_watchlist_service().get_watchlist_snapshot() or []
        return {
            "items": list(snapshot),
            "count": len(snapshot),
            "processing": _full_processing(
                requested_depth="full",
                source_version="watchlist",
                view=None,
                frame=None,
            ),
        }
