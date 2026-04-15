---
title: Notebooks
summary: Rules and bootstrap patterns for TerraFin notebooks.
---

# Notebooks

This page formalizes the guidance currently kept in `notebooks/README.md`.

## Purpose

The `notebooks/` tree is for human-guided notebooks and manual exploration
only.

| Folder | Purpose |
|--------|---------|
| `notebooks/analytics/` | Research and demo notebooks for analytics helpers |
| `notebooks/data/` | Manual provider exploration |
| `notebooks/interface/` | Notebook flows for chart and UI behavior |

## Repository Rule

- `tests/` contains automated pytest suites
- `notebooks/` contains manual/demo notebooks
- manual notebooks should not use a `test_` filename prefix

If notebook logic becomes part of automated regression coverage, convert it
into a real `test_*.py` file under `tests/` instead of placing the notebook in
the test tree.

## Bootstrap Pattern

Every tracked notebook should make runtime setup explicit at the top of the
first code cell:

```python
from TerraFin import configure, load_terrafin_config

configure()
config = load_terrafin_config()
```

Use `configure(dotenv_path="/absolute/path/to/.env")` if the kernel is not
launched from a directory where TerraFin can discover `.env` normally.

## Why This Pattern Matters

- `import TerraFin` stays side-effect free
- notebook readers can immediately see how config is loaded
- `load_terrafin_config()` makes the resolved runtime settings easy to inspect

## Related Docs

- [Getting Started](getting-started.md)
- [Development Guide](development.md)
