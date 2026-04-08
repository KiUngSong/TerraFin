import pytest

from TerraFin.data.providers.corporate.filings.sec_edgar import filing


def test_sec_user_agent_requires_explicit_env_var(monkeypatch) -> None:
    monkeypatch.delenv("TERRAFIN_SEC_USER_AGENT", raising=False)
    monkeypatch.setenv("TERRAFIN_DISABLE_DOTENV", "1")

    with pytest.raises(filing.SecEdgarConfigurationError, match="TERRAFIN_SEC_USER_AGENT"):
        filing._sec_user_agent()


def test_sec_user_agent_supports_explicit_override(monkeypatch) -> None:
    monkeypatch.setenv("TERRAFIN_SEC_USER_AGENT", "Acme Research sec-contact@acme.test")

    assert filing._sec_user_agent() == "Acme Research sec-contact@acme.test"


def test_create_sec_client_prefers_explicit_user_agent_override(monkeypatch) -> None:
    captured: list[tuple[str, str]] = []

    class _FakeSECClient:
        def __init__(self, user_agent: str, host_url: str) -> None:
            captured.append((user_agent, host_url))

    monkeypatch.setenv("TERRAFIN_SEC_USER_AGENT", "My TerraFin Bot bot@example.com")
    monkeypatch.setattr(filing, "SECClient", _FakeSECClient)

    _ = filing.create_sec_client(host_url="www.sec.gov")

    assert captured == [("My TerraFin Bot bot@example.com", "www.sec.gov")]


def test_sec_edgar_status_reports_disabled_when_user_agent_missing(monkeypatch) -> None:
    monkeypatch.delenv("TERRAFIN_SEC_USER_AGENT", raising=False)
    monkeypatch.setenv("TERRAFIN_DISABLE_DOTENV", "1")

    assert filing.sec_edgar_is_configured() is False
    assert "TERRAFIN_SEC_USER_AGENT" in filing.sec_edgar_status_message()


def test_sec_edgar_module_has_no_free_proxy_fallback() -> None:
    assert not hasattr(filing, "get_free_proxy")
