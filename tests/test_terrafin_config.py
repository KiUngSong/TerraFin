from TerraFin.configuration import (
    DEFAULT_CACHE_INTERVALS,
    DEFAULT_WATCHLIST_COLLECTION,
    DEFAULT_WATCHLIST_DATABASE,
    DEFAULT_WATCHLIST_DOCUMENT_ID,
    RuntimeConfigError,
    load_terrafin_config,
)


def test_load_terrafin_config_builds_typed_sections() -> None:
    config = load_terrafin_config(
        env={
            "TERRAFIN_HOST": "0.0.0.0",
            "TERRAFIN_PORT": "9000",
            "TERRAFIN_BASE_PATH": "terrafin",
            "TERRAFIN_CACHE_TIMEZONE": "Asia/Seoul",
            "TERRAFIN_PRIVATE_SOURCE_ENDPOINT": "https://private.example.test",
            "TERRAFIN_PRIVATE_SOURCE_ACCESS_KEY": "X-API-Key",
            "TERRAFIN_PRIVATE_SOURCE_ACCESS_VALUE": "secret",
            "TERRAFIN_PRIVATE_SOURCE_TIMEOUT_SECONDS": "5.5",
            "TERRAFIN_MONGODB_URI": "mongodb://mongo.example.test",
            "TERRAFIN_WATCHLIST_MONGODB_DATABASE": "watchlist_db",
            "TERRAFIN_WATCHLIST_MONGODB_COLLECTION": "watchlist_collection",
            "TERRAFIN_WATCHLIST_DOCUMENT_ID": "watchlist_doc",
            "TERRAFIN_SEC_USER_AGENT": "Acme Research sec-contact@acme.test",
            "FRED_API_KEY": "fred-secret",
            "TERRAFIN_CACHE_FRED": "123",
            "TERRAFIN_CACHE_PORTFOLIO": "456",
        }
    )

    assert config.runtime.host == "0.0.0.0"
    assert config.runtime.port == 9000
    assert config.runtime.base_path == "/terrafin"
    assert config.runtime.cache_timezone == "Asia/Seoul"
    assert config.private_access.endpoint == "https://private.example.test"
    assert config.private_access.access_key == "X-API-Key"
    assert config.private_access.access_value == "secret"
    assert config.private_access.timeout_seconds == 5.5
    assert config.watchlist.uri == "mongodb://mongo.example.test"
    assert config.watchlist.database == "watchlist_db"
    assert config.watchlist.collection == "watchlist_collection"
    assert config.watchlist.document_id == "watchlist_doc"
    assert config.sec_edgar.user_agent == "Acme Research sec-contact@acme.test"
    assert config.fred.api_key == "fred-secret"
    assert config.cache.interval_seconds_for("fred") == 123
    assert config.cache.interval_seconds_for("portfolio") == 456


def test_load_terrafin_config_uses_defaults_and_fallbacks() -> None:
    config = load_terrafin_config(
        env={
            "MONGODB_URI": "mongodb://fallback.example.test",
            "TERRAFIN_BASE_PATH": "/",
            "TERRAFIN_CACHE_FRED": "invalid",
        }
    )

    assert config.runtime.host == "127.0.0.1"
    assert config.runtime.port == 8001
    assert config.runtime.base_path == ""
    assert config.runtime.cache_timezone == "UTC"
    assert config.private_access.endpoint is None
    assert config.watchlist.uri == "mongodb://fallback.example.test"
    assert config.watchlist.database == DEFAULT_WATCHLIST_DATABASE
    assert config.watchlist.collection == DEFAULT_WATCHLIST_COLLECTION
    assert config.watchlist.document_id == DEFAULT_WATCHLIST_DOCUMENT_ID
    assert config.sec_edgar.user_agent is None
    assert config.fred.api_key is None
    assert config.cache.interval_seconds_for("fred") == DEFAULT_CACHE_INTERVALS["fred"]


def test_load_terrafin_config_reuses_runtime_validation() -> None:
    try:
        load_terrafin_config(env={"TERRAFIN_CACHE_TIMEZONE": "Mars/Olympus"})
    except RuntimeConfigError as exc:
        assert "TERRAFIN_CACHE_TIMEZONE" in str(exc)
    else:  # pragma: no cover - defensive assertion style for clarity
        raise AssertionError("Expected RuntimeConfigError for invalid timezone.")
