"""CLI entry point for the TerraFin signals scanner.

Usage::

    terrafin-signals [--group GROUP] [--json]
    terrafin-alerting [--group GROUP] [--json]   # legacy alias

Scans every ticker in the watchlist for pattern signals using
``TerraFin.analytics.reports.scanner.scan`` and prints the results.
"""

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="terrafin-signals",
        description="Scan the watchlist for pattern signals.",
    )
    parser.add_argument(
        "--group",
        default=None,
        metavar="GROUP",
        help="Watchlist group to scan (default: all groups).",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Output results as JSON.",
    )
    args = parser.parse_args()

    from TerraFin.env import load_entrypoint_dotenv

    load_entrypoint_dotenv()

    from TerraFin.analytics.reports.scanner import scan

    try:
        signals = scan(group=args.group)
    except Exception as exc:
        print(f"Scan failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not signals:
        print("No signals detected.")
        return

    if args.as_json:
        print(
            json.dumps(
                [
                    {
                        "ticker": s.ticker,
                        "name": s.name,
                        "severity": s.severity,
                        "message": s.message,
                    }
                    for s in signals
                ],
                indent=2,
            )
        )
    else:
        for s in signals:
            print(f"{s.ticker:<8}  [{s.severity:<6}]  {s.name:<30}  {s.message}")


if __name__ == "__main__":
    main()
