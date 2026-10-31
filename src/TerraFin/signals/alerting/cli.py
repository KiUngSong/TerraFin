"""CLI entry point for the TerraFin signals scanner.

Usage::

    terrafin-signals [--group GROUP] [--json]
    terrafin-signals telegram setup <token> | pair | test
    terrafin-alerting ...   # legacy alias

With no subcommand, scans every ticker in the watchlist for pattern signals
using ``TerraFin.analytics.reports.scanner.scan`` and prints the results.
``telegram`` saves the bot token, pairs a chat, and sends a test message.
"""

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="terrafin-signals",
        description="Scan the watchlist for pattern signals, or set up Telegram.",
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
    sub = parser.add_subparsers(dest="command")
    tg_parser = sub.add_parser("telegram", help="Set up the Telegram channel.")
    tg_sub = tg_parser.add_subparsers(dest="tg_command", required=True)
    tg_setup = tg_sub.add_parser("setup", help="Save the BotFather token.")
    tg_setup.add_argument("token", help="Token from @BotFather (e.g. 123456789:AAH...).")
    tg_sub.add_parser("pair", help="Wait for a DM to the bot and save its chat_id.")
    tg_sub.add_parser("test", help="Send a test message.")
    args = parser.parse_args()

    if args.command == "telegram":
        from TerraFin.interface.infra.channels.telegram import cmd_pair, cmd_setup, cmd_test, redact_token

        try:
            if args.tg_command == "setup":
                cmd_setup(args.token)
            elif args.tg_command == "pair":
                cmd_pair()
            else:
                cmd_test()
        except Exception as exc:
            print(f"telegram {args.tg_command} failed: {redact_token(str(exc))}", file=sys.stderr)
            sys.exit(1)
        return

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
