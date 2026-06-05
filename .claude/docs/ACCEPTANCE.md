# Acceptance Criteria & Test Plan — CloudAgent MVP

**Definition of Done:** CloudAgent MVP is complete when all criteria in this document can be verified (either via curl/script or manual inspection).

---

## Acceptance Criteria (MVP Success)

### Pillar 1: Agent Orchestration & Scheduling

- [ ] **API Exists:** `POST /tasks` endpoint returns `202 Accepted` with task ID
- [ ] **Task Polling:** `GET /tasks/{id}` returns current task status
- [ ] **State Transitions:** Task moves through `queued` → `running` → `succeeded` | `failed` visibly
- [ ] **Async Execution:** Submit task, receive ID immediately; task runs in background worker
- [ ] **Result Retrieval:** Completed task returns `result` field with markdown output

**Verification Script:**
```bash
TASK_ID=$(curl -s -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Find all TODO/FIXME in /workspace/repo"}' \
  | jq -r '.id')

echo "Task ID: $TASK_ID"

# Poll until done
while true; do
  STATUS=$(curl -s http://localhost:8000/api/tasks/$TASK_ID | jq -r '.status')
  echo "Status: $STATUS"
  [ "$STATUS" = "succeeded" ] && break
  sleep 2
done

# Get result
curl -s http://localhost:8000/api/tasks/$TASK_ID | jq '.result'
```

---

### Pillar 2: Sandbox & Isolated Execution

- [ ] **Docker Isolation:** read/write operations execute **inside container**, not on worker host
- [ ] **Repository Clone:** vllm shallow-cloned into `/workspace/repo` inside sandbox
- [ ] **Output Directory:** `/workspace/out/` exists and is writable within sandbox
- [ ] **Container Cleanup:** Container is destroyed after task completes (no lingering processes)
- [ ] **Path Isolation:** Agent cannot read files outside `/workspace/` (or explicitly allowed paths)

**Verification Script:**
```bash
# Run task
TASK_ID=$(curl -s -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Check if /workspace/repo contains vllm files"}' \
  | jq -r '.id')

# Wait for completion
sleep 30

# Check that no stray containers remain
RUNNING=$(docker ps | grep -c cloudagent || true)
echo "Running cloudagent containers: $RUNNING"
[ "$RUNNING" -eq 0 ] && echo "✓ Containers cleaned up"

# Verify result mentions vllm
curl -s http://localhost:8000/api/tasks/$TASK_ID | jq '.result' | grep -q vllm && echo "✓ Clone successful"
```

---

### Pillar 3: LLM Integration & Tool Calling

- [ ] **LLM API Connected:** Agent successfully calls Together AI Qwen model
- [ ] **Tool Calls Work:** Agent makes tool calls (read, shell, write, finish)
- [ ] **Loop Iterates:** Agent iterates multiple times (at least 2-3 tool calls observed)
- [ ] **Tool Results Used:** LLM receives tool results and responds appropriately
- [ ] **Finish Tool:** Agent calls finish() and exits cleanly
- [ ] **Summary Report:** Agent generates markdown summary of findings

**Verification Approach:**
1. Submit task to analyze vllm for TODO/FIXME
2. Wait for completion
3. Inspect returned markdown for:
   - List of TODO/FIXME comments found
   - File paths and line numbers
   - Clear summary structure
4. Agent should call tools in logical sequence:
   - `shell("rg 'TODO|FIXME'" ...)` to find matches
   - `read(file)` to examine snippets
   - `write("/workspace/out/report.md", ...)` to save result
   - `finish(output)` to complete

**Test Script:**
```bash
curl -s -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Find all TODO/FIXME in /workspace/repo and write a summary to /workspace/out/report.md"}' \
  | jq -r '.id' > /tmp/task_id.txt

TASK_ID=$(cat /tmp/task_id.txt)

# Poll for 5 minutes
for i in {1..150}; do
  RESULT=$(curl -s http://localhost:8000/api/tasks/$TASK_ID)
  STATUS=$(echo "$RESULT" | jq -r '.status')
  ITERATION=$(echo "$RESULT" | jq -r '.iteration // 0')
  echo "[$i] Status: $STATUS, Iteration: $ITERATION"
  
  if [ "$STATUS" = "succeeded" ]; then
    echo "✓ Task completed"
    echo "$RESULT" | jq '.result' | head -50
    break
  elif [ "$STATUS" = "failed" ]; then
    echo "✗ Task failed:"
    echo "$RESULT" | jq '.error'
    exit 1
  fi
  sleep 2
done
```

---

### Pillar 4: Extensible Architecture (Protocols)

- [ ] **LLMProvider Protocol:** Defined and implemented (LangChain wrapper)
- [ ] **Tool Protocol:** Defined; tools (read, write, shell, finish) implement it
- [ ] **Sandbox Protocol:** Defined and implemented (DockerSandbox)
- [ ] **Code Pointers:** Each protocol has clear implementation visible in codebase

**Verification:**
```bash
# Check that protocols are defined
grep -r "class LLMProvider" /root/CloudAgent/
grep -r "class Tool" /root/CloudAgent/
grep -r "class Sandbox\|class DockerSandbox" /root/CloudAgent/

# Check that tools inherit/implement Tool protocol
grep -r "class ReadFile\|class WriteFile\|class Shell\|class Finish" /root/CloudAgent/
```

---

## Four-Pillar Demo Checklist

Use this checklist to demonstrate CloudAgent to stakeholders:

### Demonstration Flow

1. **Start Backend**
   ```bash
   cd /root/CloudAgent/demo
   python run.py &  # uvicorn on :8000
   ```

2. **Show API Endpoints**
   ```bash
   echo "API Documentation:"
   echo "  POST /api/tasks"
   echo "  GET /api/tasks/{id}"
   ```

3. **Show Source Code (Pillars)**
   ```bash
   echo "Pillar 1 (Orchestration):"
   grep -n "POST /tasks\|GET /tasks" app/main.py | head -5
   
   echo "Pillar 2 (Sandbox):"
   ls -la app/sandbox.py
   
   echo "Pillar 3 (LLM + Tools):"
   ls -la agent/runner.py agent/tools.py
   
   echo "Pillar 4 (Protocols):"
   grep -n "class LLMProvider\|class Tool\|class Sandbox" SPECS.md | head -10
   ```

4. **Submit Demo Task**
   ```bash
   curl -X POST http://localhost:8000/api/tasks \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Find and summarize all TODO and FIXME comments in /workspace/repo. Write the summary to /workspace/out/report.md."}'
   ```

5. **Poll Task Status**
   ```bash
   # Copy task ID from above response
   curl http://localhost:8000/api/tasks/{id}
   ```

6. **Show Frontend (optional)**
   ```bash
   open http://localhost:8000/
   # or
   firefox http://localhost:8000/
   ```

7. **Verify Results**
   - Task reaches `succeeded` status
   - Result contains markdown summary
   - No errors or rejections for valid operations

---

## Rejection Test Cases

These operations **must be rejected** with clear error messages:

### Test Case: pip install (rejected)

```bash
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Please run: pip install numpy"}'

# Expected: Agent attempts shell("pip install numpy")
# Agent receives rejection: "Dependency installation not supported..."
# Agent should NOT execute pip install
```

### Test Case: git push (rejected)

```bash
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Push changes to GitHub using git push"}'

# Expected: Agent attempts to run git push
# Receives rejection: "Remote write operations not supported..."
# Should NOT execute
```

### Test Case: Private repo (rejected)

```bash
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Analyze https://github.com/my-private-org/secret-repo"}'

# Expected: Agent sees private URL
# Receives rejection: "Only vllm-project/vllm supported..."
# Should NOT attempt clone
```

**Verification:** Check agent's response in task result or error message.

---

## Minimal Frontend Test

If frontend is implemented:

1. **Open in Browser**
   ```bash
   open http://localhost:8000/
   ```

2. **Submit Task**
   - Enter: "Find all TODO/FIXME in /workspace/repo and summarize"
   - Click "Submit Task"
   - See task ID displayed

3. **Watch Status**
   - Status shows "queued" → "running" → "succeeded"
   - Iteration count increments

4. **View Result**
   - Markdown report displays in browser
   - Can scroll and read findings

---

## curl Demo Script (`scripts/demo.sh`)

```bash
#!/bin/bash
# CloudAgent Acceptance Test
# Usage: ./scripts/demo.sh [http://localhost:8000]

API_URL="${1:-http://localhost:8000}"
PROMPT="Find all TODO and FIXME comments in /workspace/repo and write a summary to /workspace/out/report.md"

echo "=== CloudAgent MVP Acceptance Test ==="
echo "API: $API_URL"
echo ""

# 1. Submit task
echo "1. Submitting task..."
RESPONSE=$(curl -s -X POST "$API_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"$PROMPT\"}")

TASK_ID=$(echo "$RESPONSE" | jq -r '.id')
echo "   Task ID: $TASK_ID"
echo ""

# 2. Poll for completion
echo "2. Polling task status..."
TIMEOUT=300  # 5 minutes
ELAPSED=0

while [ $ELAPSED -lt $TIMEOUT ]; do
  RESPONSE=$(curl -s "$API_URL/api/tasks/$TASK_ID")
  STATUS=$(echo "$RESPONSE" | jq -r '.status')
  ITERATION=$(echo "$RESPONSE" | jq -r '.iteration // 0')
  
  echo "   [$ELAPSED s] Status: $STATUS (iteration $ITERATION)"
  
  if [ "$STATUS" = "succeeded" ]; then
    echo "   ✓ Task completed successfully"
    echo ""
    break
  elif [ "$STATUS" = "failed" ]; then
    echo "   ✗ Task failed"
    ERROR=$(echo "$RESPONSE" | jq -r '.error')
    echo "   Error: $ERROR"
    exit 1
  fi
  
  sleep 3
  ELAPSED=$((ELAPSED + 3))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
  echo "   ✗ Task timeout (${TIMEOUT}s exceeded)"
  exit 1
fi

# 3. Display result
echo "3. Final result:"
echo ""
RESULT=$(echo "$RESPONSE" | jq -r '.result')
echo "$RESULT"
echo ""

# 4. Verify result is valid markdown
echo "4. Verification:"
if echo "$RESULT" | grep -q "TODO\|FIXME\|#"; then
  echo "   ✓ Result contains expected content"
else
  echo "   ⚠ Result may be incomplete"
fi

echo ""
echo "=== Test Complete ==="
```

**Run:**
```bash
chmod +x scripts/demo.sh
./scripts/demo.sh http://localhost:8000
```

---

## Automated pytest Suite (Optional)

If time permits, create `tests/acceptance_test.py`:

```python
import pytest
import requests
import time

API_URL = "http://localhost:8000"

def test_task_submission():
    """Test that tasks can be submitted."""
    response = requests.post(
        f"{API_URL}/api/tasks",
        json={"prompt": "Find TODO"}
    )
    assert response.status_code == 202
    data = response.json()
    assert "id" in data
    assert data["status"] == "queued"

def test_task_polling():
    """Test that task status can be polled."""
    # Submit
    response = requests.post(
        f"{API_URL}/api/tasks",
        json={"prompt": "Find TODO in /workspace/repo"}
    )
    task_id = response.json()["id"]
    
    # Poll
    for _ in range(180):  # 5 min timeout
        response = requests.get(f"{API_URL}/api/tasks/{task_id}")
        assert response.status_code == 200
        status = response.json()["status"]
        if status in ["succeeded", "failed"]:
            break
        time.sleep(2)
    
    assert status in ["succeeded", "failed"]

def test_rejection_pip_install():
    """Test that pip install is rejected."""
    response = requests.post(
        f"{API_URL}/api/tasks",
        json={"prompt": "Run: pip install numpy"}
    )
    task_id = response.json()["id"]
    
    # Wait for task
    time.sleep(10)
    
    response = requests.get(f"{API_URL}/api/tasks/{task_id}")
    result = response.json()
    # Should either fail or have error message mentioning rejection
    assert "not supported" in result.get("error", "").lower() or \
           "not supported" in result.get("result", "").lower()

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

**Run:**
```bash
pytest tests/acceptance_test.py -v
```

---

## Manual Verification Checklist

Before marking MVP complete, verify:

- [ ] **Backend running:** `curl http://localhost:8000/` returns response (not connection refused)
- [ ] **API responds:** `POST /api/tasks` returns 202; `GET /api/tasks/{id}` returns 200
- [ ] **Docker installed:** `docker ps` runs without error
- [ ] **LLM key set:** `echo $TOGETHER_API_KEY` is non-empty
- [ ] **Task executes:** Submit task, see status change to "running"
- [ ] **Agent loops:** Task iteration count > 2
- [ ] **Task completes:** Status reaches "succeeded" with result field populated
- [ ] **Result is markdown:** Output contains `#` headers and readable structure
- [ ] **Rejection works:** Try `pip install` task; receives error message
- [ ] **Container cleaned:** After task, `docker ps` shows no active cloudagent containers
- [ ] **Frontend loads:** `open http://localhost:8000/` or `curl http://localhost:8000/` returns HTML
- [ ] **Frontend works:** Can submit task and see result in browser
- [ ] **demo.sh passes:** `./scripts/demo.sh` exits with 0

---

## Success Metrics

**MVP is successful if:**

1. All four pillars are demonstrable via code and running system
2. vllm TODO/FIXME analysis task completes in < 5 minutes with meaningful output
3. No hangs, crashes, or unclear error messages
4. Rejection of `pip install` and `git push` is explicit and visible
5. Frontend (if implemented) shows task progress and final result
6. `demo.sh` can be run repeatedly with consistent results

---

## Known Limitations (Document These)

- [ ] Tasks not persisted across restarts
- [ ] Only vllm supported as demo repo; user repos not allowed
- [ ] No build/install operations inside sandbox
- [ ] No remote write (git push, PRs)
- [ ] Single worker (no concurrency)
- [ ] No real-time streaming of agent output
- [ ] Minimal error recovery (timeouts are terminal)

---

## Post-MVP Notes

After MVP acceptance, potential improvements (out of scope):

- [ ] SQLite persistence for task history
- [ ] Multi-worker pool (Redis queue)
- [ ] User-provided repo URLs with policy controls
- [ ] Real-time websocket streaming of agent output
- [ ] LangSmith tracing for debugging
- [ ] Artifact editing (EditFile tool)
- [ ] Sub-planning and step tracking
- [ ] GitHub App token for write operations
- [ ] Advanced rejection policies (machine-learning based)

---

## Test Script

**Location:** `scripts/demo.sh`

**Run:**
```bash
chmod +x scripts/demo.sh
./scripts/demo.sh http://localhost:8000
```

The script is self-contained (requires only `curl` and `jq`) and covers the two most critical acceptance flows end-to-end.

### What the script does

| Step | Action | Pass condition |
|---|---|---|
| 0 | Dependency check | `curl` and `jq` available on PATH |
| 1 | Server reachability | `http://localhost:8000` responds (any non-zero HTTP status) |
| 2 | POST /api/tasks | Returns HTTP 202 (or 200) and a JSON body with an `id` field |
| 3 | Initial status | Returned `status` is `"queued"` (confirms async dispatch) |
| 4 | Poll loop | Polls `GET /api/tasks/{id}` every 3 seconds, up to 60 polls (3 minutes) |
| 5 | Task success | Status reaches `"succeeded"` before the poll limit |
| 6 | Iteration count | `iteration` field is greater than 0 (agent loop ran) |
| 7 | Result present | `result` field is non-empty |
| 8 | Result content | Result contains `TODO`, `FIXME`, `#`, or `**` (markdown + task-relevant content) |
| 9 | Rejection probe | Submit `"run pip install requests"`; verify task fails or result/error contains rejection language |

### Expected output format

A successful run produces output similar to the following:

```
=== CloudAgent MVP Acceptance Demo ===
API : http://localhost:8000
Date: 2026-06-04T10:30:00Z

[PASS] Server is reachable at http://localhost:8000

--- Test 1: Submit main task (TODO/FIXME analysis) ---
       Raw submit response: {"id":"a1b2c3d4-...","status":"queued","created_at":"..."}
[PASS] POST /api/tasks returned 202 (task accepted)
[PASS] Task created with id=a1b2c3d4-...
[PASS] Initial status is 'queued' (async dispatch confirmed)

--- Test 2: Poll GET /api/tasks/{id} until terminal state ---
       Polling every 3s (max 60 polls = 180s)
       [poll  1/60] status=queued       iteration=0
       [poll  2/60] status=running      iteration=1
       [poll  3/60] status=running      iteration=3
       ...
       [poll 12/60] status=succeeded    iteration=7
[PASS] Task a1b2c3d4-... reached status=succeeded
[PASS] Agent iterated 7 time(s) — loop ran as expected
[PASS] Result field is populated
[PASS] Result contains expected TODO/FIXME references or markdown structure

--- Final result (first 40 lines) ---
# TODO/FIXME Summary — vllm-project/vllm

## Overview
Found 142 TODO and 23 FIXME comments across 67 files.
...

--- Test 3: Rejection case — 'run pip install requests' ---
       Rejection-probe task id=e5f6g7h8-...; waiting up to 30s for result
       Rejection-probe status: failed
       Rejection-probe error : Dependency installation not supported. Use provided environment.
[PASS] Rejection message found for 'pip install' probe

=== Demo Summary ===
ALL CHECKS PASSED — CloudAgent MVP acceptance demo succeeded.
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All checks passed — MVP acceptance criteria met |
| `1` | One or more checks failed — review `[FAIL]` lines in output |

### Failure modes and remediation

| Symptom | Likely cause | Fix |
|---|---|---|
| `[FAIL] Server not reachable` | Backend not started | `python3 run.py` |
| `[FAIL] POST /api/tasks — connection error` | Backend crashed after startup | Check worker logs |
| `[FAIL] Task timed out after 180s` | Sandbox creation failed or LLM unreachable | Check Docker daemon and `TOGETHER_API_KEY` |
| `[FAIL] result field is empty` | Agent finished without calling `finish()` | Review agent runner logic |
| `[FAIL] Unexpected outcome for pip install probe` | Tool policy not enforced | Review shell tool rejection logic in `SPECS.md` §8 |

