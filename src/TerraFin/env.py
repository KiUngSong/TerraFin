"""Helpers for TerraFin runtime environment bootstrap."""

import os
from collections.abc import Mapping
from pathlib import Path
from threading import Lock


_AUTOLOAD_ATTEMPTED = False
_AUTOLOAD_LOADED = False
_AUTOLOAD_LOCK = Lock()
STATE_DIR_ENV = "TERRAFIN_STATE_DIR"


def _dotenv_disabled() -> bool:
    return os.getenv("TERRAFIN_DISABLE_DOTENV", "").strip().lower() in {"1", "true", "yes", "on"}


def _candidate_dotenv_paths(dotenv_path: str | os.PathLike[str] | None = None) -> list[Path]:
    candidates: list[Path] = []
    if dotenv_path is not None:
        candidates.append(Path(dotenv_path).expanduser())
        return candidates

    explicit = os.getenv("TERRAFIN_DOTENV_PATH", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
        return candidates

    try:
        from dotenv import find_dotenv
    except ImportError:  # pragma: no cover - optional import guard
        return candidates

    found = find_dotenv(usecwd=True)
    if found:
        candidates.append(Path(found))

    package_root_candidate = Path(__file__).resolve().parents[2] / ".env"
    if package_root_candidate not in candidates:
        candidates.append(package_root_candidate)

    return candidates


def _source_repo_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "pyproject.toml").is_file():
        return candidate
    return None


def resolve_state_dir(env: Mapping[str, str] | None = None) -> Path:
    """Resolve TerraFin's shared local state directory.

    Defaults to the repo-root `.terrafin/` when running from source so the CLI,
    hosted runtime, and provider caches share one location regardless of cwd.
    Falls back to `~/.terrafin/` outside the source tree.
    """

    source = env if env is not None else os.environ
    explicit = str(source.get(STATE_DIR_ENV, "") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    repo_root = _source_repo_root()
    if repo_root is not None:
        return repo_root / ".terrafin"
    return Path.home() / ".terrafin"


def apply_api_keys(api_keys: Mapping[str, str] | None = None) -> None:
    for key, value in (api_keys or {}).items():
        os.environ[str(key)] = str(value)


def _load_dotenv_candidates(
    dotenv_path: str | os.PathLike[str] | None = None,
    *,
    override: bool = False,
) -> bool:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - optional import guard
        return False

    for candidate in _candidate_dotenv_paths(dotenv_path):
        if not candidate.is_file():
            continue
        return bool(load_dotenv(candidate, override=override))
    return False


def load_dotenv_file(
    dotenv_path: str | os.PathLike[str] | None = None,
    *,
    override: bool = False,
) -> bool:
    """Explicitly load a `.env` file for notebooks, scripts, or embedding."""

    return _load_dotenv_candidates(dotenv_path, override=override)


def ensure_runtime_env_loaded() -> bool:
    """Lazily bootstrap `.env` once per process for env-backed operations."""

    global _AUTOLOAD_ATTEMPTED, _AUTOLOAD_LOADED

    if _dotenv_disabled():
        return False

    with _AUTOLOAD_LOCK:
        if _AUTOLOAD_ATTEMPTED:
            return _AUTOLOAD_LOADED
        _AUTOLOAD_ATTEMPTED = True
        _AUTOLOAD_LOADED = _load_dotenv_candidates()
        return _AUTOLOAD_LOADED


def configure(
    *,
    api_keys: Mapping[str, str] | None = None,
    dotenv_path: str | os.PathLike[str] | None = None,
    load_dotenv: bool = True,
    override: bool = False,
) -> bool:
    """Explicitly configure TerraFin for notebooks, scripts, or embedding.

    Explicit API keys are applied after dotenv loading so direct arguments win.
    """

    global _AUTOLOAD_ATTEMPTED, _AUTOLOAD_LOADED

    loaded = load_dotenv_file(dotenv_path, override=override) if load_dotenv else False
    apply_api_keys(api_keys)
    if load_dotenv:
        with _AUTOLOAD_LOCK:
            _AUTOLOAD_ATTEMPTED = True
            _AUTOLOAD_LOADED = loaded
    return loaded


def load_entrypoint_dotenv() -> bool:
    """Load a `.env` file for explicit CLI/server entrypoints."""

    if _dotenv_disabled():
        return False
    return load_dotenv_file()
