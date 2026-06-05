# CloudAgent

An autonomous agent platform for cloud-based code analysis. Users submit a natural-language task; the platform launches an agent that reasons with an LLM, executes tools inside an isolated Docker sandbox, iterates until done, then returns a structured result.

> **Take-home context:** this project demonstrates four design pillars —
> agent orchestration, sandbox isolation, LLM tool-calling, and a swappable
> protocol architecture — using a minimal but fully working implementation.

---

## Four pillars

### 1. Agent orchestration

Tasks move through a state machine (`queued → running → succeeded | failed`) driven by a single background worker thread. Each iteration of the agent loop is visible in real time via the API and UI.

```
POST /api/tasks  →  in-memory queue  →  worker thread  →  run_agent()
GET  /api/tasks/{id}  →  live status, iteration, thought, plan, result
```

Key files: [`demo/app/worker.py`](demo/app/worker.py), [`demo/app/store.py`](demo/app/store.py), [`demo/app/main.py`](demo/app/main.py)

### 2. Sandbox isolation

Each task runs inside an ephemeral Docker container. The agent's tools (`read`, `write`, `shell`) call into the sandbox — never the worker host. The vllm repo is pre-cloned into a named Docker volume on first use and mounted read-only, so tasks start in seconds rather than waiting for a fresh clone every time.

```
worker process          Docker container
──────────────          ─────────────────────────────────────
LLM call  ────────────► (never; key stays here)
tool.run() ───exec()──► /bin/sh -c "rg 'TODO' /workspace/repo"
           ───read()──► cat /workspace/repo/vllm/model_executor/...
           ──write()──► tee /workspace/out/report.md
```

Key files: [`demo/app/sandbox.py`](demo/app/sandbox.py), [`demo/Dockerfile`](demo/Dockerfile)

### 3. LLM integration and tool-calling

The agent loop follows an **observe → think → act** cycle backed by LangChain + Together AI (`Qwen/Qwen2.5-7B-Instruct-Turbo`). The LLM receives a tool schema and picks which tool to call each iteration. Tool results are fed back as observations, and the model iterates until it calls `finish()` with a markdown report.

Context safety measures prevent the 422 "too many tokens" error that would otherwise occur on large repos:
- Tool output is capped at 4 000 characters before being appended to history
- Message history is trimmed to 20 messages before each LLM call
- The system prompt instructs bounded search (`rg --max-count 5`) over full-repo dumps

```
system prompt
user prompt
  └─ [think]  llm.complete(history, tool_schemas)
  └─ [act]    tool.run(args, sandbox)
  └─ [observe] history.append({"role": "user", "content": "Tool result: ..."})
  └─ repeat until finish() or max iterations
```

Key files: [`demo/agent/runner.py`](demo/agent/runner.py), [`demo/agent/llm.py`](demo/agent/llm.py), [`demo/agent/tools.py`](demo/agent/tools.py), [`demo/agent/prompts.py`](demo/agent/prompts.py)

### 4. Swappable protocol architecture

Three `Protocol` interfaces define the seams between axes of change. The core loop (`run_agent`) only depends on these protocols — not on Docker, LangChain, or FastAPI:

| Protocol | Axis of change | MVP implementation |
|----------|---------------|-------------------|
| `LLMProvider` | model / API | `LangChainProvider` (Together AI) |
| `Tool` | agent capability | `ReadFileTool`, `WriteFileTool`, `ShellTool`, `FinishTool` |
| `Sandbox` | isolation backend | `DockerSandbox` (python:3.11-slim + git + ripgrep) |

Swapping the model means replacing `LangChainProvider`; adding a tool means implementing `Tool.run()`; moving to Firecracker means implementing `Sandbox.exec/read/write/destroy`. None of these touch `run_agent`.

Key files: [`demo/agent/tools.py`](demo/agent/tools.py) (protocols + tool implementations), [`skeleton.py`](skeleton.py) (architecture reference)

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│  Browser / curl                                             │
│  POST /api/tasks  ·  GET /api/tasks/{id}  ·  GET /         │
└────────────────────────┬────────────────────────────────────┘
                         │ FastAPI (uvicorn)
┌────────────────────────▼────────────────────────────────────┐
│  Worker thread                                              │
│  dequeue → DockerSandbox.create() → run_agent() → update   │
│                                                             │
│  run_agent:  [think] llm.complete()                         │
│              [act]   tool.run(args, sandbox)                │
│              [observe] append result to history             │
└──────────────────────────┬──────────────────────────────────┘
                           │ docker exec / docker cp
┌──────────────────────────▼──────────────────────────────────┐
│  Docker container  (cloudagent-sandbox:latest)              │
│  /workspace/repo  ← named volume (vllm, read-only)         │
│  /workspace/out/  ← writable report output                 │
│  tools: git · ripgrep · cat · head · find                   │
└─────────────────────────────────────────────────────────────┘
                           │ Together AI API (worker only)
┌──────────────────────────▼──────────────────────────────────┐
│  Qwen/Qwen2.5-7B-Instruct-Turbo  (via LangChain)           │
│  TOGETHER_API_KEY in worker env; never in container         │
└─────────────────────────────────────────────────────────────┘
```

---

## Tech stack

| Layer | Choice |
|-------|--------|
| API | FastAPI + uvicorn |
| LLM | LangChain · Together AI · Qwen2.5-7B-Instruct-Turbo |
| Sandbox | Docker (python:3.11-slim + git + ripgrep) |
| Worker | Python `threading.Thread` (single worker, in-process queue) |
| Frontend | Vanilla HTML + JS (no build step) |
| Tests | pytest (16 unit tests, no API key required) |

---

## Project structure

```
CloudAgent/
├── demo/
│   ├── agent/
│   │   ├── runner.py       # observe→think→act loop
│   │   ├── llm.py          # LangChainProvider (Together AI)
│   │   ├── tools.py        # ReadFile, WriteFile, Shell, Finish + ToolRegistry
│   │   └── prompts.py      # system prompt with tool guidance
│   ├── app/
│   │   ├── main.py         # FastAPI routes + startup
│   │   ├── worker.py       # background thread, timeout wrapper
│   │   ├── sandbox.py      # DockerSandbox (volume caching, exec/read/write)
│   │   ├── models.py       # Task dataclass
│   │   └── store.py        # in-memory task store + FIFO queue
│   ├── frontend/
│   │   └── index.html      # single-page UI with live polling
│   ├── tests/
│   │   └── test_runner.py  # 16 unit tests (agent loop, tool allow-list, budget)
│   ├── scripts/
│   │   ├── demo.sh         # end-to-end acceptance script
│   │   ├── load-env.sh     # source TOGETHER_API_KEY
│   │   └── setup-venv.sh   # create .venv + install requirements
│   ├── Dockerfile          # sandbox image (NOT the app image)
│   ├── requirements.txt    # worker/API Python dependencies
│   └── run.py              # uvicorn entrypoint
├── skeleton.py             # architecture reference (pseudocode)
├── _requirements.txt       # original project requirements spec
└── .claude/docs/           # binding specs (SPECS.md, MVP.md, ACCEPTANCE.md, ...)
```

---

## Quick start

**Prerequisites:** Docker running, Python 3.11+, a [Together AI](https://api.together.xyz/) API key.

```bash
# 1. Build the sandbox image (one time)
cd demo
docker build -t cloudagent-sandbox:latest .

# 2. Install Python dependencies
./scripts/setup-venv.sh

# 3. Set your API key
cp ../.env.example .env.example   # see format
export TOGETHER_API_KEY=<your-key>
# or: add to ~/.config/cloudagent/env.sh and source scripts/load-env.sh

# 4. Start the server
source scripts/load-env.sh
.venv/bin/python run.py
```

Open **http://localhost:8000** — the UI lets you submit a prompt and watch the agent work in real time.

The first task clones the vllm repo into a Docker volume (~2 min). All subsequent tasks start immediately from the cached volume.

### Try it with curl

```bash
# Submit
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Find all TODO and FIXME in the vllm repo and summarize."}'
# → {"id": "abc123", "status": "queued", ...}

# Poll (repeat until succeeded/failed)
curl http://localhost:8000/api/tasks/abc123
# running: {"status":"running","iteration":3,"thought":"Iteration 3: calling shell","plan":"Step 3 of max 50"}
# done:    {"status":"succeeded","result":"# TODO/FIXME Summary\n\n..."}
```

### Run the acceptance script

```bash
cd demo
./scripts/demo.sh http://localhost:8000
```

Checks: server reachable → task queued → agent iterates → markdown result returned → `pip install` probe rejected.

### Run unit tests

```bash
cd demo
.venv/bin/pytest tests/ -v
# 16 passed in ~0.1s  (no API key, no Docker required)
```

---

## Design decisions

**Single worker thread, not asyncio.**
The agent loop is async (for `asyncio.wait_for` cancellation), but the outer worker is a `threading.Thread`. This keeps the queue and state updates simple and avoids async leaking into FastAPI's request handlers.

**Named Docker volume instead of per-task clone.**
`git clone --depth 1` of vllm takes ~2–3 minutes. Cloning once into `cloudagent-vllm-repo` and mounting it read-only cuts task startup to under 5 seconds.

**Tool output capped at 4 000 characters.**
`rg 'TODO|FIXME' /workspace/repo` on vllm produces ~1.6 MB of output. Appending this verbatim to history triggers a 422 "too many tokens" error (Qwen2.5-7B has a ~32K token context). Truncation + history trimming keeps the LLM within limits.

**Tool results use `role: "user"`.**
OpenAI-format tool results should use `role: "tool"`, but smaller models (like Qwen2.5-7B via Together AI) can misread `role: "assistant"` messages as their own prior output and echo them back as the final answer. Using `role: "user"` makes the model treat results as environment observations.

**LLM key never in the container.**
The Together AI key is an environment variable on the worker process only. The Docker container gets no network credentials — it can reach GitHub (for git operations) but not the LLM API.

---

## What's in scope (MVP) vs. out of scope

| In scope | Out of scope (P1) |
|----------|------------------|
| Single-user, in-memory state | Multi-tenant, SQLite/Redis persistence |
| Fixed vllm repo (read-only analysis) | User-supplied repo URLs, private repos |
| 4 tools: read/write/shell/finish | Edit-in-place, test-runner, PR creation |
| Docker sandbox | Firecracker microVM, seccomp tuning |
| Single background worker | Multi-worker, task priorities |
| Plain HTML frontend | Auth, design system, streaming |
