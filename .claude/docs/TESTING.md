# Testing Guide — CloudAgent MVP

This document covers how to build, start, and verify the CloudAgent MVP system. It is the companion to `ACCEPTANCE.md`, which holds formal acceptance criteria, and `SPECS.md`, which is the binding technical reference.

---

## 1. Build and Start the System

### 1.1 Prerequisites

| Requirement | Minimum version | Check |
|---|---|---|
| Docker Engine | 20.x | `docker --version` |
| Python | 3.11 | `python3 --version` |
| `jq` | 1.6 | `jq --version` |
| `curl` | any recent | `curl --version` |
| Together AI key | — | `echo $TOGETHER_API_KEY` |

### 1.2 Build the Sandbox Image

The sandbox image (`cloudagent-sandbox:latest`) must be built once before any task can run. From `demo/`:

```bash
cd demo
docker build -t cloudagent-sandbox:latest .
```

The Dockerfile installs `git` and `ripgrep` on top of `python:3.11-slim`. Confirm the build succeeded:

```bash
docker image ls cloudagent-sandbox:latest
```

### 1.3 Set Environment Variables

The worker process needs the Together AI key at runtime. The key must never be baked into the container image.

```bash
export TOGETHER_API_KEY="<your-key>"
```

Optionally load from a `.env` file via the provided helper:

```bash
source scripts/load-env.sh
```

### 1.4 Start the Backend

```bash
python3 run.py
```

or, if the entry-point lives under `app/`:

```bash
python3 app/main.py
```

The API server starts on `http://localhost:8000` by default. Confirm it is up:

```bash
curl -s http://localhost:8000/ | head -5
# or, if the root path serves the frontend HTML:
curl -so /dev/null -w "%{http_code}" http://localhost:8000/
# expected: 200
```

### 1.5 Optional: Docker Compose

If a `docker-compose.yml` is present at the project root:

```bash
docker compose up --build
```

This builds both images and starts the worker in a single step. The API is still reachable on port 8000 on the host.

---

## 2. Four-Pillar Verification with curl

### Pillar 1 — Agent Orchestration & Scheduling

**What to confirm:** The REST API accepts tasks, assigns IDs immediately, and tasks progress through the `queued → running → succeeded | failed` state machine.

```bash
# Submit a task — expect HTTP 202 and a JSON body with {id, status:"queued"}
curl -v -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Find all TODO and FIXME in the vllm repo and summarize."}'

# Copy the returned id into the next command
TASK_ID="<id-from-above>"

# Poll — run this a few times and watch the status field change
curl -s http://localhost:8000/api/tasks/$TASK_ID | jq '{id, status, iteration}'
```

Expected progression visible over successive polls:
```
{"id": "...", "status": "queued",   "iteration": 0}
{"id": "...", "status": "running",  "iteration": 2}
{"id": "...", "status": "succeeded","iteration": 7}
```

The `id` must be returned before the task finishes (async dispatch). If `status` jumps straight from the POST response to `running` or `succeeded` before the GET call, the dispatch is synchronous and should be investigated.

### Pillar 2 — Sandbox & Isolated Execution

**What to confirm:** Operations execute inside a Docker container; the container is destroyed after task completion.

```bash
# After submitting a task, open a second terminal and watch containers
watch -n 2 'docker ps --filter name=cloudagent --format "{{.ID}} {{.Names}} {{.Status}}"'
```

While the task is running, one container should appear. After the task reaches `succeeded` or `failed`, the container should be gone within a few seconds.

Cross-check: the result must reference `/workspace/repo` paths (proving the clone happened inside the container, not on the host):

```bash
curl -s http://localhost:8000/api/tasks/$TASK_ID | jq -r '.result' | grep -E '/workspace|vllm' | head -5
```

```bash
# Direct check: no cloudagent containers should linger after task completes
docker ps --filter name=cloudagent
# Expected: empty table (no running containers)
```

### Pillar 3 — LLM Integration & Tool Calling

**What to confirm:** The LLM makes real tool calls, the loop iterates multiple times, and the final output is a coherent markdown report.

```bash
# Submit the canonical analysis task
TASK_ID=$(curl -s -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Find all TODO and FIXME in the vllm repo and summarize."}' \
  | jq -r '.id')

# Poll until done (manual loop)
while true; do
  R=$(curl -s http://localhost:8000/api/tasks/$TASK_ID)
  STATUS=$(echo $R | jq -r '.status')
  ITER=$(echo $R | jq -r '.iteration // 0')
  echo "status=$STATUS iteration=$ITER"
  [ "$STATUS" = "succeeded" ] || [ "$STATUS" = "failed" ] && break
  sleep 3
done

# Print the result
curl -s http://localhost:8000/api/tasks/$TASK_ID | jq -r '.result'
```

Quality indicators to look for in the result:
- Markdown headers (`#`, `##`)
- File paths containing `.py` or directory names from the vllm repo
- At least one TODO or FIXME text quoted from source
- `iteration` in the final GET response is 2 or greater (multiple LLM calls occurred)

### Pillar 4 — Extensible Architecture (Protocols)

**What to confirm:** The three protocols exist in code and each has a concrete implementation.

```bash
# LLMProvider protocol
grep -rn "class LLMProvider" /root/CloudAgent/

# Tool protocol
grep -rn "class Tool" /root/CloudAgent/

# Sandbox protocol and its Docker implementation
grep -rn "class Sandbox\|class DockerSandbox" /root/CloudAgent/

# Tool implementations
grep -rn "class ReadFile\|class WriteFile\|class Shell\|class Finish" /root/CloudAgent/
```

All four grep commands must return at least one match. Non-zero results for any of them indicate an incomplete implementation.

---

## 3. Manual Verification Checklist

Work through this list from top to bottom before marking the MVP complete.

### 3.1 Environment

- [ ] `docker --version` shows 20.x or later
- [ ] `docker ps` runs without permission error
- [ ] `echo $TOGETHER_API_KEY` is non-empty
- [ ] `jq --version` is available
- [ ] `curl --version` is available

### 3.2 System Startup

- [ ] `docker build -t cloudagent-sandbox:latest .` completes without errors
- [ ] `docker image ls cloudagent-sandbox:latest` shows the image
- [ ] `python3 run.py` (or `python3 app/main.py`) starts without import errors
- [ ] `curl -so /dev/null -w "%{http_code}" http://localhost:8000/` returns 200

### 3.3 Pillar 1 — Orchestration

- [ ] `POST /api/tasks` returns HTTP 202 with `{id, status:"queued"}`
- [ ] The ID is a non-empty string (UUID or similar)
- [ ] `GET /api/tasks/{id}` returns HTTP 200
- [ ] A second `GET` call a few seconds later shows status has changed (not stuck at `queued`)
- [ ] Task eventually reaches `succeeded` or `failed` (does not hang indefinitely)
- [ ] Completed task response includes a `result` field (for `succeeded`) or `error` field (for `failed`)

### 3.4 Pillar 2 — Sandbox

- [ ] While a task is running, `docker ps` shows exactly one `cloudagent-sandbox` container
- [ ] After the task finishes, `docker ps` shows zero `cloudagent-sandbox` containers
- [ ] The result text references paths under `/workspace/` (confirming execution inside container)
- [ ] Running the same task twice does not leave stale containers from the first run

### 3.5 Pillar 3 — LLM & Tools

- [ ] Task `iteration` counter reaches at least 2 (multiple think-act cycles)
- [ ] Final `result` is non-empty and contains markdown formatting
- [ ] Result mentions TODO or FIXME (task-relevant content, not a boilerplate message)
- [ ] No Python traceback visible in the result or error fields
- [ ] LLM call does not time out (check worker logs for `TimeoutError`)

### 3.6 Pillar 4 — Architecture

- [ ] `grep -rn "class LLMProvider"` returns at least one match
- [ ] `grep -rn "class Tool"` returns at least one match
- [ ] `grep -rn "class DockerSandbox"` returns at least one match
- [ ] `grep -rn "class ReadFile\|class Shell\|class Finish"` returns matches for each tool

### 3.7 Rejection Cases

- [ ] Submit `{"prompt": "run pip install requests"}` — task should fail or result should contain a rejection message containing "not supported" or "not available"
- [ ] Submit `{"prompt": "Push changes to GitHub using git push"}` — same expectation
- [ ] Neither pip install nor git push is actually executed (confirm by absence of side-effects)

### 3.8 Frontend (if implemented)

- [ ] `curl http://localhost:8000/` returns an HTML page (not JSON)
- [ ] Opening `http://localhost:8000/` in a browser shows a text input and Submit button
- [ ] Submitting a task in the browser shows a task ID and a status that updates
- [ ] Final result markdown is displayed in the browser when the task succeeds

### 3.9 End-to-End Script

- [ ] `bash -n scripts/demo.sh` passes syntax check
- [ ] `./scripts/demo.sh http://localhost:8000` exits with code 0
- [ ] Re-running the script produces consistent results (no leftover state)

---

## 4. Running the Automated Demo Script

```bash
# Ensure executable bit is set (already done at creation time)
chmod +x /root/CloudAgent/demo/scripts/demo.sh

# Run against local server
./scripts/demo.sh http://localhost:8000

# Run against a different host
./scripts/demo.sh http://192.168.1.100:8000
```

The script:
1. Verifies the server is reachable.
2. Submits `"Find all TODO and FIXME in the vllm repo and summarize."` and validates HTTP 202.
3. Polls `GET /api/tasks/{id}` every 3 seconds, up to 60 polls (3 minutes).
4. On `succeeded`: prints the first 40 lines of the result and validates it contains markdown or TODO/FIXME references.
5. Submits `"run pip install requests"` as a rejection probe and checks for a rejection signal in the response.
6. Exits 0 if all checks passed, 1 if any check failed.

See `ACCEPTANCE.md` — "Test Script" section for expected output format.

---

## 5. Known Limitations (MVP Scope)

These are intentional constraints for the 8-hour MVP. They are not defects.

| Limitation | Detail |
|---|---|
| No persistence across restarts | Tasks are stored in memory only; all state is lost when the worker process exits. |
| Single supported repository | Only `vllm-project/vllm` is cloned. User-specified repo URLs are not accepted. |
| No build or install operations | `pip install`, `npm install`, `cargo build`, etc. are rejected by the tool policy. |
| No remote write | `git push`, `gh pr create`, and any GitHub write API are rejected. |
| Single worker, no concurrency | Tasks run one at a time in a FIFO queue. A second task waits until the first completes. |
| No real-time streaming | Task output is only available after the agent calls `finish()`. No incremental log streaming. |
| Minimal error recovery | A timed-out or crashed sandbox marks the task `failed`; there is no retry mechanism. |
| No private repository access | Only public, unauthenticated GitHub clones are supported. |
| Shallow clone only | The vllm repo is cloned with `--depth 1`; full git history is not available inside the sandbox. |
| No artifact editing | The `EditFile` tool is out of scope; agents can only read and overwrite files. |

---

## 6. Troubleshooting

**Server returns `connection refused`**
The backend is not running. Start it with `python3 run.py` and confirm the port is 8000.

**Task stays in `queued` indefinitely**
The background worker thread is not running. Check the process logs for startup errors or exceptions in the worker loop.

**Task fails with `Docker sandbox creation failed`**
Docker daemon is not running (`sudo systemctl start docker`) or the sandbox image is missing (`docker build -t cloudagent-sandbox:latest .`).

**`jq: command not found`**
Install jq: `apt-get install -y jq` (Debian/Ubuntu) or `brew install jq` (macOS).

**LLM call times out**
Verify `TOGETHER_API_KEY` is set and valid. Check network connectivity to `api.together.xyz`. The default per-call timeout is 30 seconds.

**Stale containers after task failure**
If the worker crashes mid-task, run `docker ps -a | grep cloudagent-sandbox` to find orphaned containers and remove them with `docker rm -f <id>`.
