# CloudAgent — demo

Runnable implementation of the CloudAgent MVP. See the [root README](../README.md) for architecture and design decisions.

## Prerequisites

- Docker (running)
- Python 3.11+
- Together AI API key — get one free at https://api.together.xyz/

## Setup

```bash
cd demo

# 1. Build the sandbox image (one time — ~30 seconds)
docker build -t cloudagent-sandbox:latest .

# 2. Create .venv and install dependencies (one time)
./scripts/setup-venv.sh

# 3. Set API key
export TOGETHER_API_KEY=<your-key>
# or: edit scripts/load-env.sh and source it
```

## Run

```bash
source scripts/load-env.sh   # sets TOGETHER_API_KEY
.venv/bin/python run.py
```

Server starts at **http://localhost:8000**.

> **First task:** the vllm repo is cloned into a Docker volume on first use (~2 min).
> All subsequent tasks skip the clone and start in seconds.

## UI

Open http://localhost:8000 in a browser. Submit a prompt and watch:
- **Status** updates (`queued → running → succeeded`)
- **Iteration** counter increments as the agent works
- **Thought** line shows what the agent is doing right now
- **Plan** line shows the current step number
- **Result** renders as markdown when done

## API

```bash
# Submit a task
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Find all TODO and FIXME in the vllm repo and summarize."}'
# → 202 {"id": "abc-123", "status": "queued", "created_at": "..."}

# Poll for result
curl http://localhost:8000/api/tasks/abc-123
# running → {"status":"running","iteration":4,"thought":"Iteration 4: calling shell","plan":"Step 4 of max 50"}
# done    → {"status":"succeeded","result":"# TODO/FIXME Summary\n\n...","iteration":7}
```

**Response fields** (None fields are omitted):

| Field | When present | Description |
|-------|-------------|-------------|
| `status` | always | `queued` / `running` / `succeeded` / `failed` |
| `iteration` | running / done | number of agent iterations completed |
| `thought` | running | what the agent is doing right now |
| `plan` | running | current step label (e.g. "Step 4 of max 50") |
| `result` | succeeded | final markdown report |
| `error` | failed | error message |

## Acceptance script

Runs three checks end-to-end (requires `curl` and `jq`):

```bash
./scripts/demo.sh http://localhost:8000
```

1. Server reachable
2. TODO/FIXME task → `succeeded` with non-empty markdown result and `iteration > 0`
3. `pip install` probe → rejected (agent returns an unsupported-operation error)

Exit code 0 = all passed.

## Unit tests

No API key or Docker required:

```bash
.venv/bin/pytest tests/ -v
```

16 tests covering:
- LLM error → `failed` status (not `succeeded`)
- Tool output truncated to 4 000 chars before history append
- Iteration increments before tools run (UI shows progress immediately)
- `thought` and `plan` set on each iteration
- History trimmed to 20 messages before each LLM call
- `guard_budget` raises after time limit, silent within limit
- `ShellTool.check` allow-list: rg, git -C, git push rejection, pip rejection, quoted regex pipe, unknown subcommand

## Project layout

```
demo/
├── agent/
│   ├── runner.py     # observe→think→act loop (MAX_ITERATIONS=50, 10-min budget)
│   ├── llm.py        # LangChainProvider wrapping Together AI
│   ├── tools.py      # ReadFile, WriteFile, Shell (allow-list), Finish
│   └── prompts.py    # system prompt: tool descriptions + search strategy
├── app/
│   ├── main.py       # FastAPI: POST /api/tasks, GET /api/tasks/{id}, GET /
│   ├── worker.py     # daemon thread: dequeue → sandbox → run_agent → update task
│   ├── sandbox.py    # DockerSandbox: named volume + exec/read/write/destroy
│   ├── models.py     # Task dataclass (id, status, iteration, thought, plan, ...)
│   └── store.py      # in-memory dict + deque queue
├── frontend/
│   └── index.html    # vanilla JS: submit, poll, render markdown
├── tests/
│   └── test_runner.py
├── scripts/
│   ├── demo.sh       # end-to-end acceptance
│   ├── load-env.sh   # source TOGETHER_API_KEY
│   └── setup-venv.sh # create .venv
├── Dockerfile        # sandbox image: python:3.11-slim + git + ripgrep
├── requirements.txt  # fastapi uvicorn docker langchain-openai langchain python-dotenv
└── run.py            # uvicorn entrypoint (host=0.0.0.0, port=8000)
```
