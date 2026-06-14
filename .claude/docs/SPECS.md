# Technical Specification — CloudAgent MVP

## Overview

CloudAgent is a minimal autonomous agent platform that executes user tasks in isolated Docker sandboxes using LLM-driven tool orchestration. This spec defines APIs, data models, protocols, and tool behavior.

**Binding reference:** This document is the source of truth for all agents. `skeleton.py` is a reference sketch; deviations are documented below.

---

## 1. Architecture: Three Protocols

### 1.1 LLMProvider Protocol

Interface for LLM completion with tool calling support.

```python
class LLMProvider(Protocol):
    """
    Wraps LLM API (e.g., LangChain ChatOpenAI).
    Accepts conversation history and tool schemas.
    Returns parsed tool calls or final response.
    """
    def complete(
        self, 
        messages: list[dict],           # [{"role": "system", "content": ...}, ...]
        tools: list[dict]               # JSON schema of available tools
    ) -> dict:  # {"is_final": bool, "text": str, "tool_calls": [...]}
        ...
```

**Implementation:** LangChain wrapper
- **Model:** `Qwen/Qwen2.5-7B-Instruct-Turbo` via Together AI API
- **Base URL:** `https://api.together.xyz/v1`
- **Auth:** `TOGETHER_API_KEY` env var on worker process only (never in container)
- **Message format:** OpenAI-compatible (role/content)
- **Tool schema:** OpenAI function calling format

Example (sketch):
```python
from langchain_openai import ChatOpenAI
import json

llm_raw = ChatOpenAI(
    model="Qwen/Qwen2.5-7B-Instruct-Turbo",
    base_url="https://api.together.xyz/v1",
    api_key=os.environ["TOGETHER_API_KEY"],
    temperature=0.7
)

class LangChainProvider:
    def complete(self, messages, tools):
        # Bind tools to LLM, invoke, parse response
        ...
```

### 1.2 Tool Protocol

Interface for executable operations in the sandbox.

```python
class Tool(Protocol):
    """
    A single action the agent can take.
    Runs inside the Sandbox context.
    """
    name: str                           # e.g. "read", "write", "shell"
    description: str                    # For LLM prompt
    schema: dict                        # JSON schema of tool input args
    
    def run(self, args: dict, sandbox: "Sandbox") -> dict:
        # Execute tool inside sandbox
        # Return {"success": bool, "output": str, "error": str}
        ...
```

**Scope:** Simple, read-heavy tools only. Details in § 2 (Tool Registry).

### 1.3 Sandbox Protocol

Interface for isolated execution environment.

```python
class Sandbox(Protocol):
    """
    One-time, ephemeral execution context.
    Implements read/write/exec isolation.
    """
    def exec(self, cmd: str, timeout: int = 60) -> dict:
        # Execute shell command in sandbox
        # Return {"returncode": int, "stdout": str, "stderr": str}
        ...
    
    def read(self, path: str, line_range: tuple[int, int] | None = None) -> str:
        # Read file, optionally with line range (1-indexed, inclusive)
        # Return file content as string
        # Raise FileNotFoundError, PermissionError as needed
        ...
    
    def write(self, path: str, content: str) -> dict:
        # Write content to file (create or overwrite)
        # Return {"success": bool, "error": str}
        ...
    
    def destroy(self):
        # Clean up resources, stop container
        ...
```

**Implementation:** Docker-based
- See § 3 (Sandbox: Docker Implementation)

---

## 2. Agent & Tool Layer

### 2.1 Core Loop (run_agent)

```python
async def run_agent(task: Task, sandbox: Sandbox, llm: LLMProvider):
    """
    Main agent loop: observe → think → act.
    """
    max_iterations = 50
    history = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": task.prompt}
    ]
    
    for iteration in range(max_iterations):
        # Check budgets (timeout, token count)
        guard_budget(task)
        
        # Think: get LLM response with tool calls
        response = llm.complete(history, tool_registry.schemas())
        
        # Act: if final, return result
        if response["is_final"]:
            return {"status": "succeeded", "output": response["text"]}
        
        # Act: call tools
        tool_results = []
        for tool_call in response["tool_calls"]:
            tool_name = tool_call["name"]
            tool_args = tool_call["arguments"]  # parsed dict
            
            # Check policy (reject unknown/unsafe tools)
            if not tool_registry.is_allowed(tool_name):
                result = {
                    "success": False,
                    "output": "",
                    "error": f"Tool '{tool_name}' not available in this context"
                }
            else:
                # Execute tool in sandbox
                tool = tool_registry.get(tool_name)
                result = tool.run(tool_args, sandbox)
            
            tool_results.append({
                "tool": tool_name,
                "input": tool_args,
                "result": result
            })
        
        # Observe: add results to history
        for tr in tool_results:
            history.append({
                "role": "assistant",
                "content": f"Executed {tr['tool']}: {json.dumps(tr['result'])}"
            })
        
        # Update task progress
        task.iteration = iteration + 1
        task.last_activity = datetime.now()
    
    # Exhausted iterations
    return {"status": "failed", "output": "Max iterations reached"}
```

### 2.2 Tool Registry & Definitions

**Implemented tools:**

#### a. **ReadFile**
- **Name:** `read` or `ReadFile` (agent sees both as available)
- **Purpose:** Read file content, optionally with line range
- **Input schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "path": {"type": "string", "description": "File path (relative to /workspace)"},
      "line_start": {"type": "integer", "description": "Start line (1-indexed, optional)"},
      "line_end": {"type": "integer", "description": "End line inclusive (optional)"}
    },
    "required": ["path"]
  }
  ```
- **Execution:** `sandbox.read(path, (line_start, line_end))`
- **Output:** File content or error message
- **Rejection cases:** None—read is always allowed

#### b. **WriteFile**
- **Name:** `write` or `WriteFile`
- **Purpose:** Write markdown report or analysis output
- **Input schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "path": {"type": "string", "description": "File path (e.g., /workspace/out/report.md)"},
      "content": {"type": "string", "description": "File content"}
    },
    "required": ["path", "content"]
  }
  ```
- **Execution:** `sandbox.write(path, content)`
- **Output:** Success or error
- **Scope:** Writes to `/workspace/out/` only for reports; error if trying to modify source files

#### c. **Shell** (limited)
- **Name:** `shell` or `Shell`
- **Purpose:** Execute read-only shell commands (grep, rg, find, wc, etc.)
- **Input schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "command": {"type": "string", "description": "Shell command (grep, rg, find, etc.)"}
    },
    "required": ["command"]
  }
  ```
- **Execution:** `sandbox.exec(command, timeout=60)`
- **Output:** stdout, stderr, return code
- **Rejection cases:**
  - `pip install` / `npm install` → **Error:** "Dependency installation not supported. Use provided environment."
  - `git push`, `git PR`, GitHub CLI write ops → **Error:** "Remote write operations not supported."
  - `cd /workspace/repo && cargo build` (or any heavy build) → **Error:** "Build operations not supported in this context."
  - `curl` to arbitrary URLs → **Error:** "Network operations limited to package managers (via policy)."
  - Timeout (>60s) → **Error:** "Command exceeded time limit."

#### d. **Finish**
- **Name:** `finish`
- **Purpose:** Signal completion; return final report to user
- **Input schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "output": {"type": "string", "description": "Final markdown report or summary"}
    },
    "required": ["output"]
  }
  ```
- **Execution:** Writes `output` to task result, sets task status = `succeeded`
- **Output:** Immediate return from agent loop

### 2.3 System Prompt (sketch)

```
You are an autonomous code analysis agent. You have access to a GitHub repository cloned in /workspace/repo.

Your tools:
- read(path, line_start=None, line_end=None): Read file content
- write(path, content): Write markdown reports to /workspace/out/
- shell(command): Run grep, rg, find, wc (read-only analysis commands only)
- finish(output): Return final report and exit

Your goal: {user_task}

Analysis strategy:
1. Use shell (rg/grep) to locate patterns (TODO, FIXME, etc.)
2. Read relevant source files to understand context
3. Summarize findings in markdown
4. Write final report with finish()

Do not attempt:
- pip install, build commands, git operations
- Access private repositories
- Modify source code (only write to /workspace/out/)

Start by exploring the repository structure.
```

---

## 3. Backend & Orchestration

### 3.1 Task Model

```python
@dataclass
class Task:
    id: str                             # UUID
    prompt: str                         # User's natural language request
    status: str                         # "queued" | "running" | "succeeded" | "failed"
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result: str | None                  # Markdown output or error
    iteration: int = 0                  # Current loop iteration
    error: str | None                   # Terminal error if failed
```

### 3.2 REST API

#### POST /tasks

**Request:**
```json
{
  "prompt": "Find all TODO/FIXME in /workspace/repo and summarize."
}
```

**Response (202 Accepted):**
```json
{
  "id": "task-uuid-1234",
  "status": "queued",
  "created_at": "2026-06-04T10:30:00Z"
}
```

**Implementation:**
- Generate UUID for task
- Create Task object (status = "queued")
- Enqueue task ID into memory queue
- Return task ID immediately (async)

#### GET /tasks/{id}

**Response (if queued or running):**
```json
{
  "id": "task-uuid-1234",
  "status": "running",
  "created_at": "2026-06-04T10:30:00Z",
  "started_at": "2026-06-04T10:30:05Z",
  "iteration": 3
}
```

**Response (if succeeded):**
```json
{
  "id": "task-uuid-1234",
  "status": "succeeded",
  "created_at": "2026-06-04T10:30:00Z",
  "started_at": "2026-06-04T10:30:05Z",
  "completed_at": "2026-06-04T10:35:00Z",
  "result": "# TODO/FIXME Summary\n\n- Line 45: TODO implement feature X\n..."
}
```

**Response (if failed):**
```json
{
  "id": "task-uuid-1234",
  "status": "failed",
  "error": "Docker sandbox creation failed"
}
```

**Implementation:**
- Lookup task by ID (memory store)
- Return current state
- No polling limit (poll as often as needed)

### 3.3 Worker Loop

```python
def worker_loop(queue, sandbox_factory, llm):
    """
    Main background worker. Runs continuously.
    """
    while True:
        task_id = queue.dequeue(timeout=1)
        if not task_id:
            continue
        
        task = tasks_db[task_id]
        task.status = "running"
        task.started_at = datetime.now()
        
        sandbox = None
        try:
            # Create isolated environment (vllm clone happens inside create())
            sandbox = sandbox_factory.create(task)
            
            # Ensure output directory exists
            sandbox.exec("mkdir -p /workspace/out")
            
            # Run agent
            result = run_agent(task, sandbox, llm)
            
            task.status = "succeeded"
            task.result = result.get("output", "")
            
        except TimeoutError:
            task.status = "failed"
            task.error = "Task execution timeout"
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
        finally:
            if sandbox:
                sandbox.destroy()
            task.completed_at = datetime.now()
```

### 3.4 In-Memory Task Store

```python
tasks_db = {}  # {task_id: Task}
queue = deque()

def enqueue(task_id):
    queue.append(task_id)

def dequeue(timeout=1):
    try:
        return queue.popleft()
    except IndexError:
        return None
```

---

## 4. Sandbox: Docker Implementation

### 4.1 Container Image

Use lightweight base: `python:3.11-slim`

Pre-install:
- `git`
- `ripgrep` (`rg`)
- `grep`, `find`, `wc`, `cat`, `head`

Dockerfile (minimal):
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y git ripgrep && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
RUN mkdir -p /workspace/out /workspace/repo
ENTRYPOINT ["/bin/bash"]
```

### 4.2 DockerSandbox Implementation

```python
import docker
import os

class DockerSandbox:
    def __init__(self, container):
        self.container = container
    
    @classmethod
    def create(cls, task: Task) -> "DockerSandbox":
        """
        Create and start a one-time sandbox container.
        """
        client = docker.from_env()
        container = client.containers.run(
            image="cloudagent-sandbox:latest",
            detach=True,
            working_dir="/workspace",
            stdout=True,
            stderr=True,
            # Resource limits
            mem_limit="2g",
            cpus=1.0,
            # No host volume mounts (ephemeral only)
            network_mode="bridge"
        )
        return cls(container)
    
    def exec(self, cmd: str, timeout: int = 60) -> dict:
        """
        Execute shell command inside container.
        """
        try:
            exit_code, output = self.container.exec_run(
                cmd,
                stdout=True,
                stderr=True,
                stdin=False,
                shell=True
            )
            return {
                "returncode": exit_code,
                "stdout": output.decode("utf-8", errors="replace"),
                "stderr": ""  # Combined with stdout
            }
        except Exception as e:
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": str(e)
            }
    
    def read(self, path: str, line_range: tuple[int, int] | None = None) -> str:
        """
        Read file from container. Optionally extract lines.
        """
        try:
            # Use exec to cat file
            full_path = f"/workspace/{path}" if not path.startswith("/workspace") else path
            exit_code, output = self.container.exec_run(
                f"cat {full_path}",
                stdout=True
            )
            content = output.decode("utf-8", errors="replace")
            
            if line_range:
                lines = content.split("\n")
                start, end = line_range
                # 1-indexed, inclusive
                content = "\n".join(lines[start-1:end])
            
            return content
        except Exception as e:
            raise FileNotFoundError(f"Cannot read {path}: {e}")
    
    def write(self, path: str, content: str) -> dict:
        """
        Write content to file in container.
        """
        try:
            full_path = f"/workspace/{path}" if not path.startswith("/workspace") else path
            # Use exec + tee
            self.container.exec_run(
                f"tee {full_path}",
                input=content.encode("utf-8")
            )
            return {"success": True, "error": None}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def destroy(self):
        """
        Stop and remove container.
        """
        self.container.stop()
        self.container.remove()
```

---

## 5. Frontend (Minimal)

### 5.1 Single-Page HTML

```html
<!DOCTYPE html>
<html>
<head>
  <title>CloudAgent Task Submission</title>
  <style>
    body { font-family: sans-serif; max-width: 800px; margin: 50px auto; }
    textarea { width: 100%; height: 100px; }
    button { padding: 10px 20px; cursor: pointer; }
    #result { margin-top: 20px; border: 1px solid #ccc; padding: 10px; }
    #status { color: #666; font-size: 0.9em; }
  </style>
</head>
<body>
  <h1>CloudAgent Task Submission</h1>
  <form id="taskForm">
    <label for="prompt">Task Prompt (default: find TODO/FIXME):</label><br/>
    <textarea id="prompt" placeholder="Enter task description..."></textarea><br/>
    <button type="submit">Submit Task</button>
  </form>
  
  <div id="status"></div>
  <div id="result"></div>
  
  <script>
    const form = document.getElementById("taskForm");
    const statusDiv = document.getElementById("status");
    const resultDiv = document.getElementById("result");
    
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const prompt = document.getElementById("prompt").value || 
        "Clone completed. Find all TODO/FIXME in /workspace/repo. Summarize findings in markdown.";
      
      // POST task
      const postResp = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt })
      });
      const { id } = await postResp.json();
      
      statusDiv.innerText = `Task submitted: ${id}. Waiting for results...`;
      resultDiv.innerHTML = "";
      
      // Poll for completion
      const poll = setInterval(async () => {
        const getResp = await fetch(`/api/tasks/${id}`);
        const task = await getResp.json();
        statusDiv.innerText = `Status: ${task.status} (iteration ${task.iteration || 0})`;
        
        if (task.status === "succeeded") {
          clearInterval(poll);
          resultDiv.innerHTML = `<h2>Result</h2><pre>${escapeHtml(task.result)}</pre>`;
        } else if (task.status === "failed") {
          clearInterval(poll);
          resultDiv.innerHTML = `<h2>Error</h2><pre>${escapeHtml(task.error)}</pre>`;
        }
      }, 1000);
    });
    
    function escapeHtml(text) {
      const div = document.createElement("div");
      div.innerText = text;
      return div.innerHTML;
    }
  </script>
</body>
</html>
```

---

## 6. LLM Stack Details

### 6.1 Together AI + Qwen

**Provider:** Together AI (together.xyz)
**Model:** Qwen/Qwen2.5-7B-Instruct-Turbo
**API:** OpenAI-compatible REST endpoint

**Configuration (LangChain):**
```python
from langchain_openai import ChatOpenAI

class LangChainProvider:
    def __init__(self, api_key: str):
        self.llm = ChatOpenAI(
            model="Qwen/Qwen2.5-7B-Instruct-Turbo",
            base_url="https://api.together.xyz/v1",
            api_key=api_key,
            temperature=0.7,
            timeout=30
        )
    
    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        # Bind tools as functions
        llm_with_tools = self.llm.bind_tools(tools)
        response = llm_with_tools.invoke(messages)
        
        # Parse response
        if response.tool_calls:
            return {
                "is_final": False,
                "tool_calls": [
                    {
                        "name": tc["name"],
                        "arguments": tc["args"]
                    }
                    for tc in response.tool_calls
                ]
            }
        else:
            return {
                "is_final": True,
                "text": response.content
            }
```

### 6.2 Environment

- **Worker process:** TOGETHER_API_KEY environment variable
- **Container:** No API keys; only sandbox tooling
- **Timeouts:** 30s per LLM call; 60s per tool execution; 5min per task max

---

## 7. Demo Scenario (Default)

### 7.1 Default Task Prompt

```
Clone completed. The repository vllm-project/vllm is available at /workspace/repo.

Find all TODO and FIXME comments in the codebase. 
Search systematically using grep or rg to locate them.
Read the files containing these comments to understand context.
Summarize your findings in a well-structured markdown report.

Write the final report to /workspace/out/report.md using the write tool.
```

### 7.2 Expected Flow

1. User submits prompt via UI or curl
2. Task enqueued; API returns task ID
3. Worker picks up task:
   - Create Docker container
   - Clone vllm (shallow) → /workspace/repo
   - Start agent loop with LLM
4. Agent thinks → calls shell("rg 'TODO|FIXME'")
5. Agent reads top files → calls read()
6. Agent writes report → calls write("/workspace/out/report.md", "# Findings...")
7. Agent calls finish() → loop exits
8. Worker destroys container
9. User polls API, receives markdown report
10. Frontend displays markdown in browser

---

## 8. Error Handling & Rejection

### 8.1 Rejection Categories

| Operation | Status | Response |
|-----------|--------|----------|
| `pip install`, `npm install` | 400 | "Dependency installation not supported. Sandbox provides required tools." |
| `git push`, `gh pr create` | 400 | "Remote write operations not supported in this context." |
| User-provided repo URL | 400 | "Only vllm-project/vllm supported in this MVP." |
| Private repository access | 400 | "Private repositories not supported." |
| Task timeout (5min) | 504 | "Task execution exceeded time limit." |
| Container creation fail | 500 | "Sandbox initialization failed." |

### 8.2 LLM Behavior on Rejection

When tool call is rejected:
```python
history.append({
    "role": "assistant",
    "content": f"Tool '{tool_name}' not available: {rejection_reason}"
})
# Next iteration, LLM receives error and should adjust strategy
```

This allows agent to recover (e.g., "I can't install packages, let me search with rg instead").

---

## 9. Deviations from skeleton.py

1. **No Plan/Step persistence:** Skeleton includes Plan with step tracking. MVP uses simple iteration counter only.
2. **No policy engine:** Skeleton references `check_policy(task.policy, call)`. MVP uses hardcoded tool allow-list.
3. **Single worker, no multi-tenant:** Skeleton shows tenant_id; MVP is single-user in-memory demo.
4. **No GitHub token injection:** Skeleton mentions "注入 token". MVP forbids push entirely.
5. **No artifact editing:** Skeleton mentions EditFile for partial edits. MVP offers only read/write.

These simplifications are intentional for the 8-hour scope. Document them in ROLE_CONTRACTS.md.

---

## 10. Testing & Verification (outline)

See `ACCEPTANCE.md` for concrete curl/script tests.

Quick checks:
- `curl -X POST http://localhost:8000/api/tasks -H "Content-Type: application/json" -d '{"prompt": "..."}'`
- `curl http://localhost:8000/api/tasks/{id}` → poll until status = "succeeded"
- Check `/workspace/out/report.md` in final output

