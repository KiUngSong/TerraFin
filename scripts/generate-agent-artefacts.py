"""Regenerate agent-surface documentation from the capability registry.

The capability list lives in `src/TerraFin/agent/runtime/capability.py` (the
`build_default_capability_registry()` function). All downstream artefacts
that mirror the public agent surface — `skills/terrafin/SKILL.md`'s
"Capability inventory" section, `docs/skills/usage.md`'s "Route summary", and the
whole of `docs/skills/catalog.md` — should be derived from that single source. This script does the derivation.

Usage:

    python scripts/generate-agent-artefacts.py            # write artefacts
    python scripts/generate-agent-artefacts.py --check    # CI mode (exit 1 on diff)
    python scripts/generate-agent-artefacts.py --json-out PATH
                                                          # also dump JSON snapshot

The artefacts use HTML comment sentinels:

    <!-- generated:capability-list:begin -->
    ...generated content...
    <!-- generated:capability-list:end -->

Hand-edited prose outside the sentinels is preserved verbatim. The catalog
page is generated whole, sentinels included.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_ROOT / "skills" / "terrafin" / "SKILL.md"
USAGE_PATH = REPO_ROOT / "docs" / "skills" / "usage.md"
CATALOG_PATH = REPO_ROOT / "docs" / "skills" / "catalog.md"
CLI_MAIN_PATH = REPO_ROOT / "src" / "TerraFin" / "agent" / "cli" / "main.py"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

# Sentinel pairs — anchors must already exist in the target files.
SKILL_SENTINELS = ("<!-- generated:capability-list:begin -->", "<!-- generated:capability-list:end -->")
USAGE_SENTINELS = ("<!-- generated:route-summary:begin -->", "<!-- generated:route-summary:end -->")
CATALOG_SENTINELS = ("<!-- generated:capability-catalog:begin -->", "<!-- generated:capability-catalog:end -->")

# Feature-flag modules: each names the capabilities it hides from the hosted
# agent and the environment variable that turns them on.
FLAG_MODULES = (
    ("TerraFin.agent.deepresearch.flag", "DEEPRESEARCH_TOOL_NAMES", "DEEPRESEARCH_ENABLED_ENV"),
)


def _read_pyproject_version() -> str:
    """Pull `[project] version` from pyproject.toml without importing tomllib
    differently across versions — Python 3.11+ ships tomllib in stdlib."""
    import tomllib

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if not version:
        raise SystemExit("Could not read project.version from pyproject.toml")
    return str(version)


def _src_on_path() -> None:
    src = str(REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _category_labels() -> dict[str, str]:
    _src_on_path()
    from TerraFin.agent.runtime.capability import CAPABILITY_CATEGORIES

    return dict(CAPABILITY_CATEGORIES)


def _flag_envs() -> dict[str, str]:
    """Map each flag-gated capability to the environment variable that enables it.

    A flag module that cannot be imported gates nothing, as in the tool adapter.
    """
    import importlib

    _src_on_path()
    gated: dict[str, str] = {}
    for module_name, names_attr, env_attr in FLAG_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for name in getattr(module, names_attr):
            gated[name] = getattr(module, env_attr)
    return gated


def _wired_cli_commands() -> set[str]:
    """Subcommands `terrafin-agent` actually defines, so the docs never name one that fails."""
    import re

    return set(re.findall(r'add_parser\(\s*"([a-z0-9\-]+)"', CLI_MAIN_PATH.read_text(encoding="utf-8")))


def _load_capabilities() -> list[dict[str, Any]]:
    """Return the registered capabilities as a serializable list."""
    # Import lazily so `--check` can run with minimal startup cost when
    # the user just wants the diff.
    _src_on_path()
    from TerraFin.agent.runtime import build_default_capability_registry

    registry = build_default_capability_registry()
    flag_envs = _flag_envs()
    wired = _wired_cli_commands()
    capabilities: list[dict[str, Any]] = []
    for capability in registry.list():
        capabilities.append(
            {
                "name": capability.name,
                "summary": capability.summary,
                "description": capability.description,
                "cli_subcommand_name": capability.cli_subcommand_name,
                "http_route_path": capability.http_route_path,
                "http_method": capability.http_method,
                "response_model_name": capability.response_model_name,
                "side_effecting": capability.side_effecting,
                "backgroundable": capability.backgroundable,
                "background_only": capability.background_only,
                "category": capability.category,
                "flag_env": flag_envs.get(capability.name),
                "cli_command": capability.cli_subcommand_name if capability.cli_subcommand_name in wired else None,
            }
        )
    return capabilities


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_skill_capability_list(caps: list[dict[str, Any]]) -> str:
    """Render the SKILL.md "Capability inventory" section.

    Splits into two sub-lists by whether the capability has an HTTP route, so
    the docs can name the exceptions from the registry instead of asserting a
    count that nothing keeps true.
    """
    stateless = [c for c in caps if c.get("http_route_path")]
    hosted_only = [c for c in caps if not c.get("http_route_path")]

    lines: list[str] = []
    lines.append("Stateless data + analysis (each has a matching `/agent/api/*` HTTP route):")
    lines.append("")
    for cap in stateless:
        name = cap["name"]
        summary = cap.get("summary") or ""
        route = cap.get("http_route_path") or ""
        lines.append(f"- `{name}` — {summary} `{cap['http_method']} {route}`")
    lines.append("")

    if hosted_only:
        lines.append(
            "Hosted-runtime-only tools (require a live TerraFinAgentSession; not exposed as stateless HTTP routes):"
        )
        lines.append("")
        for cap in hosted_only:
            name = cap["name"]
            summary = cap.get("summary") or ""
            lines.append(f"- `{name}` — {summary}")
        lines.append("")

    # Trailing blank line keeps the closing sentinel cleanly separated.
    return "\n".join(lines).rstrip() + "\n"


def _group_by_category(caps: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group capabilities under their registry category, in `CAPABILITY_CATEGORIES` order."""
    labels = _category_labels()
    unknown = sorted(c["name"] for c in caps if c.get("category") not in labels)
    if unknown:
        raise SystemExit(
            "Capabilities with no category from CAPABILITY_CATEGORIES: "
            + ", ".join(unknown)
            + "\nSet `category=` on them in src/TerraFin/agent/runtime/capability.py."
        )
    return [(label, bucket) for key, label in labels.items() if (bucket := [c for c in caps if c["category"] == key])]


def render_usage_route_summary(caps: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for label, bucket in _group_by_category([c for c in caps if c.get("http_route_path") and not c.get("flag_env")]):
        lines.append(f"{label}:")
        lines.append("")
        for cap in sorted(bucket, key=lambda c: c["name"]):
            route = cap["http_route_path"]
            summary = cap.get("summary") or ""
            lines.append(f"- `{cap['http_method']} {route}` — {summary}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _reach(cap: dict[str, Any]) -> str:
    """How a caller reaches one capability: HTTP route, CLI command, or the hosted agent only."""
    ways: list[str] = []
    if cap.get("http_route_path"):
        ways.append(f"`{cap['http_method']} {cap['http_route_path']}`")
    if cap.get("cli_command"):
        ways.append(f"`terrafin-agent {cap['cli_command']}`")
    if not ways:
        ways.append("Hosted agent only")
    if cap.get("background_only"):
        ways.append(f"as the background task `start_{cap['name']}_task`")
    return ", ".join(ways)


def render_catalog_page(caps: list[dict[str, Any]]) -> str:
    """Render the whole of docs/skills/catalog.md."""
    lines = [
        "# Skill catalog",
        "",
        "<!-- Auto-generated from src/TerraFin/agent/runtime/capability.py by",
        "     `python scripts/generate-agent-artefacts.py`. Edit the registry, not",
        "     this page. Hand-edits will be overwritten. -->",
        "",
        CATALOG_SENTINELS[0],
        "",
        "A capability is one research operation TerraFin can run: fetch a price series, run a DCF,",
        "read a section of a 10-K. Each one is registered once, in",
        "`build_default_capability_registry` in `src/TerraFin/agent/runtime/capability.py`.",
        "The `/agent/api/*` HTTP routes, the `terrafin-agent` CLI and the hosted agent all expose",
        "capabilities from that registry.",
        "",
        "This page is generated from the registry by `scripts/generate-agent-artefacts.py`, so it",
        "lists every released capability in the registry. The category of each capability is a field of its",
        "registration. To print the live set as JSON, run:",
        "",
        "```bash",
        "terrafin-agent capabilities",
        "```",
        "",
        "How to read the **How to reach it** column:",
        "",
        "- An HTTP route is served by a running TerraFin server.",
        "- A `terrafin-agent` command runs the capability from the CLI.",
        "- **Hosted agent only** means there is no HTTP route and no CLI command: only TerraFin's",
        "  own agent calls it, inside a session.",
        "",
        "Capabilities behind a feature flag are not listed here.",
        "",
    ]
    # The public page leaves out every flag-gated capability.
    shipped = [cap for cap in caps if not cap.get("flag_env")]
    for label, bucket in _group_by_category(shipped):
        lines.append(f"## {label}")
        lines.append("")
        lines.append("| Capability | What it does | How to reach it |")
        lines.append("| --- | --- | --- |")
        for cap in bucket:
            summary = (cap.get("summary") or "").replace("|", "\\|")
            lines.append(f"| `{cap['name']}` | {summary} | {_reach(cap)} |")
        lines.append("")
    lines.append(CATALOG_SENTINELS[1])
    return "\n".join(lines) + "\n"


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
            f'{SKILL_PATH}: missing `version: "..."` line in YAML frontmatter; add it before running the generator.'
        )
    return new_text


def render_files(caps: list[dict[str, Any]]) -> dict[Path, str]:
    skill_body = render_skill_capability_list(caps)
    usage_body = render_usage_route_summary(caps)
    pyproject_version = _read_pyproject_version()

    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    usage_text = USAGE_PATH.read_text(encoding="utf-8")

    new_skill = _replace_between_sentinels(skill_text, *SKILL_SENTINELS, body=skill_body, file_label=str(SKILL_PATH))
    new_skill = _sync_skill_version(new_skill, pyproject_version)
    new_usage = _replace_between_sentinels(usage_text, *USAGE_SENTINELS, body=usage_body, file_label=str(USAGE_PATH))

    return {SKILL_PATH: new_skill, USAGE_PATH: new_usage, CATALOG_PATH: render_catalog_page(caps)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help=("CI mode: do not write files. Exit 1 if the committed artefacts differ from generated output."),
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
            current = path.read_text(encoding="utf-8") if path.exists() else None
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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8")
        print(f"updated {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
