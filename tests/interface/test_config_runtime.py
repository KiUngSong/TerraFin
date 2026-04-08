import pytest

from TerraFin.interface.config import RuntimeConfigError, load_runtime_config


def test_runtime_config_defaults_when_env_missing() -> None:
    config = load_runtime_config(env={})
    assert config.host == "127.0.0.1"
    assert config.port == 8001
    assert config.base_path == ""
    assert config.cache_timezone == "UTC"


def test_runtime_config_invalid_port_non_integer() -> None:
    with pytest.raises(RuntimeConfigError, match="Invalid TERRAFIN_PORT"):
        load_runtime_config(env={"TERRAFIN_PORT": "invalid"})


def test_runtime_config_invalid_port_out_of_range_low() -> None:
    with pytest.raises(RuntimeConfigError, match="Invalid TERRAFIN_PORT"):
        load_runtime_config(env={"TERRAFIN_PORT": "0"})


def test_runtime_config_invalid_port_out_of_range_high() -> None:
    with pytest.raises(RuntimeConfigError, match="Invalid TERRAFIN_PORT"):
        load_runtime_config(env={"TERRAFIN_PORT": "65536"})


def test_runtime_config_base_path_normalization_adds_leading_slash() -> None:
    config = load_runtime_config(env={"TERRAFIN_BASE_PATH": "terrafin"})
    assert config.base_path == "/terrafin"


def test_runtime_config_base_path_normalization_removes_trailing_slash() -> None:
    config = load_runtime_config(env={"TERRAFIN_BASE_PATH": "/terrafin/"})
    assert config.base_path == "/terrafin"


def test_runtime_config_base_path_normalization_empty_values() -> None:
    config_empty = load_runtime_config(env={"TERRAFIN_BASE_PATH": ""})
    config_root = load_runtime_config(env={"TERRAFIN_BASE_PATH": "/"})
    assert config_empty.base_path == ""
    assert config_root.base_path == ""


def test_runtime_config_accepts_valid_cache_timezone() -> None:
    config = load_runtime_config(env={"TERRAFIN_CACHE_TIMEZONE": "Asia/Seoul"})
    assert config.cache_timezone == "Asia/Seoul"


def test_runtime_config_rejects_invalid_cache_timezone() -> None:
    with pytest.raises(RuntimeConfigError, match="Invalid TERRAFIN_CACHE_TIMEZONE"):
        load_runtime_config(env={"TERRAFIN_CACHE_TIMEZONE": "Mars/Olympus"})
