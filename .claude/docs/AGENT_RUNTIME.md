# Agent Runtime (llm-architect)

Implementation notes for `/root/CloudAgent/demo/agent/`. Binding spec: `SPECS.md`
§ 2 (Agent & Tool Layer) and § 6 (LLM Stack). This file documents only where
the code is more specific than, or intentionally diverges from, those sections.

## Files

| File | Contract |
|------|----------|
| `agent/llm.py` | `LangChainProvider` ��� Together AI + Qwen behind `LLMProvider`. |
| `agent/tools.py` | `Tool` protocol, `ReadFileTool`/`WriteFileTool`/`ShellTool`/`FinishTool`, `ToolRegistry`. |
| `agent/prompts.py` | `system_prompt()`. |
| `agent/runner.py` | `run_agent(task, sandbox, llm, tool_registry=None)`, `guard_budget()`. |
| `agent/__init__.py` | Exports `run_agent`, `LangChainProvider`, `ToolRegistry`, tools, `system_prompt`. |

## Conformance to SPECS.md

- `LLMProvider.complete` returns `{"is_final", "text", "tool_calls"}` (§ 1.1, § 6.1).
- Loop: observe -> think -> act, `max_iterations = 50` (§ 2.1).
- Four tools with the schemas in § 2.2; rejection messages match § 2.2 / § 8.1.
- `ToolRegistry` exposes `schemas()`, `get(name)`, `is_allowed(name)` (§ 2.1).
- API key from `TOGETHER_API_KEY` on the worker process only; never in the
  sandbox (§ 6.2). Tools call only `sandbox.read/write/exec` ��� no Docker import.

## Deviations / clarifications (beyond SPECS.md § 9)

1. **`complete()` return shape is always fully populated.** The § 6.1 sketch
   omits `text` on tool-call responses and `tool_calls` on final responses.
   The implementation always includes all three keys (empty string / empty
   list) so the loop never does a `KeyError`-prone lookup. A response with no
   tool calls is treated as final even if the model did not set a flag.

2. **Tool result shape is `{success, output, error}`** per the § 1.2 `Tool`
   protocol (the § 2.1 sketch's history string uses `json.dumps(result)`,
   which this matches). `FinishTool` additionally returns `is_final: True`,
   which the loop uses to short-circuit and return `{"status": "succeeded",
   "output": <finish output>}`. This realizes § 2.2(d) without a separate
   task-status side effect inside the tool.

3. **Tool names are single canonical strings** (`read`, `write`, `shell`,
   `finish`). § 2.2 lists aliases ("read or ReadFile"). For reliable OpenAI
   function-calling we register one name each (lowercase). The class names
   (`ReadFileTool` etc.) cover the "ReadFile" naming for code readers.

4. **Shell allow-list uses quote-aware tokenization.** § 2.2 / § 8.1 specify
   deny patterns (pip/npm install, git push, gh pr, cargo/docker build, curl).
   The implementation also enforces a positive allow-list of command heads
   (grep, rg, find, wc, cat, head, tail, ls, sort, uniq, awk, sed, cut, echo,
   git, file, stat, tree, ...) and restricts `git` to read-only subcommands
   (log, status, show, diff, branch, blame, ls-files). Commands are split into
   segments on shell operators (`| && || ; &`) using `shlex`, so the central
   demo command `rg 'TODO|FIXME'` is NOT mis-parsed (the `|` inside quotes is
   not a pipe). Every segment head must pass the allow-list. This is stricter
   than § 2.2 (deny-only) and is the intended hardening for the read-only demo.

5. **Write path restriction to `/workspace/out/`.** § 2.2(c) says writes go to
   `/workspace/out/` only. `WriteFileTool` normalizes relative paths under
   `/workspace` and rejects any normalized path outside `/workspace/out/`,
   protecting source files.

6. **`guard_budget` enforces the 5-minute task limit** (§ 6.2). It prefers the
   task's `started_at` (epoch or `datetime`) and falls back to the loop's
   `time.monotonic()` start when absent, raising `BudgetExceeded`, which the
   loop converts to `{"status": "failed", ...}`. Note: this is a wall-clock
   guard checked once per iteration; the worker's own timeout (§ 3.3) remains
   the hard backstop.

7. **`task` and `sandbox` are duck-typed.** Per ROLE_CONTRACTS, the `Task`
   dataclass and `Sandbox` are owned by backend-developer. `run_agent` reads
   `task.prompt` (or `task["prompt"]`) and best-effort updates
   `task.iteration` / `task.last_activity`; it never imports those types, so
   tests can pass simple fakes.

8. **LLM errors are surfaced as `is_error: True`, not raised.** If `llm.invoke`
   throws, `complete` returns `{"is_error": True, "is_final": True, "text": "LLM
   call failed: ..."}`. The runner detects `is_error` and returns
   `{"status": "failed", ...}` — **not** `succeeded`. (Pre-fix bug: the runner
   treated any `is_final` response as success, so HTTP 422 context-overflow errors
   silently appeared as `status: succeeded` with error text in `result`.)

9. **Lazy `langchain_openai` import.** Imported inside `LangChainProvider.__init__`
   so the package and tests import without the dependency installed; a missing
   key or missing package raises a clear `RuntimeError`.

14. **`FileCallbackHandler` as LLM middleware.** Every `llm.complete()` call wraps
    `llm_with_tools.invoke(messages, config=RunnableConfig(callbacks=[handler]))`
    inside `with FileCallbackHandler(self.log_path) as handler:`. This logs chain
    entry/exit and tool events to `/tmp/cloudagent_llm.log` (default). `log_path`
    is a constructor parameter. The handler is opened and closed per call (context
    manager) so no file handle leaks across iterations.

10. **Tool output is capped at 4000 chars before appending to history.** Large
    shell outputs (e.g., `rg 'TODO|FIXME'` on the full vllm repo returning
    thousands of lines) are truncated with a `\n[...truncated, N chars total]`
    suffix. This prevents context-window overflow on the next `llm.complete()` call.

11. **Message history is trimmed to 20 messages before each LLM call.**
    `_trim_history` keeps the first two messages (system + original prompt) plus
    the most recent 18 messages. This bounds total context independent of tool
    output length.

12. **Iteration increments BEFORE tools run.** `_update_progress` is called as
    soon as `tool_calls` are extracted from the LLM response (line ~159 in
    runner.py), so the user sees the iteration counter advance during long-running
    tool calls (e.g., `rg` on a large repo), not only after they complete.

13. **`task.thought` and `task.plan` are updated each iteration.** `thought` is
    set to `"Iteration N: calling <tool_name>"` (or the first 200 chars of the
    final text). `plan` is `"Step N of max 50"`. These are exposed by the API
    so the frontend can show live agent reasoning.

## Root cause: 2026-06-04 production bug

User symptom: `LLM call failed: Error code: 422 — Given: 544288 input tokens`.

**Cause chain:**
1. Agent runs `shell("rg 'TODO|FIXME' /workspace/repo")` on vllm (a large repo)
2. `rg` returns thousands of lines (~500K chars untruncated output)
3. Output appended verbatim to `history` → history becomes ~500K chars
4. Next `llm.complete(history, ...)` sends 544K tokens to Together AI → HTTP 422
5. `complete()` catches the exception, returns `is_final: True` with error text
6. Runner returned `{"status": "succeeded", "output": "LLM call failed: 422..."}` ← wrong status
7. Iteration counter appeared stuck at 0 because the loop completed before the next 2s poll

**Fixes applied:** output truncation (§10), history trimming (§11), `is_error` flag (§8), early iteration increment (§12), thought/plan fields (§13).

## Out of scope (per task + ROLE_CONTRACTS)

No API routes, worker queue, Docker/sandbox implementation, frontend,
persistence, policy engine, or RAG/fine-tuning. No hardcoded API keys.
