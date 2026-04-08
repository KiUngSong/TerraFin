from collections.abc import Iterable
from typing import Any

from TerraFin.data.contracts import TimeSeriesDataFrame

from .client import TerraFinAgentClient


def _client(client: TerraFinAgentClient | None, **kwargs: Any) -> TerraFinAgentClient:
    return client if client is not None else TerraFinAgentClient(**kwargs)


def ticker_brief(
    name: str,
    *,
    client: TerraFinAgentClient | None = None,
    depth: str = "auto",
    view: str = "daily",
    **client_kwargs: Any,
) -> dict[str, Any]:
    agent = _client(client, **client_kwargs)
    resolved = agent.resolve(name)
    if resolved["type"] == "stock":
        symbol = resolved["name"]
        return {
            "resolve": resolved,
            "snapshot": agent.market_snapshot(symbol, depth=depth, view=view),
            "company": agent.company_info(symbol),
        }
    return {
        "resolve": resolved,
        "macro": agent.macro_focus(resolved["name"], depth=depth, view=view),
    }


def market_snapshot(
    name: str,
    *,
    client: TerraFinAgentClient | None = None,
    depth: str = "auto",
    view: str = "daily",
    **client_kwargs: Any,
) -> dict[str, Any]:
    return _client(client, **client_kwargs).market_snapshot(name, depth=depth, view=view)


def compare_assets(
    names: Iterable[str],
    *,
    client: TerraFinAgentClient | None = None,
    depth: str = "auto",
    view: str = "daily",
    **client_kwargs: Any,
) -> dict[str, Any]:
    agent = _client(client, **client_kwargs)
    items = []
    for name in names:
        items.append(agent.market_snapshot(str(name), depth=depth, view=view))
    return {"assets": items, "count": len(items)}


def macro_context(
    name: str,
    *,
    client: TerraFinAgentClient | None = None,
    depth: str = "auto",
    view: str = "daily",
    **client_kwargs: Any,
) -> dict[str, Any]:
    return _client(client, **client_kwargs).macro_focus(name, depth=depth, view=view)


def portfolio_context(
    guru: str,
    *,
    client: TerraFinAgentClient | None = None,
    **client_kwargs: Any,
) -> dict[str, Any]:
    return _client(client, **client_kwargs).portfolio(guru)


def stock_fundamentals(
    ticker: str,
    *,
    client: TerraFinAgentClient | None = None,
    statement: str = "income",
    period: str = "annual",
    **client_kwargs: Any,
) -> dict[str, Any]:
    agent = _client(client, **client_kwargs)
    return {
        "company": agent.company_info(ticker),
        "earnings": agent.earnings(ticker),
        "financials": agent.financials(ticker, statement=statement, period=period),
    }


def bubble_analysis(
    name: str,
    *,
    client: TerraFinAgentClient | None = None,
    depth: str = "auto",
    view: str = "daily",
    **client_kwargs: Any,
) -> dict[str, Any]:
    agent = _client(client, **client_kwargs)
    return {
        "snapshot": agent.market_snapshot(name, depth=depth, view=view),
        "lppl": agent.lppl_analysis(name, depth=depth, view=view),
    }


def calendar_scan(
    *,
    year: int,
    month: int,
    categories: str | Iterable[str] | None = None,
    limit: int | None = None,
    client: TerraFinAgentClient | None = None,
    **client_kwargs: Any,
) -> dict[str, Any]:
    return _client(client, **client_kwargs).calendar_events(
        year=year,
        month=month,
        categories=categories,
        limit=limit,
    )


def open_chart(
    data_or_names: str | list[str] | TimeSeriesDataFrame | list[TimeSeriesDataFrame],
    *,
    client: TerraFinAgentClient | None = None,
    session_id: str | None = None,
    **client_kwargs: Any,
) -> dict[str, Any]:
    return _client(client, **client_kwargs).open_chart(data_or_names, session_id=session_id)
