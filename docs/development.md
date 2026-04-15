---
title: Development Guide
summary: Local workflow for code, docs, tests, notebooks, and frontend changes.
---

# Development Guide

This page is the maintainer-facing companion to the product docs.

## Repo Layout

| Path | Purpose |
|------|---------|
| `src/TerraFin/data/` | Data providers, normalization, and output types |
| `src/TerraFin/analytics/` | Indicators, DCF, risk, options, portfolio, and simulation helpers |
| `src/TerraFin/interface/` | FastAPI app, page routes, and frontend |
| `src/TerraFin/agent/` | External-agent client, hosted runtime, model runtime, and tools |
| `docs/` | Formal documentation site source |
| `tests/` | Automated regression coverage |
| `notebooks/` | Manual and demo notebooks only |

## Local Setup

```bash
pip install -e ".[dev]"
```

Add extras when needed:

```bash
pip install -e ".[db]"
pip install -e ".[notebooks]"
pip install -e ".[docs]"
```

## Tests

Core Python tests:

```bash
pytest
```

Agent-focused slice:

```bash
pytest tests/agent tests/interface/test_agent_api.py
```

Packaging smoke:

```bash
python -m build
python scripts/package_smoke.py
```

## Frontend

The frontend lives under `src/TerraFin/interface/frontend/`.

Typical commands:

```bash
npm install
npm run build
```

When you touch page-specific agent context, DCF workbenches, or the hosted
assistant widget, verify both desktop and mobile flows.

## Docs Site

TerraFin now ships a formal static docs site using MkDocs Material.

Preview locally:

```bash
pip install -e ".[docs]"
mkdocs serve
```

Build locally:

```bash
mkdocs build --strict
```

GitHub Pages deployment is defined in `.github/workflows/docs-pages.yml`.

## Notebook Rules

Notebooks are for human-guided exploration, not automated tests.

- keep notebooks under `notebooks/`
- do not use a `test_` prefix for notebook filenames
- promote stable notebook logic into `tests/test_*.py` if it becomes regression-critical

Detailed notebook guidance lives in [Notebooks](notebooks.md).

## External Artifacts

Some code-adjacent references remain useful even though they are not formal
docs pages:

- analytics implementation notes:
  [src/TerraFin/analytics/analysis/README.md](https://github.com/KiUngSong/TerraFin/blob/main/src/TerraFin/analytics/analysis/README.md)
- shipped TerraFin skill:
  [skills/terrafin/SKILL.md](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md)

## Related Docs

- [Feature Integration](feature-integration.md)
- [Analytics Notes](analytics-notes.md)
- [Notebooks](notebooks.md)
