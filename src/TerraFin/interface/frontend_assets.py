import json
from dataclasses import dataclass
from pathlib import Path


class FrontendBuildError(RuntimeError):
    """Raised when the packaged frontend build is missing or incomplete."""


@dataclass(frozen=True)
class FrontendBuildPaths:
    build_dir: Path
    index_html: Path
    static_dir: Path
    asset_manifest: Path


def _manifest_asset_path(build_dir: Path, asset_path: str) -> Path:
    normalized = str(asset_path or "").strip().lstrip("/")
    return build_dir / normalized


def resolve_frontend_build_paths(build_dir: Path) -> FrontendBuildPaths:
    return FrontendBuildPaths(
        build_dir=build_dir,
        index_html=build_dir / "index.html",
        static_dir=build_dir / "static",
        asset_manifest=build_dir / "asset-manifest.json",
    )


def validate_frontend_build(build_dir: Path) -> FrontendBuildPaths:
    paths = resolve_frontend_build_paths(build_dir)
    missing = [
        path.name
        for path in (paths.index_html, paths.static_dir, paths.asset_manifest)
        if not path.exists()
    ]
    if missing:
        raise FrontendBuildError(
            "Frontend build assets are missing. "
            f"Expected {', '.join(missing)} under '{paths.build_dir}'."
        )

    try:
        manifest = json.loads(paths.asset_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrontendBuildError(
            f"Frontend asset manifest is unreadable: '{paths.asset_manifest}'."
        ) from exc

    entrypoints = manifest.get("entrypoints")
    if not isinstance(entrypoints, list) or not entrypoints:
        raise FrontendBuildError(
            "Frontend asset manifest does not declare any runtime entrypoints."
        )

    missing_entrypoints = [
        asset
        for asset in entrypoints
        if not _manifest_asset_path(paths.build_dir, str(asset)).is_file()
    ]
    if missing_entrypoints:
        raise FrontendBuildError(
            "Frontend runtime assets are missing from the packaged build: "
            + ", ".join(sorted(missing_entrypoints))
        )

    return paths
