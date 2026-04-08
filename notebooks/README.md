# TerraFin Notebooks

This directory is for human-guided notebooks and manual exploration only.

- `analytics/`: research and demo notebooks for analytics helpers
- `data/`: manual data-provider exploration notebooks
- `interface/`: notebook flows for chart and UI behavior

Repository rule:

- `tests/` contains automated pytest suites
- `notebooks/` contains manual/demo notebooks
- manual notebooks should not use a `test_` filename prefix

If a notebook becomes part of automated regression coverage, convert the logic
into a real `test_*.py` file under `tests/` instead of placing the notebook
back there.

## Bootstrap Pattern

Every tracked notebook should make TerraFin runtime setup explicit at the top
of its first code cell:

```python
from TerraFin import configure, load_terrafin_config

configure()
config = load_terrafin_config()
```

Use `configure(dotenv_path="/absolute/path/to/.env")` if the notebook kernel is
not launched from a directory where TerraFin can discover `.env` normally.

Why this is the preferred pattern:

- `import TerraFin` stays side-effect free
- notebook readers can immediately see how config is loaded
- `config = load_terrafin_config()` makes the resolved runtime settings easy to inspect
