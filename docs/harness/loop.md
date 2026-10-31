---
title: The agent loop
summary: The shape of one turn of TerraFin's own agent, from the user's message to the reply, and what each step can end in.
read_when:
  - Debugging a turn of TerraFin's own agent that stopped, failed or looped
  - Changing the turn loop, tool execution, recovery or background tasks
---

# The agent loop

Package paths on this page drop the leading `src/TerraFin/`: `data/` means `src/TerraFin/data/`.

TerraFin has its own agent: the chat panel in the TerraFin web app, served by
the runtime in `agent/`. This page follows one turn of that
agent, from the user's message to the reply. It does not apply when you call
TerraFin's skills from your own agent. Components are described on
[Agent harness](index.md).

The loop lives in `agent/runtime/loop.py`
(`TerraFinHostedAgentLoop.submit_user_message`). A turn appends the user's
message, then repeats one step (call the model, run the tools it asked for)
until the model answers in plain text, recovery ends the turn, or a limit is
hit. The limits are constructor arguments on the loop class and on
`RecoveryPolicy` in `agent/runtime/recovery.py`.

## Flow

??? info "Diagram: a turn"

    ```mermaid
    flowchart TD
        route["<b>HTTP route</b><br/>check model, relink view context,<br/>claim the turn"]
        route -- no model --> e503(["503"])
        route -- turn running --> e409(["409"])
        route --> submit["<b>submit_user_message</b><br/>load conversation, check message cap,<br/>append user message"]
        submit --> step["<b>Step</b>, up to max_steps<br/>list tools, call the model,<br/>append its reply"]
        step --> calls{"Tool calls?"}
        calls -- no --> done(["Return the answer"])
        calls -- yes --> batch["Run each tool call<br/>(next chart)"]
        batch -- recovery says stop --> fb1(["Fallback message"])
        batch -- fatal error or cap --> fail1(["Raise"])
        batch -- all ran --> left{"Steps left?"}
        left -- yes --> step
        left -- no --> any{"Any retryable<br/>error?"}
        any -- yes --> fb2(["Fallback message"])
        any -- no --> fail2(["Raise"])

        classDef ok stroke:#2e7d32,stroke-width:2px
        classDef bad stroke:#c62828,stroke-width:2px
        classDef soft stroke:#ef6c00,stroke-width:2px
        class done ok
        class e503,e409,fail1,fail2 bad
        class fb1,fb2 soft
    ```

??? info "Diagram: each tool call in the batch"

    ```mermaid
    flowchart TD
        cap{"Over the<br/>tool-call cap?"}
        cap -- yes --> close
        cap -- no --> dup{"Same call a<br/>3rd time?"}
        dup -- yes --> guard["Loop-guard result"]
        dup -- no --> exec["Execute"]
        exec -- fatal_error --> close["Close open calls"] --> fail(["Raise"])
        exec -- success or<br/>retryable_error --> append["Append tool result"]
        guard --> append
        append --> stop{"Retryable error and<br/>recovery says stop?"}
        stop -- yes --> fb(["Fallback message"])
        stop -- no --> next(["Next call"])

        classDef ok stroke:#2e7d32,stroke-width:2px
        classDef bad stroke:#c62828,stroke-width:2px
        classDef soft stroke:#ef6c00,stroke-width:2px
        class next ok
        class fail bad
        class fb soft
    ```

## Before the loop

The HTTP route for a new message (`interface/agent/data_routes.py`)
runs first. It fails with 503 if no model provider is configured. It points
the session at the page the user is looking at, so tools that read the view
see the live page. It then claims the turn with a per-session lock
(`agent/runtime/inflight.py`). A second turn on the same chat gets 409 with code
`hosted_agent_turn_in_flight`. The claim is released when the turn ends,
whether it succeeded or not.

`submit_user_message` loads the conversation, checks the session message cap,
and appends the user's message.

## One step

### 1. Tools and prompt

The tool list is rebuilt every step from the session's agent definition
(`agent/tools/adapter.py`).

The prompt is built by `ContextBudgetManager` (`agent/runtime/context_budget.py`).
It has three levels, `default`, `aggressive` and `minimal`. Each keeps fewer
recent messages and shortens them more. The manager picks the first level
whose estimated size fits its budget. If the provider still rejects the prompt
as too long, the loop retries at the other levels. If every level is
rejected, the turn fails and asks the user to start a new chat. Any other
model error fails the turn at once.

The model client (`agent/models/runtime.py`) reads the model pinned on the session
and routes the call to that provider.

### 2. Model reply

- **Text** is appended as an assistant message and becomes the turn's final
  message.
- **Tool calls** are appended as one internal `tool_use` message before any
  call runs.
- **No tool calls** ends the turn. The loop returns the final message, every
  message added this turn, the tool results and the step count.

### 3. Tool batch

Calls run one after another, in the order the model gave them. For each call:

1. **Tool-call cap.** A count across the whole turn. Past the cap, the turn
   fails.
2. **Loop guard.** A call is identified by tool name plus arguments. The
   third identical call in one turn is not run. It gets a
   `tool_call_loop_guard` result telling the model to change tool, change
   arguments, or answer. It does not count toward recovery.
3. **Execute.** `ToolExecutionEngine` (`agent/tools/execution.py`) runs the tool
   through the adapter, which validates arguments and classifies failures.

| Outcome | When | What the loop does |
|---|---|---|
| `success` | The tool returned, including loop-guard and approval-required results | Appends the result |
| `retryable_error` | The tool returned an error the model can fix, such as bad arguments or an unresolved ticker | Appends the result with the error and a hint, and records it for recovery |
| `fatal_error` | The tool raised: unknown tool, policy denial, upstream failure, any unclassified exception | Fails the turn |

**Approval.** A call that needs human approval returns a normal result with
`approvalRequired: true`. The model can tell the user. After the user
approves, the next identical call runs. Rules:
[Approvals and policy](index.md#approvals-and-policy).

**Closing open calls.** If anything ends the batch early (a fatal error, the
tool-call cap, an interrupt), every call in the batch that has no result gets
a `tool_call_unresolved` result before the error propagates. A stored
`tool_use` with no result would read as an interrupted turn.

### 4. Recovery

`RecoveryTracker` (`agent/runtime/recovery.py`) counts retryable errors in the turn.
Once there are too many, or the same error repeats, the loop stops at once. It
appends a fallback message asking the user to name a ticker or keep the
relevant page open, and returns it as the final message. Otherwise the model
sees the error results on the next step and can try again.

### 5. Out of steps

If every step used tool calls, the turn ends with the same fallback message
when any retryable error happened, and fails otherwise.

## Background tasks

A capability marked `backgroundable` also appears as a
`start_<capability>_task` tool when the agent definition allows background
tasks. The default agent does.

The tool creates a `pending` task on the session and returns its `taskId`
right away. The turn does not wait. A dispatcher thread in
`agent/runtime/hosted.py` claims pending tasks with a lease and runs them on a
worker pool. The widget reads task status from the session's tasks route
(`/agent/api/runtime/sessions/{id}/tasks`).

## What is saved

Two stores, wired in `agent/service/hosted.py`:

- **Transcript** (`agent/storage/transcript_store.py`): one JSONL file per session.
  Every message is written as it is appended.
- **Session record** (`agent/storage/session_store.py`): a SQLite row per session.
  It holds the tool-call history, the pinned model, tasks, approvals and the
  audit log.

Because each message is written when it is appended, a turn that fails leaves
everything up to the failure in the transcript, with every tool call closed.
