from collections.abc import Mapping

from TerraFin.configuration import RuntimeConfig, RuntimeConfigError, load_terrafin_config


def load_runtime_config(env: Mapping[str, str] | None = None) -> RuntimeConfig:
    return load_terrafin_config(env=env).runtime


__all__ = ["RuntimeConfig", "RuntimeConfigError", "load_runtime_config"]
