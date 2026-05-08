"""Weekly report generation job.

Generates a report for the most recently completed Friday on boot (if none
exists), then fires every Friday at 16:30 ET.

Disable with ``TERRAFIN_WEEKLY_REPORT_ENABLED=0``.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)


def _ensure_recent_report() -> None:
    from TerraFin.analytics.reports import list_reports
    from TerraFin.analytics.reports.weekly import _last_completed_friday, build_weekly_report

    target = _last_completed_friday()
    existing = list_reports(limit=8)
    if any(r.as_of == target.isoformat() for r in existing):
        return
    build_weekly_report(as_of=target)


async def run() -> None:
    if os.environ.get("TERRAFIN_WEEKLY_REPORT_ENABLED", "1") in ("0", "false", "False"):
        log.info("weekly-report: disabled via env, exiting")
        return

    loop = asyncio.get_running_loop()
    tz = ZoneInfo(os.environ.get("TERRAFIN_CACHE_TIMEZONE", "America/New_York"))

    log.info("weekly-report: scheduler enabled (Fri 16:30 ET)")

    try:
        await loop.run_in_executor(None, _ensure_recent_report)
    except Exception:
        log.exception("weekly-report: boot generation failed")

    while True:
        try:
            now = datetime.now(tz)
            days_ahead = (4 - now.weekday()) % 7
            target = now.replace(hour=16, minute=30, second=0, microsecond=0)
            if days_ahead == 0 and now >= target:
                days_ahead = 7
            target = target + timedelta(days=days_ahead)
            wait = (target - now).total_seconds()
            log.info("weekly-report: next run at %s (%.0fs)", target.isoformat(), wait)
            await asyncio.sleep(wait)
            from TerraFin.analytics.reports.weekly import build_weekly_report
            await loop.run_in_executor(None, build_weekly_report)
            log.info("weekly-report: generated")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("weekly-report: generation failed, retrying next cycle")
