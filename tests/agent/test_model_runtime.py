import pytest

from TerraFin.agent.definitions import TerraFinAgentDefinition
from TerraFin.agent.loop import TerraFinConversationMessage, TerraFinHostedConversation, TerraFinModelTurn
from TerraFin.agent.model_management import set_saved_default_model_ref
from TerraFin.agent.model_runtime import (
    TerraFinModelConfigError,
    TerraFinModelProviderRegistry,
    TerraFinProviderRoutedModelClient,
    TerraFinRuntimeModel,
)
from TerraFin.agent.runtime import TerraFinAgentSession
from TerraFin.agent.service.hosted import (
    build_hosted_model_provider_registry,
    get_hosted_agent_loop,
    reset_hosted_agent_loop,
)


class _FakeProvider:
    provider_id = "fake"
    label = "Fake"

    def resolve_model(self, model_id: str) -> TerraFinRuntimeModel:
        normalized = str(model_id or "").strip()
        if not normalized:
            raise TerraFinModelConfigError("Fake model id is required.")
        return TerraFinRuntimeModel(
            model_ref=f"fake/{normalized}",
            provider_id="fake",
            provider_label="Fake",
            model_id=normalized,
        )

    def complete(self, *, model, **kwargs):
        _ = kwargs
        return TerraFinModelTurn(
            assistant_message=TerraFinConversationMessage(
                role="assistant",
                content=f"using {model.model_ref}",
            )
        )


def _agent_definition() -> TerraFinAgentDefinition:
    return TerraFinAgentDefinition(
        name="market-researcher",
        description="General market agent.",
        allowed_capabilities=("market_snapshot",),
    )


def test_provider_registry_parses_valid_model_refs() -> None:
    registry = TerraFinModelProviderRegistry()
    registry.register(_FakeProvider())

    resolved = registry.resolve_model_ref("fake/demo-model")

    assert resolved.model_ref == "fake/demo-model"
    assert resolved.provider_id == "fake"
    assert resolved.model_id == "demo-model"


@pytest.mark.parametrize(
    "model_ref",
    ["", "openai", " openai /gpt-4.1-mini ", "/gpt-4.1-mini", "openai/"],
)
def test_provider_registry_rejects_invalid_model_refs(model_ref: str) -> None:
    registry = TerraFinModelProviderRegistry()
    registry.register(_FakeProvider())

    with pytest.raises(TerraFinModelConfigError):
        registry.resolve_model_ref(model_ref)


def test_provider_registry_maps_legacy_openai_env_to_canonical_ref() -> None:
    registry = build_hosted_model_provider_registry()

    resolved = registry.resolve_default_model_ref(env={"TERRAFIN_OPENAI_MODEL": "gpt-4.1-mini"})

    assert resolved.model_ref == "openai/gpt-4.1-mini"
    assert resolved.provider_id == "openai"


def test_provider_registry_reads_saved_default_model_ref_from_state(tmp_path) -> None:
    registry = build_hosted_model_provider_registry()
    env = {"TERRAFIN_AGENT_MODELS_PATH": str(tmp_path / "agent-models.json")}
    set_saved_default_model_ref("google/gemini-3.1-pro-preview", env)

    resolved = registry.resolve_default_model_ref(env=env)

    assert resolved.model_ref == "google/gemini-3.1-pro-preview"
    assert resolved.provider_id == "google"


def test_a_saved_ref_that_is_not_a_removed_provider_keeps_its_own_error(tmp_path) -> None:
    """Only a missing provider gets the "no longer available" guidance. A
    malformed ref and a bad model id carry remedies of their own, and dressing
    them as a removed provider sends the user to the wrong fix.
    """
    registry = build_hosted_model_provider_registry()

    def _error_for(ref: str) -> str:
        env = {"TERRAFIN_AGENT_MODELS_PATH": str(tmp_path / f"{abs(hash(ref))}.json")}
        set_saved_default_model_ref(ref, env)
        with pytest.raises(TerraFinModelConfigError) as excinfo:
            registry.resolve_default_model_ref(env=env)
        return str(excinfo.value)

    malformed = _error_for("garbage")
    assert "canonical 'provider/model' format" in malformed
    assert "no longer available" not in malformed

    bad_model = _error_for("google/totally-not-a-model")
    assert "totally-not-a-model" in bad_model
    assert "no longer available" not in bad_model


def test_saved_default_ref_for_removed_provider_names_the_stale_ref(tmp_path) -> None:
    registry = build_hosted_model_provider_registry()
    env = {"TERRAFIN_AGENT_MODELS_PATH": str(tmp_path / "agent-models.json")}
    set_saved_default_model_ref("github-copilot/gpt-4o", env)

    with pytest.raises(TerraFinModelConfigError) as excinfo:
        registry.resolve_default_model_ref(env=env)

    message = str(excinfo.value)
    assert "github-copilot/gpt-4o" in message
    assert "terrafin-agent models use" in message


def test_routed_model_client_pins_runtime_model_to_session_metadata() -> None:
    registry = TerraFinModelProviderRegistry()
    registry.register(_FakeProvider())
    default_model = registry.resolve_model_ref("fake/demo-model")
    client = TerraFinProviderRoutedModelClient(
        registry=registry,
        default_model=default_model,
    )
    session = TerraFinAgentSession(session_id="runtime:model")
    conversation = TerraFinHostedConversation(
        session_id="runtime:model",
        agent_name="market-researcher",
        messages=[TerraFinConversationMessage(role="user", content="hello")],
    )

    turn = client.complete(
        agent=_agent_definition(),
        session=session,
        conversation=conversation,
        messages=conversation.snapshot(),
        tools=(),
    )

    assert turn.assistant_message is not None
    assert turn.assistant_message.content == "using fake/demo-model"
    assert session.metadata["runtimeModel"]["modelRef"] == "fake/demo-model"
    assert conversation.metadata["runtimeModel"]["providerId"] == "fake"


def test_hosted_agent_loop_resyncs_saved_default_model_without_rebuild(monkeypatch, tmp_path) -> None:
    env = {"TERRAFIN_AGENT_MODELS_PATH": str(tmp_path / "agent-models.json")}
    set_saved_default_model_ref("openai/gpt-4.1-mini", env)
    monkeypatch.setenv("TERRAFIN_AGENT_MODELS_PATH", env["TERRAFIN_AGENT_MODELS_PATH"])

    reset_hosted_agent_loop()
    try:
        loop = get_hosted_agent_loop()
        assert loop.model_client.default_model.model_ref == "openai/gpt-4.1-mini"

        set_saved_default_model_ref("google/gemini-3.1-pro-preview", env)

        loop = get_hosted_agent_loop()
        assert loop.model_client.default_model.model_ref == "google/gemini-3.1-pro-preview"
        assert loop.runtime.default_runtime_model is not None
        assert loop.runtime.default_runtime_model.model_ref == "google/gemini-3.1-pro-preview"
    finally:
        reset_hosted_agent_loop()


def test_hosted_agent_loop_uses_shared_state_dir_for_session_db(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TERRAFIN_STATE_DIR", str(tmp_path / "state"))
    reset_hosted_agent_loop()
    try:
        loop = get_hosted_agent_loop()
        assert loop.runtime.session_store.db_path == tmp_path / "state" / "hosted_agent_sessions.sqlite3"
    finally:
        reset_hosted_agent_loop()
