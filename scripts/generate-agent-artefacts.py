"""Regenerate agent-surface documentation from the capability registry.

The capability list lives in `src/TerraFin/agent/runtime.py` (the
`build_default_capability_registry()` function). All downstream artefacts
that mirror the public agent surface — `skills/terrafin/SKILL.md`'s "Key
client methods" section and `docs/agent/usage.md`'s "Route summary" —
should be derived from that single source. This script does the derivation.

Usage:

    python scripts/generate-agent-artefacts.py            # write artefacts
    python scripts/generate-agent-artefacts.py --check    # CI mode (exit 1 on diff)
    python scripts/generate-agent-artefacts.py --json-out PATH
                                                          # also dump JSON snapshot

The artefacts use HTML comment sentinels:

    <!-- generated:capability-list:begin -->
    ...generated content...
    <!-- generated:capability-list:end -->

Hand-edited prose outside the sentinels is preserved verbatim.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_ROOT / "skills" / "terrafin" / "SKILL.md"
USAGE_PATH = REPO_ROOT / "docs" / "agent" / "usage.md"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

# Sentinel pairs — anchors must already exist in the target files.
SKILL_SENTINELS = ("<!-- generated:capability-list:begin -->", "<!-- generated:capability-list:end -->")
USAGE_SENTINELS = ("<!-- generated:route-summary:begin -->", "<!-- generated:route-summary:end -->")


def _read_pyproject_version() -> str:
    """Pull `[project] version` from pyproject.toml without importing tomllib
    differently across versions — Python 3.11+ ships tomllib in stdlib."""
    import tomllib

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if not version:
        raise SystemExit("Could not read project.version from pyproject.toml")
    return str(version)


def _load_capabilities() -> list[dict[str, Any]]:
    """Return the registered capabilities as a serializable list."""
    # Import lazily so `--check` can run with minimal startup cost when
    # the user just wants the diff.
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from TerraFin.agent.runtime import build_default_capability_registry

    registry = build_default_capability_registry()
    capabilities: list[dict[str, Any]] = []
    for capability in registry.list():
        capabilities.append(
            {
                "name": capability.name,
                "summary": capability.summary,
                "description": capability.description,
                "cli_subcommand_name": capability.cli_subcommand_name,
                "http_route_path": capability.http_route_path,
                "response_model_name": capability.response_model_name,
                "side_effecting": capability.side_effecting,
                "backgroundable": capability.backgroundable,
            }
        )
    return capabilities


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_skill_capability_list(caps: list[dict[str, Any]]) -> str:
    """Render the SKILL.md "Key client methods" section.

    Splits into two sub-lists (stateless HTTP-parity vs hosted-runtime-only)
    so the existing "every capability has a parity HTTP route" claim stays
    accurate even when a future capability is hosted-only.
    """
    stateless = [c for c in caps if c.get("http_route_path")]
    hosted_only = [c for c in caps if not c.get("http_route_path")]

    lines: list[str] = []
    lines.append(
        "Stateless data + analysis (each has a matching `/agent/api/*` HTTP route):"
    )
    lines.append("")
    for cap in stateless:
        name = cap["name"]
        summary = cap.get("summary") or ""
        route = cap.get("http_route_path") or ""
        lines.append(f"- `{name}` — {summary} `GET {route}`")
    lines.append("")

    if hosted_only:
        lines.append(
            "Hosted-runtime-only tools (require a live TerraFinAgentSession; "
            "not exposed as stateless HTTP routes):"
        )
        lines.append("")
        for cap in hosted_only:
            name = cap["name"]
            summary = cap.get("summary") or ""
            lines.append(f"- `{name}` — {summary}")
        lines.append("")

    # Trailing blank line keeps the closing sentinel cleanly separated.
    return "\n".join(lines).rstrip() + "\n"


# Categorisation for the usage.md route summary. Keep ordered for stable
# output; capabilities not matched fall into "Other".
USAGE_CATEGORIES: list[tuple[str, set[str]]] = [
    (
        "Data + chart",
        {
            "resolve",
            "market_data",
            "indicators",
            "market_snapshot",
            "company_info",
            "earnings",
            "financials",
            "portfolio",
            "economic",
            "macro_focus",
            "lppl_analysis",
            "calendar_events",
        },
    ),
    (
        "Valuation + fundamentals",
        {
            "valuation",
            "sp500_dcf",
            "fundamental_screen",
            "risk_profile",
            "beta_estimate",
        },
    ),
    (
        "SEC filings",
        {"sec_filings", "sec_filing_document", "sec_filing_section"},
    ),
    (
        "Sentiment / breadth / market state",
        {
            "fear_greed",
            "market_regime",
            "market_breadth",
            "trailing_forward_pe",
            "top_companies",
            "watchlist",
        },
    ),
]


def render_usage_route_summary(caps: list[dict[str, Any]]) -> str:
    by_name = {c["name"]: c for c in caps}
    matched: set[str] = set()
    sections: list[tuple[str, list[dict[str, Any]]]] = []
    for label, names in USAGE_CATEGORIES:
        bucket = [by_name[name] for name in names if name in by_name]
        if not bucket:
            continue
        bucket.sort(key=lambda c: c["name"])
        matched.update(c["name"] for c in bucket)
        sections.append((label, bucket))

    other = [
        c for c in caps if c.get("http_route_path") and c["name"] not in matched
    ]
    if other:
        other.sort(key=lambda c: c["name"])
        sections.append(("Other", other))

    lines: list[str] = []
    for label, bucket in sections:
        lines.append(f"{label}:")
        lines.append("")
        for cap in bucket:
            route = cap["http_route_path"]
            summary = cap.get("summary") or ""
            lines.append(f"- `GET {route}` — {summary}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Sentinel-bounded file replacement
# ---------------------------------------------------------------------------


def _replace_between_sentinels(
    contents: str,
    begin: str,
    end: str,
    body: str,
    *,
    file_label: str,
) -> str:
    if begin not in contents:
        raise SystemExit(f"{file_label}: missing begin sentinel `{begin}`")
    if end not in contents:
        raise SystemExit(f"{file_label}: missing end sentinel `{end}`")
    head, _, rest = contents.partition(begin)
    _, _, tail = rest.partition(end)
    # Sandwich body between sentinels with one blank line on each side so
    # the markdown renders cleanly regardless of source-file whitespace.
    return f"{head}{begin}\n\n{body}\n{end}{tail}"


def _sync_skill_version(text: str, version: str) -> str:
    """Replace the `version: "..."` line in SKILL.md's YAML frontmatter.

    The frontmatter is the first `---`-delimited block at the top of the file.
    We do a narrow regex substitution rather than parsing the YAML so the rest
    of the frontmatter (description, allowed-tools, triggers) stays byte-for-
    byte identical.
    """
    import re

    pattern = re.compile(r'^version:\s*"[^"]*"\s*$', flags=re.MULTILINE)
    replacement = f'version: "{version}"'
    new_text, count = pattern.subn(replacement, text, count=1)
    if count == 0:
        raise SystemExit(
            f"{SKILL_PATH}: missing `version: \"...\"` line in YAML frontmatter; "
            "add it before running the generator."
        )
    return new_text


def render_files(caps: list[dict[str, Any]]) -> dict[Path, str]:
    skill_body = render_skill_capability_list(caps)
    usage_body = render_usage_route_summary(caps)
    pyproject_version = _read_pyproject_version()

    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    usage_text = USAGE_PATH.read_text(encoding="utf-8")

    new_skill = _replace_between_sentinels(
        skill_text, *SKILL_SENTINELS, body=skill_body, file_label=str(SKILL_PATH)
    )
    new_skill = _sync_skill_version(new_skill, pyproject_version)
    new_usage = _replace_between_sentinels(
        usage_text, *USAGE_SENTINELS, body=usage_body, file_label=str(USAGE_PATH)
    )

    return {SKILL_PATH: new_skill, USAGE_PATH: new_usage}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "CI mode: do not write files. Exit 1 if the committed artefacts "
            "differ from generated output."
        ),
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write a JSON snapshot of the capability registry.",
    )
    args = parser.parse_args()

    caps = _load_capabilities()
    rendered = render_files(caps)

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps({"count": len(caps), "capabilities": caps}, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.check:
        diffs = []
        for path, new_text in rendered.items():
            current = path.read_text(encoding="utf-8")
            if current != new_text:
                diffs.append(path)
        if diffs:
            print(
                "Generated agent artefacts are out of date. Run\n"
                "    python scripts/generate-agent-artefacts.py\n"
                "and commit the result. Diverged files:",
                file=sys.stderr,
            )
            for path in diffs:
                print(f"  - {path.relative_to(REPO_ROOT)}", file=sys.stderr)
            return 1
        print("Generated agent artefacts match the committed copy.")
        return 0

    for path, new_text in rendered.items():
        path.write_text(new_text, encoding="utf-8")
        print(f"updated {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
