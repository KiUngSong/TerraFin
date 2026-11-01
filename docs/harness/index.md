---
title: Agent harness
summary: What TerraFin's own hosted agent is for, its components, where each lives, and how they connect.
read_when:
  - Learning how TerraFin's hosted agent is built
  - Finding which module owns a part of the hosted runtime
---

# Agent harness

The harness is TerraFin's own agent: a model loop that runs in the TerraFin
server and answers from the chat widget on every page. It calls the same
capabilities that external agents use as [skills](../skills/index.md). Both
read from one capability registry in `src/TerraFin/agent/runtime/capability.py`.

## What it adds to the skills

An external agent that installs the skill brings its own model and loop.
Someone using the TerraFin web app has neither. The harness supplies them,
plus what only a hosted agent can have: the page the user is looking at, a
transcript that survives a reload, background tasks, approvals for actions with side effects, and investor-persona
sub-agents.

Because the tools are the registry's capabilities, a fix to a capability
reaches the skill and the harness at once. There is no second, agent-only
data path.

## Components at a glance

All paths are under `src/TerraFin/`.

```text
 Browser: chat widget and page view context    interface/frontend/src/agent/
   |
   v
 HTTP routes /agent/api/runtime/*              interface/agent/data_routes.py
   |
   v
 Turn loop                                     agent/runtime/loop.py
   |-- turn hooks, pinned context              agent/runtime/hooks.py
   |-- prompt shaping                          agent/runtime/context_budget.py
   |                                           agent/runtime/transcript_normalizer.py
   |-- model providers                         agent/models/
   |-- tool batch runner                       agent/runtime/tool_batch.py
   |-- tools                                   agent/tools/, agent/contracts/
   |     |-- personas (sub-agents)             agent/guru/
   |     `-- runtime: policy, approvals, tasks agent/runtime/hosted.py
   |           |-- task records, TaskContext   agent/runtime/tasks.py
   |           `-- capability registry         agent/runtime/capability.py
   |-- recovery                                agent/runtime/recovery.py
   `-- storage: transcript and session record  agent/storage/
```

The loop is wired once per process in `agent/service/hosted.py`. The
step-by-step turn is on [The agent loop](loop.md). The sections below say
what each component does and what it hands to the next.

## Capability registry and tool layer

**What it does.** Turns registered capabilities into model tools, checks the
model's arguments against each tool's input schema, runs the call, and
returns a tool result marked as success, retryable error or fatal error.

**Where it lives.** `agent/runtime/capability.py` (the registry),
`agent/contracts/tool_contracts.py` (input schemas), `agent/tools/` (the
adapter that builds the tool list and the engine that runs a call).

Each capability says whether it has side effects and whether it can run in
the background. The tool list for an agent holds one tool per allowed
capability, a `start_<capability>_task` tool for capabilities that can run in
the background, `current_view_context`, `read_tool_result`, and the
`consult_<persona>` tools for the public agent.

**Connects to.** The loop asks for tools each step and hands each tool call
to the tool layer. The tool layer calls the runtime for capabilities and
view context, or the loop for persona consults.

## Turn loop

**What it does.** Runs one user turn: model call, tool batch, repeat, until
the model answers without tool calls or a limit or recovery rule ends the
turn. It also holds the default system prompt.

**Where it lives.** `agent/runtime/loop.py`.

**Connects to.** Everything else on this page. Full walk-through:
[The agent loop](loop.md).

A reply on the last step carries `turnEnding`, unless it only finishes a
continued reply. A reply still cut at the output limit after the loop stops
continuing it, and the reply of a stopped turn, carry one too. Its value is
`step_limit`, `length` or `interrupted`. A fallback message carries one only
when the turn was stopped. The last step runs with tools off and asks for an
answer from the results in hand. Details:
[Turn endings](loop.md#5-turn-endings).

## Turn hooks and pinned context

**What it does.** Lets a fixed list of in-repo hooks add context to a turn or
observe it. A hook never gates a turn. A hook that raises is logged and
skipped.

**Where it lives.** `agent/runtime/hooks.py` (`TerraFinTurnHook`,
`default_turn_hooks`). The default list is empty. A loop built with `hooks=`
runs the hooks it is given.

A hook can implement any of these:

- `before_turn` runs before the user's message is appended. Its return value
  is the hook's state for the turn.
- `pinned_context` returns text for one model request. It runs before every
  model call of the turn.
- `after_tool` runs after each tool result is appended.
- `after_completion` runs once per delivered background task.
- `owned_metadata_tags` names the messages the hook re-adds each turn. The
  loop drops them before `before_turn`, and they do not count toward the
  session's message cap.

**Pinned context** is sent with the system text of that one request
(`TerraFinTurnOptions.pinned_context`). It is never written to the
transcript, so the context budget can never cut it.

**Connects to.** The loop calls the hooks. Each provider adds the pinned text
to its system instructions.

## Tool batch runner

**What it does.** Runs and answers every tool call of one model reply, in the
order the model gave them.

**Where it lives.** `agent/runtime/tool_batch.py` (`run_tool_batch`). The main
loop and the persona worker both use it.

- It enforces the tool-call cap and the loop guard, and answers calls from a
  cut-off reply without running them.
- It checks the stop flag before each call.
- Any early exit gives every unanswered call a `tool_call_unresolved` result.
- Parallel runs are off by default. `max_parallel_tool_calls` on the loop is 1.
  Above 1, consecutive read-only calls share threads, and results are still
  appended in call order.

**Connects to.** The loop hands it each reply's tool calls. It hands each call
to the tool layer and each result to the hooks' `after_tool`.

## Context budget and transcript normalization

**What it does.** Builds the message list the model sees, small enough to fit
and well formed.

**Where it lives.** `agent/runtime/context_budget.py` and
`agent/runtime/transcript_normalizer.py`.

The normalizer repairs tool calls and results that lost their partner, and
drops empty assistant messages.

The budget manager picks one of four levels, from `full` (the whole
transcript) to `minimal`:

- With a `context_window` in the model's metadata, the budget is that window
  less a reserve. The prompt size comes from the provider's own token count on
  the last `full` reply.
- Without one, the budget and the size are estimates.
- If the provider still rejects the prompt as too long, the loop retries at
  tighter levels.

Below `full`, a long tool result is cut and ends with a pointer. The model
reads the exact text in slices with `read_tool_result(call_id, offset,
limit)`.

**Connects to.** The loop asks the budget manager for the prepared messages
before each model call. The stored transcript is never shortened. Only the
copy sent to the model is.

## Sessions, background tasks and the dispatcher

**What it does.** Keeps each chat's state, runs long capabilities off the
turn, and brings their results back.

**Where it lives.**

- `agent/runtime/hosted.py`: the runtime. It creates sessions, runs
  capabilities directly or as tasks, enforces policy, manages approvals, and
  owns the dispatcher thread and worker pool.
- `agent/runtime/tasks.py`: task records and their status, and
  `TerraFinTaskContext`, a handler's view of its own task.
- `agent/storage/session_store.py`: the session record, its tasks,
  approvals, audit log and view contexts, task checkpoints and stop requests,
  in SQLite.
- `agent/storage/transcript_store.py`: one append-only JSONL transcript per
  session.

Both stores live under TerraFin's state directory unless
`TERRAFIN_AGENT_SESSION_DB_PATH` or `TERRAFIN_AGENT_TRANSCRIPT_DIR` points
elsewhere.

A handler that takes a `task` argument gets a `TerraFinTaskContext`:

- `heartbeat(stage)` renews the task's lease and shows the stage.
- `cancelled()` says whether the user cancelled the task.
- `load_checkpoint()` and `save_checkpoint(payload)` keep resume state.
- `call(name, ...)` runs another capability for the task.
- `model_turn` is the loop's model call, with the same prompt budget.

The dispatcher also renews the lease of every task it is running. A task
whose worker is lost is claimed again, up to 3 attempts.

**Connects to.** The loop appends every message to the transcript and writes
conversation metadata to the session record. The dispatcher claims pending
tasks and runs them. The widget reads their status from the session's tasks
route and cancels one with `POST /agent/api/runtime/tasks/{id}/cancel`. A
completed task is delivered to the next turn as a note that carries its
result. A task that fails after losing its worker 3 times (`restart_limit`)
gets a note that says it failed. Details:
[Background tasks](loop.md#background-tasks).

## Stop

**What it does.** Lets the user stop a running turn.

**Where it lives.** `POST /agent/api/runtime/sessions/{id}/interrupt` in
`interface/agent/data_routes.py` records a stop request in the session store.

- The loop reads it before each step and before each tool call.
- Calls not yet started get a "not run" result.
- A model call already running is not aborted.
- The next step is the last. It answers with tools off, and the reply carries
  `turnEnding: "interrupted"`.
- Recovery is still judged on the calls that ran. If it says stop, the turn
  ends with the fallback message, marked `interrupted`, and no last step runs.

**Connects to.** The widget's Stop button. Details: [Stop](loop.md#stop).

## Model providers and model management

**What it does.** Sends the prepared messages and tool list to a model and
returns the assistant text and tool calls.

**Where it lives.** `agent/models/`. The model client routes each session to
its pinned model's provider. Providers live in `agent/models/providers/`.
OpenAI, Google and Anthropic are registered (`agent/service/hosted.py`). Each
reports a reply cut at the output limit as stop reason `length`. Each passes
on the token usage the provider reports for a reply.

**Connects to.** The loop calls the model client once per step. Choosing a
provider and model: [Model management](../agent/models.md).

## Approvals and policy

**What it does.** Decides whether a tool call may run, and holds side
effects until a person approves them.

**Where it lives.** `agent/runtime/hosted.py`.

- Policy denies a capability the agent does not allow, a chart for an agent
  without chart access, and a background task where the agent or capability
  does not allow one. Each decision goes to the session's audit log.
- The hosted agent requires approval for side-effecting capabilities and not
  for background tasks. A session can override either at creation.
- The first call creates a pending approval. The model sees it as a normal
  tool result with `approvalRequired: true`, not as an error. Once a person
  approves it (`POST /agent/api/runtime/approvals/{id}/approve`), the next
  identical call runs.

**Connects to.** The runtime checks policy before any capability runs.

## Recovery

**What it does.** Ends a turn with a plain apology when the tools keep
failing, instead of looping until the step limit.

**Where it lives.** `agent/runtime/recovery.py`.

**Connects to.** The loop records each batch that had a retryable error,
once per batch. Three failing batches in a turn, or the same error in two
batches, stop the turn, and the loop answers with a fallback message.

## Personas as sub-agents

**What it does.** Lets the main agent ask Warren Buffett, Howard Marks or
Stanley Druckenmiller personas for a structured memo, then write its own
answer from the memos.

**Where it lives.** `agent/guru/`. A consult creates a hidden child session
and runs a short model loop in it that must end with a memo. Each persona's
allowed capabilities come from its YAML file in `agent/guru/personas/`.

**Connects to.** The tool layer routes `consult_<persona>` calls to the loop.
The memo returns as that call's tool result. Persona sessions get no
`consult_*` tools, so they cannot recurse. Deleting the parent session
deletes its hidden children. Diagrams of both loops:
[Agent architecture](../agent/architecture.md).

## View context

**What it does.** Tells the agent what the user is looking at: route, page
type, selection and entities, such as the ticker on screen or the filing
section open in the reader.

**Where it lives.**

- The frontend (`interface/frontend/src/agent/`) publishes the page state
  with `PUT /agent/api/runtime/view-contexts/{id}`.
- The runtime stores it and links it to the session.
- The message route re-links the session to the current view context before
  every turn, so the agent reads the live page, not the one open when the
  chat started.

**Connects to.** The model calls the read-only `current_view_context` tool
when the user says "this stock". Persona sessions read the parent's view
context.

## HTTP and widget surface

**What it does.** Exposes the harness to the browser and to scripts.

**Where it lives.**

- `interface/agent/data_routes.py`: the `/agent/api/runtime/*` routes for
  agents, sessions, messages, stop, view contexts, tasks and approvals.
- `agent/runtime/inflight.py`: a per-session lock. A second turn on the same
  chat while one is running gets HTTP 409 with code
  `hosted_agent_turn_in_flight`.
- `interface/frontend/src/agent/`: the chat panel. It manages sessions, sends
  and stops messages, polls and cancels tasks, lets the user approve or deny,
  and shows each turn's tool calls.
- `agent/service/client.py`: `TerraFinAgentClient` calls the same routes, or
  the loop in-process.

**Connects to.** The loop. The endpoint list and browser behavior are in
[Hosted runtime](../agent/hosted-runtime.md).

## Read next

- [The agent loop](loop.md): one turn, step by step.
- [Hosted runtime](../agent/hosted-runtime.md): endpoints, transcript format,
  regression surfaces.
- [Agent architecture](../agent/architecture.md): capability layer and
  persona sub-agent diagrams.
- [Model management](../agent/models.md): choosing a provider and model.
