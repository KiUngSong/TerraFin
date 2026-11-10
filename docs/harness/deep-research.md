---
title: Deep research
summary: How TerraFin's deep research runs as an agent loop, what the model decides and what code enforces, and which papers each part comes from.
read_when:
  - Changing anything under agent/deepresearch/ or the deep_research capability
  - Deciding whether a research behaviour belongs to the model or to code
  - Picking the next improvement to deep research
---

# Deep research

All paths are under `src/TerraFin/`.

- Deep research is an agent loop. The model plans, searches, reads, calls
  TerraFin's data tools, calculates, and decides when it has enough.
- Code runs the model's tool calls and enforces the caller's caps on tokens,
  seconds and tool calls. It writes no plan, picks no query and judges no claim.
- A reviewer in a fresh context checks the finished report and sends problems
  back to the researcher.
- It is on by default. `TERRAFIN_AGENT_DEEPRESEARCH_ENABLED=0` turns it off and
  removes `deep_research` from the model's tools.

???+ info "Diagram: the research loop"

    ```mermaid
    flowchart TB
        q["Question,<br/>supplied documents"]
        subgraph loop["Researcher (agent/deepresearch/agent.py)"]
            direction TB
            turn["Model turn:<br/>plan, notes,<br/>tool calls"]
            tools["Tools, run in parallel:<br/>web_search, web_fetch, read,<br/>calculate, data tools"]
            budget["Budget line<br/>shown every turn"]
            elide["Oldest tool results<br/>elided past the<br/>context cap"]
            turn -->|"calls"| tools
            tools -->|"results"| elide --> budget --> turn
        end
        cap{"A cap<br/>reached?"}
        forced["Only finish<br/>counts"]
        finish["finish(report)"]
        subgraph review["Reviewer (fresh context, same tools)"]
            direction TB
            check["Check figures against<br/>the researcher's results,<br/>read or recompute<br/>where they fall short"]
            verdict["verdict(ok, problems,<br/>edits)"]
            check --> verdict
        end
        out["Report payload"]
        q --> turn
        turn -->|"finish"| finish
        budget --> cap
        cap -->|"yes"| forced --> out
        finish -->|"report and<br/>tool results"| check
        finish -->|"a cap reached"| out
        verdict -->|"ok, edits that apply,<br/>or no verdict"| out
        verdict -->|"problems"| turn
    ```

## The loop

`research` in `agent/deepresearch/agent.py`.

- The first message holds the question and any documents the caller supplies,
  in full while they fit one `read` result.
- Each turn the model writes its plan and notes, which are never dropped, and
  any number of tool calls. Up to 8 run in parallel.
- A URL is fetched once per run.
- `finish` is accepted only as the turn's sole tool call.

**Tools:**

| Tool | What it does |
|---|---|
| `web_search` | Exa, then DuckDuckGo, then Bing News (`data/providers/web/search.py`). |
| `web_fetch` | A fresh session of the run's own model answers a question from one page. |
| `read` | Reads a supplied document or a URL in slices, or finds lines in it. |
| `calculate` | Arithmetic and a few math functions. It runs no code. |
| TerraFin data tools | Every read-only market, fundamentals, filings, sentiment and screening capability. |
| `finish` | Submits the report, or, on a revision, edits to it. |

Web text and data tool results come back fenced, and both system prompts, the
researcher's and the reviewer's, say fenced text is data, never instructions.

**Reading.** `read` and `web_fetch` load pages with `load_document`, which reads
HTML, with tables as tab-separated rows, plus PDF, CSV and spreadsheets
(`.xlsx`, `.xls`). A spreadsheet cell reads as the sheet shows a percentage:
`5.23%`, not `0.0523`. A URL must resolve to
a public address, redirects included.

## Budget and stopping

- The `deep_research` capability reads the caps from
  `TERRAFIN_AGENT_DEEPRESEARCH_MAX_TOKENS` (3,000,000), `..._MAX_SECONDS` (1800),
  `..._MAX_TOOL_CALLS` (200) and `..._MAX_CONTEXT_CHARS` (500,000). Set the
  context cap to fit the model's window: a character is about a quarter of a token.
  It must be at least 120,000, so a full tool result is read in the turn it arrives.
- The token cap and the reported usage include the `web_fetch` reader's tokens.
- Every turn shows the budget spent.
- At a cap only a `finish` call counts, and the status is `partial`.

## Review

- A second loop with a fresh transcript and the same tools checks the report
  against the researcher's tool results, and reads or recomputes where they fall
  short. It never sees the researcher's notes.
- It ends with a verdict. Its edits apply directly when it finds no problems.
  Problems go back to the researcher, who revises and finishes again, and the
  next round re-checks it.
- It shares the run's budget. It does not run after a cap, and a reviewer that
  fails passes the report.
- It runs on the researcher's model unless
  `TERRAFIN_AGENT_DEEPRESEARCH_REVIEW_MODEL` names another, as `provider/model`.

## Context

Past the context cap (`..._MAX_CONTEXT_CHARS` above), older turns'
reasoning blocks go first, then the oldest tool
results become stubs the model can fetch again. The model's own messages stay.

## The product capability

`agent/runtime/deep_research_capability.py`.

- It runs as a background task. The model is told to confirm with the user
  first, unless the user asked for deep research or a report by name.
- It supplies no documents up front. The user's documents are http(s) URLs,
  which the model reads with `read`.
- Model turns go straight to the session's provider and do not count against
  the chat's context.
- Data tool calls are recorded with the task. Each turn saves a checkpoint, so a
  restarted task resumes. A cancel stops the run within half a second, even
  during a model call or a tool. The call it leaves finishes on its own, unread.
- The payload holds the report, its status (`ok`, `partial` or `failed`) and
  the run's counts.

## Where each part comes from

| Part | Source |
|---|---|
| The model decides each step, code only runs tools | Tongyi DeepResearch's ReAct loop, WebThinker, Anthropic's multi-agent research system |
| Budget shown every turn, caps set by the caller | the Budget Tracker from Budget-Aware Tool Use |
| One forced final answer at the cap | WebThinker's search limit, Jina's node-DeepResearch final answer call |
| A reviewer before the report returns | Jina's evaluator, TTD-DR (Test-Time Diffusion Deep Researcher) judge and revision |
| A calculator for every derived figure | Open Deep Search's Wolfram Alpha tool, without its code execution |
| Old tool results dropped, notes kept | MiroThinker keeps only recent tool outputs |

## Benchmarks

The benchmarks compare this loop with Claude Code and OpenCode on the same
model. They live in a private repo, `terrafin_private.deepresearch_eval`.
