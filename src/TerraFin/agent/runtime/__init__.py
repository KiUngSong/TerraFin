"""Runtime subpackage: in-process session/capability/task data model plus
the hosted-runtime orchestrator and the conversational loop machinery.

Modules:
    artifacts            - artifact + capability-call dataclasses, helpers.
    focus                - per-capability focus extractors / artifact builders.
    tasks                - TerraFinTaskRecord + thread-safe TerraFinTaskRegistry.
    session              - TerraFinAgentSession + snapshot.
    capability           - TerraFinCapability(Registry) + default-registry builder.
    context              - TerraFinAgentContext + create_agent_context.
    errors               - hosted-runtime exception types.
    async_tasks          - internal _AsyncTaskHandle for the dispatcher pool.
    hosted               - TerraFinHostedAgentRuntime (top-level orchestrator).
    loop                 - TerraFinHostedAgentLoop + model-client integration.
    context_budget       - prompt-budget retry levels + ContextBudgetManager.
    recovery             - RecoveryPolicy + RecoveryTracker.
    transcript_normalizer - TranscriptNormalizer.

Public surface preserved for backwards-compatibility with the previous flat
`agent.runtime` and `agent.hosted_runtime` modules: every symbol exposed by
those files is re-exported here.

Import order in this `__init__` matters: low-level data modules
(artifacts/session/capability/context/tasks) must finish loading BEFORE
`hosted` is imported, because `runtime.hosted` -> `storage.session_store`
-> `agent.runtime` triggers a re-entry into this package while it's still
loading. By the time the storage layer re-imports `agent.runtime`, the
symbols it needs are already bound on the package namespace.
"""

# Layer 1: pure data types and helpers - no agent-internal deps.
from .artifacts import (
    ArtifactBuilder,
    ArtifactKind,
    CapabilityHandler,
    FocusExtractor,
    TerraFinArtifact,
    TerraFinCapabilityCall,
    _dedupe,
    _utc_now,
)
from .tasks import (
    TaskStatus,
    TerraFinTaskRecord,
    TerraFinTaskRegistry,
    _is_terminal_task_status,
)
from .session import TerraFinAgentSession, TerraFinAgentSessionSnapshot

# Layer 2: capability registry + agent context (depend on layer 1; reach into
# ..service / ..tasks lazily inside the default-registry builder to avoid
# pulling the service layer at package-import time).
from .capability import (
    TerraFinCapability,
    TerraFinCapabilityRegistry,
    build_default_capability_registry,
)
from .context import TerraFinAgentContext, create_agent_context

# Layer 3: hosted runtime errors + async helpers (no behavioural deps).
from .async_tasks import _AsyncTaskHandle
from .errors import (
    TerraFinAgentApprovalRequiredError,
    TerraFinAgentPolicyError,
    TerraFinAgentSessionConflictError,
)

# Layer 4: hosted-runtime orchestrator. Triggers a load of
# `..storage.session_store`, which imports back from `..runtime`. The symbols
# it needs are already bound on the package namespace above, so the re-entry
# succeeds.
from .hosted import TerraFinHostedAgentRuntime

# Layer 5: conversational loop + supporting modules. These import from
# `.contracts.*` and `.tools` (which themselves import from this package),
# so they must come after the hosted orchestrator is bound.
from .recovery import RecoveryPolicy, RecoveryTracker
from .transcript_normalizer import TranscriptNormalizer
from .context_budget import (
    DEFAULT_AGGRESSIVE_MODEL_MESSAGE_WINDOW,
    DEFAULT_AGGRESSIVE_TEXT_MESSAGE_CHAR_BUDGET,
    DEFAULT_AGGRESSIVE_TOOL_MESSAGE_CHAR_BUDGET,
    DEFAULT_ESTIMATED_PROMPT_TOKEN_BUDGET,
    DEFAULT_MINIMAL_MODEL_MESSAGE_WINDOW,
    DEFAULT_MINIMAL_TEXT_MESSAGE_CHAR_BUDGET,
    DEFAULT_MINIMAL_TOOL_MESSAGE_CHAR_BUDGET,
    DEFAULT_MODEL_MESSAGE_WINDOW,
    DEFAULT_TEXT_MESSAGE_CHAR_BUDGET,
    DEFAULT_TOOL_MESSAGE_CHAR_BUDGET,
    PROMPT_BUDGET_RETRY_LEVELS,
    ContextBudgetManager,
    PromptBudgetLevel,
    is_prompt_budget_error,
    truncate_text,
)
from .loop import (
    CONVERSATION_STATE_METADATA_KEY,
    TerraFinConversationMessage,
    TerraFinHostedAgentLoop,
    TerraFinHostedConversation,
    TerraFinHostedModelClient,
    TerraFinHostedRunResult,
    TerraFinModelTurn,
    TerraFinToolCall,
    build_default_system_prompt,
)


__all__ = [
    # artifacts
    "ArtifactBuilder",
    "ArtifactKind",
    "CapabilityHandler",
    "FocusExtractor",
    "TerraFinArtifact",
    "TerraFinCapabilityCall",
    # tasks (runtime task registry, distinct from agent.tasks)
    "TaskStatus",
    "TerraFinTaskRecord",
    "TerraFinTaskRegistry",
    # session / context
    "TerraFinAgentSession",
    "TerraFinAgentSessionSnapshot",
    "TerraFinAgentContext",
    "create_agent_context",
    # capability
    "TerraFinCapability",
    "TerraFinCapabilityRegistry",
    "build_default_capability_registry",
    # hosted-runtime
    "TerraFinAgentApprovalRequiredError",
    "TerraFinAgentPolicyError",
    "TerraFinAgentSessionConflictError",
    "TerraFinHostedAgentRuntime",
    # loop + supporting
    "CONVERSATION_STATE_METADATA_KEY",
    "TerraFinConversationMessage",
    "TerraFinHostedAgentLoop",
    "TerraFinHostedConversation",
    "TerraFinHostedModelClient",
    "TerraFinHostedRunResult",
    "TerraFinModelTurn",
    "TerraFinToolCall",
    "build_default_system_prompt",
    "RecoveryPolicy",
    "RecoveryTracker",
    "TranscriptNormalizer",
    # context budget
    "PROMPT_BUDGET_RETRY_LEVELS",
    "PromptBudgetLevel",
    "ContextBudgetManager",
    "is_prompt_budget_error",
    "truncate_text",
    "DEFAULT_MODEL_MESSAGE_WINDOW",
    "DEFAULT_AGGRESSIVE_MODEL_MESSAGE_WINDOW",
    "DEFAULT_MINIMAL_MODEL_MESSAGE_WINDOW",
    "DEFAULT_TOOL_MESSAGE_CHAR_BUDGET",
    "DEFAULT_AGGRESSIVE_TOOL_MESSAGE_CHAR_BUDGET",
    "DEFAULT_MINIMAL_TOOL_MESSAGE_CHAR_BUDGET",
    "DEFAULT_TEXT_MESSAGE_CHAR_BUDGET",
    "DEFAULT_AGGRESSIVE_TEXT_MESSAGE_CHAR_BUDGET",
    "DEFAULT_MINIMAL_TEXT_MESSAGE_CHAR_BUDGET",
    "DEFAULT_ESTIMATED_PROMPT_TOKEN_BUDGET",
]
