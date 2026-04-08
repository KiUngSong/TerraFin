"""Guru portfolio data via SEC EDGAR 13F filings.

Free, public, no API key required. Parses 13F-HR XML filings directly
from SEC EDGAR to extract institutional holdings.

Uses the shared SECClient for rate limiting, retries, and user-agent rotation.
Cache: managed by CacheManager file cache (7-day TTL).
"""

import json
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from TerraFin.data.providers.corporate.filings.sec_edgar.filing import create_sec_client


_CACHE_NAMESPACE = "guru_holdings"
_CACHE_MAX_SECONDS = 7 * 86400  # 1 week
_GURU_CIK_PATH = Path(__file__).with_name("guru_cik.json")


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


def _find_latest_13f(cik: int, count: int = 1) -> list[tuple[str, str]]:
    """Find the latest *count* 13F-HR filings. Returns [(accession, filing_date), ...]."""
    client = create_sec_client()
    url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"
    data = client.get(url).json()

    results: list[tuple[str, str]] = []
    filings = data["filings"]["recent"]
    for i in range(len(filings["form"])):
        if filings["form"][i] in ("13F-HR", "13F-HR/A"):
            results.append((filings["accessionNumber"][i], filings["filingDate"][i]))
            if len(results) >= count:
                break
    if not results:
        raise ValueError(f"No 13F filing found for CIK {cik}")
    return results


def _find_infotable_url(cik: int, accession: str) -> str:
    """Find the information table XML URL from the filing index."""
    cik_num = str(cik)
    acc_clean = accession.replace("-", "")
    client = create_sec_client(host_url="www.sec.gov")
    idx = client.get(f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_clean}/index.json").json()

    for item in idx["directory"]["item"]:
        name = item["name"]
        if name.endswith(".xml") and name != "primary_doc.xml":
            return f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_clean}/{name}"

    raise ValueError(f"No infotable XML found in filing {accession}")


def _parse_13f_xml(xml_text: str) -> dict[str, dict]:
    """Parse 13F XML into aggregated holdings dict: name → {value, shares}."""
    root = ET.fromstring(xml_text)

    ns_match = root.tag.split("}")[0] + "}" if "}" in root.tag else ""
    ns = {"ns": ns_match.strip("{}")} if ns_match else {}
    prefix = "ns:" if ns else ""

    holdings: dict[str, dict] = {}
    for entry in root.findall(f"{prefix}infoTable", ns):
        name_el = entry.find(f"{prefix}nameOfIssuer", ns)
        value_el = entry.find(f"{prefix}value", ns)
        shares_el = entry.find(f"{prefix}shrsOrPrnAmt/{prefix}sshPrnamt", ns)

        if name_el is None or value_el is None or shares_el is None:
            continue

        name = name_el.text or ""
        value = int(value_el.text or "0")
        shares = int(shares_el.text or "0")

        if name in holdings:
            holdings[name]["value"] += value
            holdings[name]["shares"] += shares
        else:
            holdings[name] = {"value": value, "shares": shares}

    return holdings


def _fetch_holdings_raw(cik: int, accession: str) -> dict[str, dict]:
    """Fetch and parse a single 13F filing into raw holdings dict."""
    infotable_url = _find_infotable_url(cik, accession)
    client = create_sec_client(host_url="www.sec.gov")
    xml_text = client.get(infotable_url).content.decode("utf-8")
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
        except Exception:
            pass

    rows = _format_rows(current, previous)

    # Build info
    try:
        d = datetime.strptime(filing_date, "%Y-%m-%d")
        period = f"Q{(d.month - 1) // 3 + 1} {d.year}"
    except Exception:
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
