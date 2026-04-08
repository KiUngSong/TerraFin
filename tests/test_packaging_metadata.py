import tomllib
from pathlib import Path


def test_core_runtime_dependencies_include_scipy() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text())["project"]
    dependencies = project["dependencies"]

    assert any(str(dependency).startswith("scipy") for dependency in dependencies)
