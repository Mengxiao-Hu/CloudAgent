"""
CloudAgent — architecture skeleton (pseudocode reference)

Four design pillars are annotated where they naturally appear:
  [orchestration]  agent scheduling and task lifecycle
  [sandbox]        isolated execution environment
  [llm]            LLM integration and tool-calling loop
  [architecture]   protocol seams that make each axis swappable

Binding spec: .claude/docs/SPECS.md
This file is a reference sketch — implementations in demo/ may simplify.
"""

from typing import Protocol
from dataclasses import dataclass

MAX_ITERATIONS = 50


# ============================================================
# [architecture] Protocol seams: one interface per axis of change.
# Swap model / add tool / change isolation backend without touching run_agent().
# ============================================================

class LLMProvider(Protocol):
    def complete(self, messages: list[dict], tool_schemas: list[dict]) -> dict:
        # Returns {"is_final": bool, "is_error": bool, "text": str, "tool_calls": [...]}
        ...


class Tool(Protocol):
    name: str
    description: str
    schema: dict  # JSON schema shown to the LLM

    def run(self, args: dict, sandbox: "Sandbox") -> dict:
        # Tools execute inside the sandbox, not on the worker host.
        # Returns {"success": bool, "output": str, "error": str | None}
        ...


class Sandbox(Protocol):
    def exec(self, cmd: str, timeout: int) -> dict: ...   # {"returncode", "stdout", "stderr"}
    def read(self, path: str, line_range=None) -> str: ... # optional (start, end) line range
    def write(self, path: str, content: str) -> dict: ...
    def destroy(self) -> None: ...


# ============================================================
# [sandbox] Ephemeral isolation. Demo uses Docker; swap to Firecracker
# by implementing the same Sandbox protocol.
# Key constraints:
#   - vllm repo mounted read-only from a named Docker volume (pre-cloned once)
#   - LLM API key stays in the worker process; never injected into the container
#   - Write access restricted to /workspace/out/
# ============================================================
class DockerSandbox:
    @classmethod
    def create(cls, task) -> "DockerSandbox":
        # - Ephemeral container (tail -f /dev/null to stay alive for exec_run)
        # - Resource limits: mem_limit=2g, nano_cpus=1e9
        # - Mount named volume cloudagent-vllm-repo → /workspace/repo (read-only)
        # - network_mode=bridge (outbound allowed; agent does not need to push)
        ...

    def destroy(self) -> None:
        # container.stop() + container.remove(force=True)
        ...


# ============================================================
# [orchestration] Task is the unit of work in the queue.
# ============================================================
@dataclass
class Task:
    id: str
    prompt: str
    status: str = "queued"   # queued | running | succeeded | failed
    iteration: int = 0
    thought: str | None = None  # live LLM reasoning (set each iteration)
    plan: str | None = None     # current step description
    result: str | None = None
    error: str | None = None


# ---- API layer: stateless, enqueue and read back ----
def POST_api_tasks(prompt: str) -> str:
    task = Task(id=new_id(), prompt=prompt)
    store.tasks[task.id] = task
    queue.enqueue(task.id)
    return task.id  # async: returns immediately


# ---- [orchestration] Worker: pulls tasks, runs agent, updates state ----
def worker_loop(queue, sandbox_factory, llm) -> None:
    while True:
        task_id = queue.dequeue(timeout=1)
        task = store.tasks[task_id]
        task.status = "running"
        sandbox = sandbox_factory.create(task)
        try:
            result = run_agent(task, sandbox, llm)
            task.status = result["status"]
            if result["status"] == "failed":
                task.error = result["output"]
            else:
                task.result = result["output"]
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
        finally:
            sandbox.destroy()


# ============================================================
# [llm] + [orchestration] Core agent loop: observe → think → act.
# ============================================================
async def run_agent(task: Task, sandbox: Sandbox, llm: LLMProvider) -> dict:
    history = [
        {"role": "system", "content": system_prompt()},
        {"role": "user",   "content": task.prompt},
    ]

    for iteration in range(MAX_ITERATIONS):
        guard_budget(task)                           # wall-clock + iteration limit

        history = trim_history(history)              # keep context within token limit
        response = llm.complete(history, tool_registry.schemas())

        if response.get("is_error"):
            return {"status": "failed", "output": response["text"]}

        tool_calls = response.get("tool_calls") or []

        if response.get("is_final") and not tool_calls:
            return {"status": "succeeded", "output": response["text"]}

        # Update visible progress before tools run so the UI reflects the current step.
        task.iteration = iteration + 1
        task.thought = f"Iteration {iteration + 1}: calling {', '.join(tc['name'] for tc in tool_calls)}"

        for call in tool_calls:
            tool = tool_registry.get(call["name"])
            result = tool.run(call["arguments"], sandbox)

            if result.get("is_final"):               # finish() tool short-circuits
                return {"status": "succeeded", "output": result["output"]}

            # Truncate large outputs before adding to history to stay within context limit.
            if len(result.get("output", "")) > MAX_TOOL_OUTPUT_CHARS:
                result["output"] = result["output"][:MAX_TOOL_OUTPUT_CHARS] + " [...truncated]"

            # Use "user" role so the model treats tool results as environment
            # observations, not its own prior output.
            history.append({
                "role": "user",
                "content": f"Tool result for {call['name']}: {result}",
            })

    return {"status": "failed", "output": "Max iterations reached."}


# ============================================================
# [architecture] Tools are thin wrappers over the Sandbox interface.
# ============================================================
class ReadFileTool:
    name = "read"
    def run(self, args, sandbox):
        return sandbox.read(args["path"], args.get("line_range"))

class WriteFileTool:
    name = "write"
    def run(self, args, sandbox):
        # Writes restricted to /workspace/out/ — source files are read-only.
        return sandbox.write(args["path"], args["content"])

class ShellTool:
    name = "shell"
    def run(self, args, sandbox):
        # Allow-list: grep, rg, find, wc, cat, head, ls, git log/status/show/diff
        # Reject: pip install, npm, cargo build, git push, curl, wget
        return sandbox.exec(args["command"], timeout=60)

class FinishTool:
    name = "finish"
    def run(self, args, sandbox):
        return {"success": True, "output": args["output"], "is_final": True}


# ============================================================
# Devin trace → skeleton mapping (what each part corresponds to):
#   "On it. I'll clone..."           → worker_loop sandbox setup
#   "Thought for Xs"                 → llm.complete() think step
#   "Read file.py:36-65"             → ReadFileTool(line_range) — context control
#   "Searching for TODO..."          → ShellTool → sandbox.exec("rg ...")
#   "Created report.md"              → WriteFileTool → sandbox.write(...)
#   pip error → retry with fix       → observe result → next think (self-correction)
#   Final summary in chat            → FinishTool → task.result
# ============================================================
