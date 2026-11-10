---
title: The agent loop
summary: The shape of one turn of TerraFin's own agent, from the user's message to the reply, and what each step can end in.
read_when:
  - Debugging a turn of TerraFin's own agent that stopped, failed or looped
  - Changing the turn loop, tool execution, recovery or background tasks
---

# The agent loop

All paths are under `src/TerraFin/`.

TerraFin has its own agent: the chat panel in the TerraFin web app, served by
the runtime in `agent/`.

- This page follows one turn of that agent, from the user's message to the reply.
- It does not apply when you call TerraFin's skills from your own agent.
- Components are described on [Agent harness](index.md).

The loop lives in `agent/runtime/loop.py`
(`TerraFinHostedAgentLoop.submit_user_message`).

- A turn appends the user's message, then repeats one step: call the model,
  run the tools it asked for.
- It stops when the model answers in plain text, recovery ends the turn, or a
  limit is hit.
- The limits are constructor arguments on the loop class: `max_steps` 8,
  `max_tool_calls` 24, `max_messages_per_session` 200,
  `max_parallel_tool_calls` 1.
- More limits are on `RecoveryPolicy` in `agent/runtime/recovery.py`.

## Flow

??? info "Diagram: a turn"

    ```mermaid
    flowchart TD
        route["<b>HTTP route</b><br/>check model, relink view context,<br/>claim the turn"]
        route -- no model --> e503(["503"])
        route -- turn running --> e409(["409"])
        route --> submit["<b>submit_user_message</b><br/>check message cap, deliver finished<br/>background tasks, run before_turn hooks,<br/>append user message"]
        submit --> step["<b>Step</b>, up to max_steps<br/>check the stop flag, list tools,<br/>collect pinned context"]
        step --> last{"Last step?<br/>max_steps or stopped"}
        last -- no --> model["Call the model"]
        last -- yes --> wrap["Call the model with tools off<br/>and the wrap-up note, unless it<br/>continues a cut-off reply"]
        model --> calls{"Tool calls?"}
        calls -- "no, cut off at the<br/>output limit (up to 2 times)" --> cont["Append a continue note"] --> step
        calls -- "no, with text<br/>(a 3rd cut adds<br/>turnEnding length)" --> done(["Return the answer"])
        calls -- no, no text --> empty(["Raise: empty reply"])
        calls -- yes --> batch["Run the tool batch<br/>(next chart)"]
        batch -- recovery says stop --> fb1(["Fallback message"])
        batch -- fatal error or cap --> fail1(["Raise"])
        batch -- "ask_user succeeded" --> ask(["Return the question,<br/>with its options"])
        batch -- all answered, or stopped --> step
        wrap --> text{"Text?"}
        text -- yes --> ending(["Return the answer, with turnEnding<br/>unless it finished a<br/>continued reply"])
        text -- "no, tools asked" --> stopped{"Stopped?"}
        text -- "no, no tools" --> empty
        stopped -- yes --> stoptext(["Stopped reply"])
        stopped -- no --> any{"Any retryable<br/>error?"}
        any -- yes --> fb2(["Fallback message"])
        any -- no --> fail2(["Raise"])

        classDef ok fill:#2e7d3240,stroke:#2e7d32,stroke-width:2px
        classDef bad fill:#c6282840,stroke:#c62828,stroke-width:2px
        classDef soft fill:#ef6c0040,stroke:#ef6c00,stroke-width:2px
        class done,ask ok
        class e503,e409,empty,fail1,fail2 bad
        class fb1,fb2,ending,stoptext soft
    ```

??? info "Diagram: each tool call in the batch"

    ```mermaid
    flowchart TD
        stop{"Stop asked?"}
        stop -- yes --> unrun["Answer this call and every<br/>later one as not run"] --> judge
        stop -- no --> cap{"Over the<br/>tool-call cap?"}
        cap -- yes --> close["Close open calls"] --> fail(["Raise"])
        cap -- no --> cut{"Reply cut off at<br/>the output limit?"}
        cut -- yes --> trunc["tool_arguments_truncated<br/>result"]
        cut -- no --> dup{"Same call a<br/>3rd time?"}
        dup -- yes --> guard["Loop-guard result"]
        dup -- no --> exec["Execute"]
        exec -- fatal_error --> close
        exec -- success or<br/>retryable_error --> append["Append tool result,<br/>run after_tool hooks"]
        guard --> append
        trunc --> append
        append --> more{"More calls?"}
        more -- yes --> stop
        more -- no --> judge{"Retryable error and<br/>recovery says stop?"}
        judge -- yes --> fb(["Fallback message"])
        judge -- no --> asked{"ask_user<br/>succeeded?"}
        asked -- yes --> question(["Turn ends with<br/>the question"])
        asked -- "no, stopped" --> halted(["Batch ends.<br/>The next step is the last."])
        asked -- "no, not stopped" --> next(["Next step"])

        classDef ok fill:#2e7d3240,stroke:#2e7d32,stroke-width:2px
        classDef bad fill:#c6282840,stroke:#c62828,stroke-width:2px
        classDef soft fill:#ef6c0040,stroke:#ef6c00,stroke-width:2px
        class next,question ok
        class fail bad
        class fb,halted soft
    ```

## Before the loop

The HTTP route for a new message (`interface/agent/data_routes.py`)
runs first:

- It fails with 503 if no model provider is configured.
- It points the session at the page the user is looking at, so tools that read
  the view see the live page.
- It then claims the turn with a per-session lock (`agent/runtime/inflight.py`).
- **A second turn on the same chat gets 409** with code
  `hosted_agent_turn_in_flight`.
- The claim is released when the turn ends, whether it succeeded or not.

`submit_user_message` then does four things in order:

1. **Message cap.** It loads the conversation and checks the session message
   cap. Messages a hook re-adds each turn do not count.
2. **Finished background tasks.** Each task that finished since the last turn
   is delivered as one internal note. See [Background tasks](#background-tasks).
3. **Turn hooks.** It drops the messages hooks added last turn, then runs
   every hook's `before_turn` (`agent/runtime/hooks.py`).
4. **User message.** It appends the user's message.

## One step

### 1. Stop check, tools and prompt

Each step first reads the session's stop flag. A stop asked for during this
turn makes this step the last. A model call already running is never aborted.

The tool list is rebuilt every step from the session's agent definition
(`agent/tools/adapter.py`).

**Pinned context.** Before every model call, each hook's `pinned_context`
returns text for that one request.

- The provider adds the pinned text to the system text
  (`TerraFinTurnOptions.pinned_context` in `agent/contracts/model_client.py`).
- The pinned text is never written to the transcript.

**Context budget.** The prompt is built by `ContextBudgetManager`
(`agent/runtime/context_budget.py`). It has four levels, `full`, `default`,
`aggressive` and `minimal`:

- `full` sends the whole normalized transcript, uncut.
- Each later level keeps fewer older messages and cuts them shorter.
- The current turn, from the user's message on, is always sent.

The manager picks the first level that fits the budget:

- When the session's model metadata carries a `context_window`, the budget is
  that window minus a reserve (15%, at least 16,000 tokens). The size of a
  `full` prompt is then measured from the provider's own token count on the
  last `full` reply, plus an estimate of the messages after it.
- Otherwise the budget is a fixed estimate of 52,000 tokens, and the size is
  estimated from characters.

When the provider rejects the prompt:

- If it rejects the prompt as too long, the loop retries at the tighter levels
  only.
- If every level is rejected, the turn fails and asks the user to start a new
  chat.
- Any other model error fails the turn at once.

**Spill by pointer.** Below `full`, a long tool result is cut to its head and
tail and ends with a pointer:
`[full result: call_id=..., N chars; read_tool_result(call_id, offset, limit)]`.

- The model calls `read_tool_result` to read the exact text in slices.
- A slice it asked for is sent whole at every level but `minimal`.
- The stored transcript keeps every result in full.

The model client (`agent/models/runtime.py`) reads the model pinned on the session
and routes the call to that provider. Each reply records the provider's token
usage and the level its prompt was sent at.

### 2. Model reply

- **Text** is appended as an assistant message and becomes the turn's final
  message.
- **Tool calls** are appended as one internal `tool_use` message before any
  call runs.
- **No tool calls** ends the turn. The loop returns the final message, every
  message added this turn, the tool results and the step count. The final
  reply carries `turnTokenUsage`, the token usage of every model call in the
  turn.
- **No text and no tool calls** fails the turn as an empty reply.

### 3. Tool batch

`run_tool_batch` (`agent/runtime/tool_batch.py`) runs and answers every call
in the batch, in the order the model gave them. The guru worker uses the same
runner.

**Parallel runs.** A run of consecutive read-only calls can share threads,
up to `max_parallel_tool_calls`.

- `max_parallel_tool_calls` is 1 by default, so calls run one after another.
- Results are appended in call order either way.

For each call:

1. **Stop check.** If the user asked to stop, this call and every later one
   get a `tool_call_unresolved` result saying it was not run. The batch ends,
   and the next step is the last. Recovery is still judged on the calls that
   ran. If it says stop, the turn ends with the fallback message, marked
   `interrupted`, and no last step runs.
2. **Tool-call cap.** A count across the whole turn. Past the cap, the turn
   fails.
3. **Cut-off reply.** If the reply that asked for the calls was cut at the
   output limit, its arguments may be truncated. No call runs. Each gets a
   retryable `tool_arguments_truncated` result asking for smaller arguments.
4. **Loop guard.** A call is identified by tool name plus arguments. The
   third identical call in one turn is not run. It gets a
   `tool_call_loop_guard` result telling the model to change tool, change
   arguments, or answer. It does not count toward recovery.
5. **Execute.** `ToolExecutionEngine` (`agent/tools/execution.py`) runs the tool
   through the adapter, which validates arguments and classifies failures.

After each result is appended, every hook's `after_tool` runs.

| Outcome | When | What the loop does |
|---|---|---|
| `success` | The tool returned, including loop-guard and approval-required results | Appends the result |
| `retryable_error` | The tool returned an error the model can fix, such as bad arguments or an unresolved ticker | Appends the result with the error and a hint, and records it for recovery |
| `fatal_error` | The tool raised: unknown tool, policy denial, upstream failure, any unclassified exception | Fails the turn |

**Approval.** A call that needs human approval returns a normal result with
`approvalRequired: true`.

- The model can tell the user.
- After the user approves, the next identical call runs.
- Rules: [Approvals and policy](index.md#approvals-and-policy).

**Closing open calls.** If anything ends the batch early (a fatal error, the
tool-call cap, an interrupt), every call in the batch that has no result gets
a `tool_call_unresolved` result before the error propagates. A stored
`tool_use` with no result would read as an interrupted turn.

### 4. Recovery

`RecoveryTracker` (`agent/runtime/recovery.py`) counts failing batches, once
per batch however many of its calls failed.

- After every call in the batch has its result, the loop asks the tracker.
- **Three failing batches in a turn, or the same error in two batches, stop
  the turn.**
- The loop then appends a fallback message asking the user to name a ticker or
  keep the relevant page open, and returns it as the final message.
- Otherwise the model sees the error results on the next step and can try
  again.

### 5. Asking the user

- **What it does:** shows the user one question with 2 to 4 options.
- **Who gets it:** the user-facing agent only, never a hidden persona session.
- **Rejected:** a blank question, more than 4 options, or fewer than 2 that
  differ after trimming. The model gets a retryable error.
- **Call it alone:** the description says so, because other calls in the same
  step run before the user answers. No code enforces it.
- **The turn ends:** after a batch in which `ask_user` succeeded, the loop runs
  no further step. It returns an assistant reply whose text is the question and
  whose `askUser` metadata holds the question and the options.
- **In the chat panel:** each option is a button under the latest such reply,
  with a note that the user can type their own answer.
- **The answer:** a click sends the option as the user's next message, which
  starts a normal turn. Nothing pauses, so an unanswered question just waits.

### 6. Turn endings

These replies carry `turnEnding`:

- a reply on the last step, unless it only finishes a continued reply
- a reply still cut at the output limit after the loop stops continuing it
- the reply of a stopped turn
- a fallback message, only when the turn was stopped

The chat panel shows a line under that reply.

| `turnEnding` | When | What the last step does |
|---|---|---|
| `step_limit` | The step is the last of `max_steps` | Tools are off, and a pinned wrap-up note asks for an answer from the results in hand: what is established, what is missing, what to fetch next. Tool calls in the reply are dropped unrun. |
| `length` | The reply was cut at the output limit and not continued | The loop continues a cut text reply up to 2 times with an internal note: "continue exactly where it stopped". The parts are joined in the returned answer. The transcript keeps each part. A reply still cut after 2 continuations, or cut on the last step, ends the turn with `length`. A last step that continues a cut reply has tools off and no wrap-up note. |
| `interrupted` | The user pressed Stop during the turn | The next step is the last: tools off, with the wrap-up note. If that step writes no text, the reply is "Stopped at your request before an answer was written." |

Every provider reports a cut-off reply as stop reason `length`: OpenAI's
`max_output_tokens`, Google's `MAX_TOKENS`, and Anthropic's `max_tokens`.

### 7. Out of steps

If the last step still asked for tools and wrote no text, the turn ends with
the same fallback message when any retryable error happened, and fails
otherwise.

## Stop

`POST /agent/api/runtime/sessions/{id}/interrupt` records a stop for the
session in the session store. The route records it only while a turn may be
running, and answers `interruptRequested: false` otherwise.

The running turn reads the flag at two points:

- before each step
- before each tool call, or each parallel run of calls

Only a stop asked for after the turn started counts, so a stop left by an
earlier turn never ends the next one.

## Background tasks

A capability marked `backgroundable` also appears as a
`start_<capability>_task` tool when the agent definition allows background
tasks. The default agent does.

- The tool creates a `pending` task on the session and returns its `taskId`
  right away.
- The turn does not wait.
- A dispatcher thread in `agent/runtime/hosted.py` claims pending tasks with a
  lease and runs them on a worker pool.
- The widget reads task status from the session's tasks route
  (`/agent/api/runtime/sessions/{id}/tasks`).

**The task's own view.** A handler that takes a `task` argument gets a
`TerraFinTaskContext` (`agent/runtime/tasks.py`):

- `heartbeat(stage)` renews the lease and sets `progress.stage`.
- `cancelled()` says whether the user cancelled the task.
- `load_checkpoint()` and `save_checkpoint(payload)` keep resume state in the
  session store, apart from `progress`.
- `call(name, ...)` runs another capability for the task.
- `model_turn` is the loop's `complete_model_turn`, so a task's model calls
  get the same prompt budget.

The dispatcher also renews the lease of every task it is still running. A task
whose worker was lost is claimed again, up to 3 attempts, then fails with
`restart_limit`.

**Cancel.** `POST /agent/api/runtime/tasks/{id}/cancel` sets the task's cancel
event.

- A task not yet started never runs.
- A running handler stops at its next `cancelled()` check.

**Delivery.** A completed task leaves a pending completion on the session. The
next turn appends it, before the user's message, as one internal user note:

- The note gives a pointer first: `read_tool_result(task_id="...")` reads the
  full result.
- Then a bounded summary. For a [deep research](deep-research.md) report it
  lists the title, the status, counts and the report's first 1,500 characters.
- A task that fails after losing its worker 3 times (`restart_limit`) gets a
  note that tells the model to say it failed.
- A task whose handler raises is marked failed in the task list. No note is
  delivered.

Then every hook's `after_completion` runs. The task's model token usage is
added to the session's `usageTotals`.

## What is saved

Two stores, wired in `agent/service/hosted.py`:

- **Transcript** (`agent/storage/transcript_store.py`): one JSONL file per session.
  Every message is written as it is appended.
- **Session record** (`agent/storage/session_store.py`): a SQLite row per session.
  It holds the tool-call history, the pinned model, tasks, approvals and the
  audit log. Task checkpoints and stop requests sit in their own tables.

Because each message is written when it is appended, a turn that fails leaves
everything up to the failure in the transcript, with every tool call closed.
