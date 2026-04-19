"""Guru portfolio data via SEC EDGAR 13F filings.

Free, public, no API key required. Parses 13F-HR XML filings directly
from SEC EDGAR to extract institutional holdings.

Uses the shared SECClient for rate limiting, retries, and user-agent rotation.

Cache lifecycle:
    - CacheManager policy source:    `portfolio.cache` (see `data/cache/policy.py`)
    - On-disk file-cache namespace:  `guru_holdings` (separate from `sec_filings`)
    - Cleared independently via `clear_guru_holdings_cache()`; not affected by
      `clear_sec_filings_cache()`.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import requests
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from TerraFin.data.providers.corporate.filings.sec_edgar.filing import create_sec_client


log = logging.getLogger(__name__)

_CACHE_NAMESPACE = "guru_holdings"
_CACHE_MAX_SECONDS = 7 * 86400  # 1 week
_GURU_CIK_PATH = Path(__file__).with_name("guru_cik.json")
_FILING_FORMS_13F = ("13F-HR", "13F-HR/A")


def load_guru_cik_registry(path: Path | None = None) -> dict[str, int]:
    """Load the supported guru-to-CIK registry from JSON."""
    payload = json.loads((path or _GURU_CIK_PATH).read_text(encoding="utf-8"))
    gurus = payload.get("gurus")
    if not isinstance(gurus, list):
        raise ValueError("Guru registry must contain a 'gurus' list.")

    registry: dict[str, int] = {}
    for index, row in enumerate(gurus):
        if not isinstance(row, dict):
            raise ValueError(f"Guru registry entry {index} must be a JSON object.")

        name = str(row.get("name", "")).strip()
        cik = row.get("cik")

        if not name:
            raise ValueError(f"Guru registry entry {index} must include a non-empty 'name'.")
        if name in registry:
            raise ValueError(f"Duplicate guru name in registry: {name}.")
        if not isinstance(cik, int) or cik <= 0:
            raise ValueError(f"Guru registry entry '{name}' must include a positive integer 'cik'.")

        registry[name] = cik

    if not registry:
        raise ValueError("Guru registry must contain at least one guru entry.")

    return registry


GURU_CIK = load_guru_cik_registry()


def _get_sec_json(url: str, host_url: str = "data.sec.gov") -> dict:
    """GET a SEC JSON endpoint with explicit HTTP + JSON error handling."""
    client = create_sec_client(host_url=host_url)
    response = client.get(url)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise ValueError(f"SEC EDGAR returned non-JSON response for {url}") from exc


def _iter_13f_from_block(block: dict) -> list[tuple[str, str]]:
    """Extract (accession, filing_date) pairs from a submissions block."""
    forms = block.get("form") or []
    accessions = block.get("accessionNumber") or []
    dates = block.get("filingDate") or []
    # SEC JSON blocks keep parallel arrays; truncate to the shortest length to
    # stay safe if the upstream response is ever malformed.
    n = min(len(forms), len(accessions), len(dates))
    if n < max(len(forms), len(accessions), len(dates)):
        log.warning("SEC submissions block has misaligned column lengths; truncating to %d rows", n)
    return [(accessions[i], dates[i]) for i in range(n) if forms[i] in _FILING_FORMS_13F]


def _find_latest_13f(cik: int, count: int = 1) -> list[tuple[str, str]]:
    """Find the latest *count* 13F-HR filings. Returns [(accession, filing_date), ...].

    Searches the `recent` block first and falls back to paginated history files
    only when recent yields fewer than *count* hits (rare for active filers).
    """
    url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"
    data = _get_sec_json(url)

    filings = data.get("filings", {})
    results = _iter_13f_from_block(filings.get("recent", {}))

    if len(results) < count:
        for file_info in filings.get("files", []) or []:
            name = file_info.get("name")
            if not name:
                continue
            try:
                history = _get_sec_json(f"https://data.sec.gov/submissions/{name}")
            except (requests.RequestException, ValueError) as exc:
                log.warning("Failed to load historical submissions file %s for CIK %s: %s", name, cik, exc)
                continue
            results.extend(_iter_13f_from_block(history))
            if len(results) >= count:
                break

    if not results:
        raise ValueError(f"No 13F filing found for CIK {cik}")
    return results[:count]


def _find_infotable_url(cik: int, accession: str) -> str:
    """Find the information table XML URL from the filing index."""
    cik_num = str(cik)
    acc_clean = accession.replace("-", "")
    idx = _get_sec_json(
        f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_clean}/index.json",
        host_url="www.sec.gov",
    )

    items = (idx.get("directory") or {}).get("item") or []
    for item in items:
        name = item.get("name", "")
        if name.endswith(".xml") and name != "primary_doc.xml":
            return f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_clean}/{name}"

    raise ValueError(f"No infotable XML found in filing {accession}")


def _safe_int(text: str | None) -> int | None:
    """Parse an int from XML text; return None on missing or non-numeric input."""
    if text is None:
        return None
    try:
        return int(text.strip())
    except (TypeError, ValueError):
        return None


def _parse_13f_xml(xml_text: str) -> dict[str, dict]:
    """Parse 13F XML into aggregated holdings dict: name → {value, shares}.

    Uses defusedxml to block XXE / billion-laughs entity-expansion attacks.
    Entries with missing or unparseable value/shares fields are logged and skipped
    rather than silently dropped or coerced to zero.
    """
    try:
        root = ET.fromstring(xml_text)
    except DefusedXmlException:
        raise
    except ET.ParseError as exc:
        raise ValueError("Malformed 13F XML payload") from exc

    ns_match = root.tag.split("}")[0] + "}" if "}" in root.tag else ""
    ns = {"ns": ns_match.strip("{}")} if ns_match else {}
    prefix = "ns:" if ns else ""

    holdings: dict[str, dict] = {}
    skipped = 0
    for entry in root.findall(f"{prefix}infoTable", ns):
        name_el = entry.find(f"{prefix}nameOfIssuer", ns)
        value_el = entry.find(f"{prefix}value", ns)
        shares_el = entry.find(f"{prefix}shrsOrPrnAmt/{prefix}sshPrnamt", ns)

        name = (name_el.text or "").strip() if name_el is not None else ""
        value = _safe_int(value_el.text) if value_el is not None else None
        shares = _safe_int(shares_el.text) if shares_el is not None else None

        if not name or value is None or shares is None:
            skipped += 1
            continue

        if name in holdings:
            holdings[name]["value"] += value
            holdings[name]["shares"] += shares
        else:
            holdings[name] = {"value": value, "shares": shares}

    if skipped:
        log.warning("Skipped %d malformed 13F infoTable entries", skipped)
    return holdings


def _fetch_holdings_raw(cik: int, accession: str) -> dict[str, dict]:
    """Fetch and parse a single 13F filing into raw holdings dict."""
    infotable_url = _find_infotable_url(cik, accession)
    client = create_sec_client(host_url="www.sec.gov")
    response = client.get(infotable_url)
    response.raise_for_status()
    xml_text = response.content.decode("utf-8")
    return _parse_13f_xml(xml_text)


def _format_rows(
    current: dict[str, dict],
    previous: dict[str, dict] | None,
) -> list[dict]:
    """Format raw holdings into display rows with share change vs previous quarter."""
    total_value = sum(h["value"] for h in current.values())

    rows = []
    for name, h in sorted(current.items(), key=lambda x: -x[1]["value"]):
        pct = (h["value"] / total_value * 100) if total_value > 0 else 0
        cur_shares = h["shares"]

        # Compute activity vs previous quarter
        if previous is not None and name in previous:
            prev_shares = previous[name]["shares"]
            if prev_shares > 0 and cur_shares != prev_shares:
                change_pct = round((cur_shares - prev_shares) / prev_shares * 100, 2)
                if change_pct > 0:
                    activity = f"Add {change_pct:.2f}%"
                else:
                    activity = f"Reduce {-change_pct:.2f}%"
                updated = change_pct
            else:
                activity = ""
                updated = 0.0
        elif previous is not None:
            # New position (not in previous quarter)
            activity = "Buy"
            updated = 0.0
        else:
            activity = ""
            updated = 0.0

        rows.append({
            "History": "-",
            "Stock": name,
            "% of Portfolio": round(pct, 2),
            "Recent Activity": activity,
            "Updated": updated,
            "Shares": f"{cur_shares:,}",
            "Reported Price": f"${h['value'] / cur_shares:.2f}" if cur_shares > 0 else "-",
        })

    return rows


def get_guru_holdings(guru_name: str) -> tuple[dict, list[dict]]:
    """Get holdings for a known guru from SEC EDGAR 13F. Uses file cache."""
    if guru_name not in GURU_CIK:
        raise ValueError(f"Unknown guru: {guru_name}. Available: {list(GURU_CIK.keys())}")

    # Check file cache (lazy import to avoid circular dependency)
    from TerraFin.data.cache.manager import CacheManager

    cached = CacheManager.file_cache_read(_CACHE_NAMESPACE, guru_name, _CACHE_MAX_SECONDS)
    if cached is not None:
        return cached["info"], cached["rows"]

    # Fetch latest two 13F filings from SEC EDGAR
    cik = GURU_CIK[guru_name]
    filings = _find_latest_13f(cik, count=2)

    accession, filing_date = filings[0]
    current = _fetch_holdings_raw(cik, accession)

    previous = None
    if len(filings) >= 2:
        try:
            previous = _fetch_holdings_raw(cik, filings[1][0])
        except (requests.RequestException, ValueError, DefusedXmlException) as exc:
            log.warning("Prior-quarter 13F fetch failed for CIK %s (%s); skipping comparison", cik, exc)

    rows = _format_rows(current, previous)

    # Build info
    try:
        d = datetime.strptime(filing_date, "%Y-%m-%d")
        period = f"Q{(d.month - 1) // 3 + 1} {d.year}"
    except ValueError:
        log.warning("Unexpected SEC filing_date format %r; using raw value", filing_date)
        period = filing_date

    info = {
        "Period": period,
        "Portfolio Date": filing_date,
        "Source": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=13F",
    }

    # Write to file cache
    CacheManager.file_cache_write(_CACHE_NAMESPACE, guru_name, {"info": info, "rows": rows})

    return info, rows


def clear_guru_holdings_cache() -> None:
    """Clear the shared file cache namespace for guru holdings."""
    from TerraFin.data.cache.manager import CacheManager

    CacheManager.file_cache_clear(_CACHE_NAMESPACE)


def get_available_gurus() -> list[str]:
    return sorted(GURU_CIK.keys())


if __name__ == "__main__":
    info, rows = get_guru_holdings("Warren Buffett")
    print(info)
    print(rows)
