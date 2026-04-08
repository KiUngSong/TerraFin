import argparse
import json
import sys
from typing import Any

from TerraFin.env import load_entrypoint_dotenv

from .client import TerraFinAgentClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="terrafin-agent")
    parser.add_argument("--transport", default="auto", choices=["auto", "python", "http"])
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", help="Emit compact JSON on stdout.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("query")

    market_data_parser = subparsers.add_parser("market-data")
    market_data_parser.add_argument("name")
    market_data_parser.add_argument("--depth", default="auto", choices=["auto", "recent", "full"])
    market_data_parser.add_argument("--view", default="daily", choices=["daily", "weekly", "monthly", "yearly"])

    indicators_parser = subparsers.add_parser("indicators")
    indicators_parser.add_argument("name")
    indicators_parser.add_argument("--indicators", required=True)
    indicators_parser.add_argument("--depth", default="auto", choices=["auto", "recent", "full"])
    indicators_parser.add_argument("--view", default="daily", choices=["daily", "weekly", "monthly", "yearly"])

    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("name")
    snapshot_parser.add_argument("--depth", default="auto", choices=["auto", "recent", "full"])
    snapshot_parser.add_argument("--view", default="daily", choices=["daily", "weekly", "monthly", "yearly"])

    economic_parser = subparsers.add_parser("economic")
    economic_parser.add_argument("--indicators", required=True)

    portfolio_parser = subparsers.add_parser("portfolio")
    portfolio_parser.add_argument("guru")

    company_parser = subparsers.add_parser("company")
    company_parser.add_argument("ticker")

    earnings_parser = subparsers.add_parser("earnings")
    earnings_parser.add_argument("ticker")

    financials_parser = subparsers.add_parser("financials")
    financials_parser.add_argument("ticker")
    financials_parser.add_argument("--statement", default="income", choices=["income", "balance", "cashflow"])
    financials_parser.add_argument("--period", default="annual", choices=["annual", "quarter"])

    macro_parser = subparsers.add_parser("macro-focus")
    macro_parser.add_argument("name")
    macro_parser.add_argument("--depth", default="auto", choices=["auto", "recent", "full"])
    macro_parser.add_argument("--view", default="daily", choices=["daily", "weekly", "monthly", "yearly"])

    lppl_parser = subparsers.add_parser("lppl")
    lppl_parser.add_argument("name")
    lppl_parser.add_argument("--depth", default="auto", choices=["auto", "recent", "full"])
    lppl_parser.add_argument("--view", default="daily", choices=["daily", "weekly", "monthly", "yearly"])

    calendar_parser = subparsers.add_parser("calendar")
    calendar_parser.add_argument("--year", type=int, required=True)
    calendar_parser.add_argument("--month", type=int, required=True)
    calendar_parser.add_argument("--categories", default=None)
    calendar_parser.add_argument("--limit", type=int, default=None)

    open_chart_parser = subparsers.add_parser("open-chart")
    open_chart_parser.add_argument("names", nargs="+")
    open_chart_parser.add_argument("--session-id", default=None)

    return parser


def _make_client(args: argparse.Namespace) -> TerraFinAgentClient:
    return TerraFinAgentClient(
        transport=args.transport,
        base_url=args.base_url,
        timeout=args.timeout,
    )


def _emit(payload: dict[str, Any], *, compact: bool) -> None:
    if compact:
        print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    load_entrypoint_dotenv()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        client = _make_client(args)
        if args.command == "resolve":
            payload = client.resolve(args.query)
        elif args.command == "market-data":
            payload = client.market_data(args.name, depth=args.depth, view=args.view)
        elif args.command == "indicators":
            payload = client.indicators(args.name, args.indicators, depth=args.depth, view=args.view)
        elif args.command == "snapshot":
            payload = client.market_snapshot(args.name, depth=args.depth, view=args.view)
        elif args.command == "economic":
            payload = client.economic(args.indicators)
        elif args.command == "portfolio":
            payload = client.portfolio(args.guru)
        elif args.command == "company":
            payload = client.company_info(args.ticker)
        elif args.command == "earnings":
            payload = client.earnings(args.ticker)
        elif args.command == "financials":
            payload = client.financials(args.ticker, statement=args.statement, period=args.period)
        elif args.command == "lppl":
            payload = client.lppl_analysis(args.name, depth=args.depth, view=args.view)
        elif args.command == "macro-focus":
            payload = client.macro_focus(args.name, depth=args.depth, view=args.view)
        elif args.command == "calendar":
            payload = client.calendar_events(
                year=args.year,
                month=args.month,
                categories=args.categories,
                limit=args.limit,
            )
        elif args.command == "open-chart":
            payload = client.open_chart(args.names, session_id=args.session_id)
        else:  # pragma: no cover - argparse keeps this unreachable
            raise RuntimeError(f"Unknown command: {args.command}")
        _emit(payload, compact=args.json)
        return 0
    except Exception as exc:
        message = {"error": str(exc)}
        if args.json:
            print(json.dumps(message, separators=(",", ":"), ensure_ascii=False), file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
