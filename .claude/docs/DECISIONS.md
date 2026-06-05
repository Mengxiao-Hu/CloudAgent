# CloudAgent — Organizer Decisions Log

## 2026-06-04 — Initial MVP Build

### Kickoff

- `.claude/docs/MVP.md` and `SPECS.md` were missing → spawned `product-manager` first.
- PM read `_requirements.txt`, `skeleton.py`, and `REFERENCES.md`; produced MVP.md, SPECS.md, ROLE_CONTRACTS.md, ACCEPTANCE.md.
- Expected code layout: `agent/` (llm-architect), `app/` (backend-developer), `frontend/` (frontend-developer), `scripts/` (qa-expert).

### Parallel workstreams (Wave 1)

- `llm-architect` and `backend-developer` spawned in parallel after specs existed — no dependency between them at the code level.
- `frontend-developer` and `qa-expert` spawned in parallel after Wave 1 completed.

### Key architectural decisions

1. **LLM stack:** LangChain + Together AI + `Qwen/Qwen2.5-7B-Instruct-Turbo`. API key in worker process only, never injected into Docker container.
2. **Sandbox:** `DockerSandbox` using `cloudagent-sandbox:latest` (python:3.11-slim + git + ripgrep). `tail -f /dev/null` keeps container alive for exec_run calls (docker-py exits immediately on bash entrypoint).
3. **Worker thread:** `threading.Thread` (not asyncio) — easier to block safely. `run_agent` is async, so worker uses `asyncio.run()` in sub-thread.
4. **Tool allow-list:** Shell uses `shlex`-based tokenizer to avoid misreading quoted regex like `'TODO|FIXME'` as a pipe operator.
5. **Deviations from skeleton.py:** No Plan/Step, no policy engine, no multi-tenant, no GitHub token injection — all documented in SPECS.md § 9.
6. **`nano_cpus` not `cpus`:** docker-py SDK requires integer nanocpus (1 CPU = 1_000_000_000).

### 2026-06-04 — Production bug investigation and fix

**Symptoms:** 422 context-limit error, iteration stuck at 0, no thought/plan in UI.

**Root cause trace:**
- `rg 'TODO|FIXME' /workspace/repo` on vllm returns ~500K chars untruncated
- Appended verbatim to history → 544K tokens on next LLM call → HTTP 422
- `llm.complete()` returned `is_final: True` on exception; runner treated it as `succeeded`
- Iteration counter looked stuck at 0 because the whole loop completed in <5s (before polling caught it)
- `thought`/`plan` fields never existed on Task or in the API

**Fixes (minimal diffs, all in `demo/`):**
1. `agent/runner.py` — truncate tool output to 4000 chars; trim history to 20 messages before LLM call; detect `is_error` response → return `failed`; increment iteration BEFORE tools run; set `task.thought`/`task.plan` each iteration
2. `agent/llm.py` — add `is_error: True` to exception-path return
3. `agent/prompts.py` — rg example now uses `--max-count 5`
4. `app/models.py` — add `thought: str | None`, `plan: str | None` to Task
5. `app/main.py` — expose thought/plan in `_task_to_dict` and `TaskResponse`
6. `app/worker.py` — set `task.thought` during git clone phase for visible progress
7. `frontend/index.html` — show thought, plan, iteration in progress section while running
8. `tests/test_runner.py` — 5 unit tests covering all three bugs; all pass in 0.02s

Full root cause documented in `.claude/docs/AGENT_RUNTIME.md` (§ Root cause).

**Additional fixes discovered during live verification:**
- `guard_budget` used `task.started_at` (before git clone), so the 5-min budget was consumed by the ~2.5 min clone. Fixed to use `start_monotonic` (agent loop start time). Timeout also increased to 10 min agent + 11 min worker wall clock.
- Worker routed `run_agent` failure output to `task.result` instead of `task.error` — frontend showed "Unknown error" for failed tasks. Fixed: failures now go to `task.error`.
- Tool results were appended to history with `role: "assistant"`, causing the model to echo them back as final output instead of synthesizing a report. Fixed to `role: "user"` (environment observation).
- Additional files changed: `runner.py` (role fix, timeout increase), `worker.py` (error routing, timeout), `prompts.py` (explicit "don't copy tool output" instruction), `tests/test_runner.py` (updated for role change).

**Live verification result (task 260f4ddf):**
- status: succeeded, iteration: 5, result: 1689-char markdown TODO/FIXME summary
- No 422, no stuck iteration, thought field showed live LLM reasoning during polling

### Scope decisions

- Demo repo fixed to `vllm-project/vllm` shallow clone — no user-selectable repos (per MVP.md).
- Frontend: plain HTML + vanilla JS, no build step, served as static file from FastAPI.
- No auth, no persistence, no multi-worker.
