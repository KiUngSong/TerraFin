"""CI guard: committed agent artefacts must match the generator's output.

If this test fails, regenerate the artefacts:

    python scripts/generate-agent-artefacts.py

and commit the result. The generator derives `skills/terrafin/SKILL.md`'s
"Key client methods" section and `docs/agent/usage.md`'s "Route summary"
table from the capability registry in `src/TerraFin/agent/runtime.py`.
Drift is a sign that someone added or changed a capability without running
the generator — the agent surfaces would otherwise diverge silently.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "generate-agent-artefacts.py"


def test_generated_agent_artefacts_match_registry() -> None:
    assert GENERATOR.exists(), f"generator script missing: {GENERATOR}"
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        message_lines = [
            "Generated agent artefacts are out of date.",
            "Run `python scripts/generate-agent-artefacts.py` and commit the result.",
            "",
            "Generator stderr:",
            result.stderr.strip() or "(empty)",
            "",
            "Generator stdout:",
            result.stdout.strip() or "(empty)",
        ]
        raise AssertionError("\n".join(message_lines))
