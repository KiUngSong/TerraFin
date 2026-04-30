"""CLI entry point for the TerraFin alerting engine.

Usage:
    terrafin-signals scan [--group GROUP] [--out PATH]
    terrafin-signals weekly [--group GROUP] [--out PATH]
    terrafin-signals run [--group GROUP] [--interval SECONDS]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _cmd_scan(args: argparse.Namespace) -> None:
    from TerraFin.signals.alerting.notify import get_channel_from_env
    from TerraFin.signals.alerting.scanner import scan

    signals = scan(group=args.group or None)
    payload = {
        "signals": [
            {
                "name": s.name,
                "ticker": s.ticker,
                "severity": s.severity,
                "message": s.message,
                "snapshot": s.snapshot,
            }
            for s in signals
        ],
        "total": len(signals),
    }
    title = f"TerraFin Alerts — {len(signals)} signal(s)"
    body = "\n".join(f"[{s.severity.upper()}] {s.ticker} {s.name}: {s.message}" for s in signals) or "No signals."

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))
        print(f"Wrote {len(signals)} signal(s) to {path}")
    else:
        channel = get_channel_from_env()
        channel.send(title, body, payload)


def _cmd_weekly(args: argparse.Namespace) -> None:
    from datetime import date
    from TerraFin.signals.alerting.notify import get_channel_from_env
    from TerraFin.signals.reports.weekly import build_weekly_report

    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    md = build_weekly_report(as_of=as_of)

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(md)
        print(f"Wrote weekly report to {path}")
    else:
        channel = get_channel_from_env()
        title = f"TerraFin Weekly — {(as_of or date.today()).isoformat()}"
        channel.send(title, md, {"markdown": md})


def _cmd_telegram(args: argparse.Namespace) -> None:
    from TerraFin.signals.channels.telegram import cmd_pair, cmd_setup, cmd_test

    if args.tg_command == "setup":
        cmd_setup(args.token)
    elif args.tg_command == "pair":
        cmd_pair()
    elif args.tg_command == "test":
        cmd_test()


def _cmd_run(args: argparse.Namespace) -> None:
    import logging
    import time

    from TerraFin.signals.alerting.dedup import deduplicate
    from TerraFin.signals.alerting.notify import get_channel_from_env
    from TerraFin.signals.alerting.scanner import scan

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger(__name__)
    channel = get_channel_from_env()
    group = args.group or None
    interval = args.interval

    log.info("TerraFin alerting runner started (interval=%ds, group=%s)", interval, group or "all")
    while True:
        try:
            signals = scan(group=group)
            fired = deduplicate(signals)
            if fired:
                payload = {
                    "signals": [
                        {"name": s.name, "ticker": s.ticker, "severity": s.severity,
                         "message": s.message, "snapshot": s.snapshot}
                        for s in fired
                    ],
                    "total": len(fired),
                }
                title = f"TerraFin Alerts — {len(fired)} signal(s)"
                body = "\n".join(
                    f"[{s.severity.upper()}] {s.ticker} {s.name}: {s.message}" for s in fired
                )
                channel.send(title, body, payload)
                log.info("Sent %d signal(s)", len(fired))
            else:
                log.debug("Scan complete — no new signals")
        except Exception:
            log.exception("Scan error (will retry in %ds)", interval)
        time.sleep(interval)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="terrafin-signals")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="Scan watchlist for technical signals")
    scan_p.add_argument("--group", default=None, help="Filter by group/tag")
    scan_p.add_argument("--out", default=None, help="Write JSON artifact to path")

    weekly_p = sub.add_parser("weekly", help="Generate weekly watchlist report")
    weekly_p.add_argument("--as-of", dest="as_of", default=None, help="Anchor date YYYY-MM-DD (default: today)")
    weekly_p.add_argument("--out", default=None, help="Write report to path (default: send to channel)")

    run_p = sub.add_parser("run", help="Continuous local runner — scan on interval and notify")
    run_p.add_argument("--group", default=None, help="Filter by group/tag")
    run_p.add_argument("--interval", type=int, default=300, help="Scan interval in seconds (default: 300)")

    tg_p = sub.add_parser("telegram", help="Telegram channel setup")
    tg_sub = tg_p.add_subparsers(dest="tg_command", required=True)

    tg_setup = tg_sub.add_parser("setup", help="Save BotFather token")
    tg_setup.add_argument("token", help="Token from @BotFather (e.g. 123456789:AAH...)")

    tg_sub.add_parser("pair", help="Wait for user DM to capture chat_id")
    tg_sub.add_parser("test", help="Send a test alert message")

    args = parser.parse_args(argv)
    if args.command == "scan":
        _cmd_scan(args)
    elif args.command == "weekly":
        _cmd_weekly(args)
    elif args.command == "run":
        _cmd_run(args)
    elif args.command == "telegram":
        _cmd_telegram(args)


if __name__ == "__main__":
    main()
