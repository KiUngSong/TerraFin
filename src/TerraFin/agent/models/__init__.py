"""LLM model layer for TerraFin agents.

Also re-exports Pydantic DTOs from agent.contracts.schemas for back-compat with
the pre-refactor `from TerraFin.agent.models import ...` import path.
"""

from ..contracts.schemas import *  # noqa: F401, F403
from .management import (
    DEFAULT_OPENAI_MODEL_REF,
    MODEL_STATE_PATH_ENV,
    TerraFinProviderCatalogEntry,
    build_provider_auth_status,
    get_provider_catalog,
    get_saved_default_model_ref,
    get_saved_provider_credentials,
    list_provider_catalog,
    load_model_state,
    mask_secret,
    resolve_current_model_preference,
    resolve_model_state_path,
    resolve_provider_secret,
    save_model_state,
    set_saved_default_model_ref,
    set_saved_provider_credentials,
)
from .runtime import (
    TerraFinModelConfigError,
    TerraFinModelProvider,
    TerraFinModelProviderRegistry,
    TerraFinModelResponseError,
    TerraFinProviderRoutedModelClient,
    TerraFinRuntimeModel,
)
