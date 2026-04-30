"""Guru portfolio data via SEC EDGAR 13F filings.

Free, public, no API key required. Parses 13F-HR XML filings directly
from SEC EDGAR to extract institutional holdings.

Uses the shared SECClient for rate limiting, retries, and user-agent rotation.

Cache lifecycle:
    - Managed via `CacheManager.register_payload`. Sources:
        - `portfolio.index.<guru>`     (TTL 7d, namespace `guru_holdings_history`)
        - `portfolio.holdings.<cik>.<accession>` (TTL 7d, same namespace)
    - Cleared via `clear_guru_holdings_cache()` (also reachable from the
      `portfolio.cache` policy registered in `data/cache/registry.py`).
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import requests
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from TerraFin.data.cache.policy import ttl_for
from TerraFin.data.providers.corporate.cusip_resolver import resolve_cusip_to_ticker
from TerraFin.data.providers.corporate.filings.sec_edgar.filing import create_sec_client


log = logging.getLogger(__name__)

_HISTORY_NAMESPACE = "guru_holdings_history"
_HISTORY_QUARTERS = 20
_GURU_CIK_PATH = Path(__file__).with_name("guru_cik.json")
_FILING_FORMS_13F = ("13F-HR", "13F-HR/A")
_INDEX_SOURCE_PREFIX = "portfolio.index"
_HOLDINGS_SOURCE_PREFIX = "portfolio.holdings"


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
    """Parse 13F XML into aggregated holdings dict keyed by issuer name.

    Uses defusedxml to block XXE / billion-laughs entity-expansion attacks.
    Entries with missing or unparseable value/shares fields are logged and skipped
    rather than silently dropped or coerced to zero.

    Each value carries a `cusips` set so downstream code can resolve CUSIPs to
    tickers. Multiple share classes for the same issuer (e.g. GOOG/GOOGL) keep
    aggregating under the same name and the union of CUSIPs is preserved.
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
        cusip_el = entry.find(f"{prefix}cusip", ns)
        value_el = entry.find(f"{prefix}value", ns)
        shares_el = entry.find(f"{prefix}shrsOrPrnAmt/{prefix}sshPrnamt", ns)

        name = (name_el.text or "").strip() if name_el is not None else ""
        cusip = (cusip_el.text or "").strip().upper() if cusip_el is not None else ""
        value = _safe_int(value_el.text) if value_el is not None else None
        shares = _safe_int(shares_el.text) if shares_el is not None else None

        if not name or value is None or shares is None:
            skipped += 1
            continue

        if name in holdings:
            holdings[name]["value"] += value
            holdings[name]["shares"] += shares
            if cusip:
                holdings[name]["cusips"].add(cusip)
        else:
            holdings[name] = {
                "value": value,
                "shares": shares,
                "cusips": {cusip} if cusip else set(),
            }

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


def _resolve_row_ticker(cusips: set[str]) -> str | None:
    """Pick the first CUSIP that resolves via OpenFIGI, or None."""
    for cusip in sorted(cusips):
        ticker = resolve_cusip_to_ticker(cusip)
        if ticker:
            return ticker
    return None


def _build_activity(
    cur_shares: int,
    previous: dict[str, dict] | None,
    name: str,
) -> tuple[str, float]:
    if previous is not None and name in previous:
        prev_shares = previous[name]["shares"]
        if prev_shares > 0 and cur_shares != prev_shares:
            change_pct = round((cur_shares - prev_shares) / prev_shares * 100, 2)
            activity = f"Add {change_pct:.2f}%" if change_pct > 0 else f"Reduce {-change_pct:.2f}%"
            return activity, change_pct
        return "", 0.0
    if previous is not None:
        return "Buy", 0.0
    return "", 0.0


def _format_rows(
    current: dict[str, dict],
    previous: dict[str, dict] | None,
    sparklines: dict[str, list] | None = None,
) -> list[dict]:
    """Format raw holdings into display rows with share change vs previous quarter.

    Each row carries a `Ticker` column (CUSIP-resolved exchange symbol, or
    None when OpenFIGI cannot map the CUSIP — typical for closed-end funds /
    unit trusts) and a `Cusip` column (primary CUSIP, sorted picks first).
    Downstream agents must use `Ticker` (not `Stock`) when calling
    ticker-input tools like `company_info`, `earnings`, `financials`.
    `History` is a list of share counts across quarters (None where not held),
    or "-" when sparklines are not available.
    """
    total_value = sum(h["value"] for h in current.values())
    rows = []
    for name, h in sorted(current.items(), key=lambda x: -x[1]["value"]):
        pct = (h["value"] / total_value * 100) if total_value > 0 else 0
        cur_shares = h["shares"]
        cusips = h.get("cusips") or set()
        primary_cusip = sorted(cusips)[0] if cusips else None
        ticker = _resolve_row_ticker(cusips) if cusips else None
        activity, updated = _build_activity(cur_shares, previous, name)
        history = sparklines.get(name, []) if sparklines is not None else "-"
        rows.append({
            "History": history,
            "Stock": name,
            "Ticker": ticker,
            "Cusip": primary_cusip,
            "% of Portfolio": round(pct, 2),
            "Recent Activity": activity,
            "Updated": updated,
            "Shares": f"{cur_shares:,}",
            "Reported Price": f"${h['value'] / cur_shares:.2f}" if cur_shares > 0 else "-",
        })
    return rows


def _build_sparklines(raw_sequence: list[dict[str, dict]]) -> dict[str, list[int | None]]:
    """Build share sparkline for every holding across all quarters (oldest → newest)."""
    all_names = {name for quarter in raw_sequence for name in quarter}
    return {
        name: [quarter.get(name, {}).get("shares") for quarter in raw_sequence]
        for name in all_names
    }


def _index_source(guru_name: str) -> str:
    return f"{_INDEX_SOURCE_PREFIX}.{guru_name}"


def _holdings_source(cik: int, accession: str) -> str:
    return f"{_HOLDINGS_SOURCE_PREFIX}.{cik}.{accession}"


def _ensure_index_registered(guru_name: str, cik: int) -> str:
    from TerraFin.data.cache.manager import CachePayloadSpec
    from TerraFin.data.cache.registry import get_cache_manager

    source = _index_source(guru_name)
    manager = get_cache_manager()
    if source not in manager._payload_specs:
        manager.register_payload(
            CachePayloadSpec(
                source=source,
                namespace=_HISTORY_NAMESPACE,
                key=f"{guru_name}__index",
                ttl_seconds=ttl_for("portfolio.index"),
                fetch_fn=lambda c=cik: [
                    {"accession": acc, "filing_date": fd}
                    for acc, fd in _find_latest_13f(c, count=_HISTORY_QUARTERS)
                ],
            )
        )
    return source


def _ensure_holdings_registered(cik: int, accession: str, filing_date: str, guru_name: str) -> str:
    from TerraFin.data.cache.manager import CachePayloadSpec
    from TerraFin.data.cache.registry import get_cache_manager

    source = _holdings_source(cik, accession)
    manager = get_cache_manager()
    if source not in manager._payload_specs:
        manager.register_payload(
            CachePayloadSpec(
                source=source,
                namespace=_HISTORY_NAMESPACE,
                key=f"{guru_name}__{filing_date}__raw",
                ttl_seconds=ttl_for("portfolio.holdings"),
                fetch_fn=lambda c=cik, a=accession: {
                    name: {**h, "cusips": sorted(h["cusips"])}
                    for name, h in _fetch_holdings_raw(c, a).items()
                },
            )
        )
    return source


def _fetch_or_cached_raw(cik: int, guru_name: str, accession: str, filing_date: str) -> dict[str, dict]:
    """Fetch raw holdings for a filing via the managed cache. cusips deserialized to set."""
    from TerraFin.data.cache.registry import get_cache_manager

    source = _ensure_holdings_registered(cik, accession, filing_date, guru_name)
    payload = get_cache_manager().get_payload(source).payload
    if not isinstance(payload, dict):
        return {}
    return {name: {**h, "cusips": set(h.get("cusips") or [])} for name, h in payload.items()}


def get_guru_filings_index(guru_name: str) -> list[dict]:
    """Return the filing index for a guru without fetching any XML.

    Each entry: {filing_date, period, accession}. Safe to call on every guru
    selection — triggers only one SEC EDGAR submissions.json request (cached 7d).
    """
    if guru_name not in GURU_CIK:
        raise ValueError(f"Unknown guru: {guru_name}. Available: {list(GURU_CIK.keys())}")

    from TerraFin.data.cache.registry import get_cache_manager

    cik = GURU_CIK[guru_name]
    source = _ensure_index_registered(guru_name, cik)
    filings_index = get_cache_manager().get_payload(source).payload or []

    result = []
    for entry in filings_index:
        filing_date = entry["filing_date"]
        try:
            d = datetime.strptime(filing_date, "%Y-%m-%d")
            period = f"Q{(d.month - 1) // 3 + 1} {d.year}"
        except ValueError:
            period = filing_date
        result.append({"filing_date": filing_date, "period": period, "accession": entry["accession"]})
    return result


def get_guru_holdings_for_date(guru_name: str, filing_date: str) -> tuple[dict, list[dict]]:
    """Fetch holdings for a specific filing date. Downloads exactly 2 XMLs (target + previous quarter).

    Uses the cached index to locate accession numbers without re-hitting EDGAR.
    """
    if guru_name not in GURU_CIK:
        raise ValueError(f"Unknown guru: {guru_name}. Available: {list(GURU_CIK.keys())}")

    from TerraFin.data.cache.registry import get_cache_manager

    cik = GURU_CIK[guru_name]
    source = _ensure_index_registered(guru_name, cik)
    filings_index = get_cache_manager().get_payload(source).payload or []

    target_idx = next((i for i, e in enumerate(filings_index) if e["filing_date"] == filing_date), None)
    if target_idx is None:
        raise ValueError(f"No 13F filing found for {guru_name} on {filing_date}")

    entry = filings_index[target_idx]
    raw = _fetch_or_cached_raw(cik, guru_name, entry["accession"], filing_date)

    previous: dict[str, dict] | None = None
    if target_idx + 1 < len(filings_index):
        prev_entry = filings_index[target_idx + 1]
        try:
            previous = _fetch_or_cached_raw(cik, guru_name, prev_entry["accession"], prev_entry["filing_date"])
        except (requests.RequestException, ValueError) as exc:
            log.warning("Failed to fetch previous quarter for %s: %s; activity blank", guru_name, exc)

    try:
        d = datetime.strptime(filing_date, "%Y-%m-%d")
        period = f"Q{(d.month - 1) // 3 + 1} {d.year}"
    except ValueError:
        period = filing_date

    source_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=13F"
    info = {"Period": period, "Portfolio Date": filing_date, "Source": source_url}
    rows = _format_rows(raw, previous)
    return info, rows


def get_guru_holdings_history(guru_name: str) -> list[dict]:
    """Fetch up to _HISTORY_QUARTERS 13F filings for a guru.

    Returns a list of filing dicts, newest first. Each dict has:
        filing_date, period, accession, info, rows
    where rows[*]["History"] is a list of share counts across all fetched
    quarters (oldest → newest), None where the holding was absent.
    """
    if guru_name not in GURU_CIK:
        raise ValueError(f"Unknown guru: {guru_name}. Available: {list(GURU_CIK.keys())}")

    from TerraFin.data.cache.registry import get_cache_manager

    cik = GURU_CIK[guru_name]
    source = _ensure_index_registered(guru_name, cik)
    filings_index = get_cache_manager().get_payload(source).payload

    if not filings_index:
        return []

    # Fetch raw holdings oldest → newest for sparkline alignment
    all_raw: list[tuple[dict, str, str, str]] = []
    for entry in reversed(filings_index):
        accession = entry["accession"]
        filing_date = entry["filing_date"]
        try:
            raw = _fetch_or_cached_raw(cik, guru_name, accession, filing_date)
        except (requests.RequestException, ValueError, DefusedXmlException) as exc:
            log.warning("Failed to fetch 13F for %s/%s: %s; using empty", guru_name, filing_date, exc)
            raw = {}
        try:
            d = datetime.strptime(filing_date, "%Y-%m-%d")
            period = f"Q{(d.month - 1) // 3 + 1} {d.year}"
        except ValueError:
            period = filing_date
        all_raw.append((raw, accession, filing_date, period))

    # Build sparklines across all quarters
    sparklines = _build_sparklines([r for r, _, _, _ in all_raw])
    source_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=13F"

    # Build result newest → oldest
    result = []
    for idx in range(len(all_raw) - 1, -1, -1):
        raw, accession, filing_date, period = all_raw[idx]
        previous = all_raw[idx - 1][0] if idx > 0 else None
        rows = _format_rows(raw, previous, sparklines)
        info = {"Period": period, "Portfolio Date": filing_date, "Source": source_url}
        result.append({
            "filing_date": filing_date,
            "period": period,
            "accession": accession,
            "info": info,
            "rows": rows,
        })

    return result


def get_guru_holdings(guru_name: str) -> tuple[dict, list[dict]]:
    """Get holdings for a known guru from SEC EDGAR 13F. Returns (info, rows) for latest filing.

    Fetches 2 filings (latest + previous quarter) for activity diff and color rendering.
    Both XMLs are cached (TTL 7d) so subsequent calls are instant.
    """
    if guru_name not in GURU_CIK:
        raise ValueError(f"Unknown guru: {guru_name}. Available: {list(GURU_CIK.keys())}")

    from TerraFin.data.cache.manager import CacheManager

    cik = GURU_CIK[guru_name]

    cached_index = CacheManager.file_cache_read(
        _HISTORY_NAMESPACE, f"{guru_name}__index", ttl_for("portfolio.index")
    )
    if cached_index and len(cached_index) >= 1:
        entries = [(e["accession"], e["filing_date"]) for e in cached_index[:2]]
    else:
        entries = _find_latest_13f(cik, count=2)

    accession, filing_date = entries[0]
    raw = _fetch_or_cached_raw(cik, guru_name, accession, filing_date)

    previous: dict[str, dict] | None = None
    if len(entries) >= 2:
        prev_accession, prev_filing_date = entries[1]
        try:
            previous = _fetch_or_cached_raw(cik, guru_name, prev_accession, prev_filing_date)
        except (requests.RequestException, ValueError) as exc:
            log.warning("Failed to fetch previous quarter for %s: %s; activity blank", guru_name, exc)

    try:
        d = datetime.strptime(filing_date, "%Y-%m-%d")
        period = f"Q{(d.month - 1) // 3 + 1} {d.year}"
    except ValueError:
        period = filing_date

    source_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=13F"
    info = {"Period": period, "Portfolio Date": filing_date, "Source": source_url}
    rows = _format_rows(raw, previous)
    return info, rows


def clear_guru_holdings_cache() -> None:
    """Clear all managed portfolio payload sources and the on-disk namespace."""
    from TerraFin.data.cache.manager import CacheManager
    from TerraFin.data.cache.registry import get_cache_manager

    manager = get_cache_manager()
    for source in list(manager._payload_specs):
        if source.startswith(_INDEX_SOURCE_PREFIX + ".") or source.startswith(_HOLDINGS_SOURCE_PREFIX + "."):
            manager.clear_payload(source)
    CacheManager.file_cache_clear(_HISTORY_NAMESPACE)


clear_portfolio_cache = clear_guru_holdings_cache


def get_available_gurus() -> list[str]:
    return sorted(GURU_CIK.keys())


if __name__ == "__main__":
    info, rows = get_guru_holdings("Warren Buffett")
    print(info)
    print(rows)
