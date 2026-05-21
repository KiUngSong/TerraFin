"""Agent-facing service layer.

Split out of the original ``agent/service.py`` module. The package layout:

- ``service.service`` — ``TerraFinAgentService`` capability methods plus
  the module-level helper names (``get_data_factory``,
  ``build_stock_dcf_payload``, ``canonical_macro_name``, ...) that the
  original single-file module exposed.
- ``service._formatters`` — private payload/formatter helpers used by
  ``TerraFinAgentService``.
- ``service.hosted`` — process-singleton hosted-agent loop bootstrapper.
- ``service.client`` — ``TerraFinAgentClient`` (python/HTTP transport).
- ``service.client_helpers`` — ``TerraFinRuntimeSessionClient`` and the
  thin ``ask_agent`` / ``create_runtime_session`` convenience wrappers.
  (Renamed from ``runtime_helpers`` — the file has nothing to do with
  runtime internals; it's a client-side convenience wrapper.)

Old top-level modules (``agent.service``, ``agent.hosted_service``,
``agent.client``, ``agent.runtime_helpers``) survive as ``sys.modules``
shims so external imports and monkeypatching keep working.

Why the lazy ``__getattr__`` (PEP 562):
=======================================
The real reason is **monkey-patch propagation**, not cycle prevention.
Tests (``tests/agent/test_service.py``) patch ~10 helpers that lived
at module scope in the original single-file ``agent/service.py`` —
``monkeypatch.setattr(agent_service, "get_data_factory", ...)`` — and
expect those patches to override what ``TerraFinAgentService`` methods
see at call time. After the split those helpers live inside
``service.service``; patching the package alone would NOT propagate
(the inner module's globals are a separate ``dict``). Module-level
``__setattr__`` isn't supported by Python either, so we can't
intercept the patch itself.

The ``_ForwardingModule`` class below installs itself as the package's
``sys.modules`` entry and forwards both reads AND writes into the
inner ``service.service`` submodule. ``setattr(agent_service, "X", ...)``
becomes ``setattr(service.service, "X", ...)`` — the patch lands where
the methods actually look up the symbol.

Note: rebinding ``sys.modules[__name__].__class__`` is a CPython
implementation detail (also works on PyPy in practice but isn't
language-guaranteed).

(The lazy resolution is also incidentally friendly to load order —
``runtime.hosted`` does ``from ..service import TerraFinAgentService``
as a default factory at construction time and benefits from not
forcing immediate submodule load — but the load graph isn't strictly
cyclic; this is icing.)
"""

from typing import Any


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # symbol -> (submodule, attribute_name)
    "TerraFinAgentService": (".service", "TerraFinAgentService"),
    "TerraFinAgentClient": (".client", "TerraFinAgentClient"),
    "TerraFinRuntimeSessionClient": (".client_helpers", "TerraFinRuntimeSessionClient"),
    "ask_agent": (".client_helpers", "ask_agent"),
    "create_runtime_session": (".client_helpers", "create_runtime_session"),
    "build_hosted_agent_loop": (".hosted", "build_hosted_agent_loop"),
    "build_hosted_model_provider_registry": (".hosted", "build_hosted_model_provider_registry"),
    "get_hosted_agent_loop": (".hosted", "get_hosted_agent_loop"),
    "reset_hosted_agent_loop": (".hosted", "reset_hosted_agent_loop"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is not None:
        from importlib import import_module

        module = import_module(target[0], __name__)
        value = getattr(module, target[1])
        globals()[name] = value  # cache for subsequent accesses
        return value
    # Fallback: surface the inner ``service`` submodule's module-level
    # attributes so monkeypatching the package reads the same names the
    # class methods would see at definition time. Writes through
    # ``setattr(<this_package>, name, value)`` set the attribute on this
    # package object only — they do not propagate into the inner
    # submodule's globals. The companion shim below uses a custom
    # module subclass to forward setattr writes through to the inner
    # submodule for back-compat with existing tests.
    from importlib import import_module

    inner = import_module(".service", __name__)
    try:
        value = getattr(inner, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    globals()[name] = value  # cache for subsequent accesses, matching the explicit branch
    return value


# Install a custom module class so attribute writes (monkeypatch) on
# this package forward into the inner ``service.service`` submodule —
# matching the original single-file ``agent/service.py`` semantics for
# names that ``TerraFinAgentService`` methods look up via their own
# module globals.
import sys as _sys
from types import ModuleType as _ModuleType


class _ForwardingModule(_ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_") or name in _LAZY_EXPORTS:
            super().__setattr__(name, value)
            return
        from importlib import import_module

        try:
            inner = import_module(".service", __name__)
        except Exception:
            super().__setattr__(name, value)
            return
        if hasattr(inner, name):
            setattr(inner, name, value)
            return
        super().__setattr__(name, value)


_sys.modules[__name__].__class__ = _ForwardingModule


__all__ = list(_LAZY_EXPORTS)
