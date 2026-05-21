"""CLI subpackage. Split out of the original ``agent/cli.py`` module.

Modules:
    main   - argparse CLI entry point (``main`` plus ``_*`` helpers).
    tasks  - high-level helpers (``ticker_brief``, ``market_snapshot``, ...)
             over ``TerraFinAgentClient``.

Back-compat: existing callers and tests treat ``TerraFin.agent.cli`` as a
flat module — they ``import TerraFin.agent.cli as cli_module`` then
``monkeypatch.setattr(cli_module, "TerraFinAgentClient", ...)`` expecting
the patch to be visible to functions defined in what is now ``cli.main``.
To preserve that behaviour we install a custom module class whose
``__getattr__`` / ``__setattr__`` proxy to ``cli.main`` for any name not
explicitly defined on the package itself. Submodule access
(``TerraFin.agent.cli.tasks``) keeps working because this remains a real
package with a ``__path__``.

Note: rebinding ``sys.modules[__name__].__class__`` is a CPython
implementation detail (also works on PyPy in practice but isn't
language-guaranteed).
"""
import sys
import types

from . import main as _main_module


class _CliPackageProxy(types.ModuleType):
    """Module subclass that forwards attribute access to ``cli.main``.

    Reads fall through to ``cli.main`` so legacy ``agent_cli.X`` lookups
    still resolve. Writes are mirrored to ``cli.main`` so monkeypatches
    on the package namespace also rebind the name inside ``main.py``
    (where the patched value is actually consumed at call time).
    """

    def __getattr__(self, name: str):  # noqa: D401 - module proto
        try:
            return getattr(_main_module, name)
        except AttributeError:
            raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

    def __setattr__(self, name: str, value) -> None:  # noqa: D401 - module proto
        super().__setattr__(name, value)
        # Mirror the write into cli.main so functions defined there see
        # the patched value when they look the name up in their globals.
        if name not in {"__path__", "__name__", "__loader__", "__package__", "__spec__", "__file__", "__builtins__"}:
            setattr(_main_module, name, value)


sys.modules[__name__].__class__ = _CliPackageProxy


# Re-export the canonical public entry point so static analyzers and
# ``from TerraFin.agent.cli import main`` callers see it on the package.
main = _main_module.main


__all__ = ["main"]
