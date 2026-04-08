from collections.abc import Mapping

from TerraFin.configuration import PrivateAccessConfig, load_terrafin_config


def load_private_access_config(env: Mapping[str, str] | None = None) -> PrivateAccessConfig:
    return load_terrafin_config(env=env).private_access
