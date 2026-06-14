"""Unit tests for the agent loop and middleware.

Bug 1: Context overflow — tool output truncated to 4000 chars (CapOutputMiddleware);
        history trimmed to max_messages before each llm.complete() call
        (TrimHistoryMiddleware).
Bug 2: LLM errors returned as "succeeded" — is_error response now fails the task.
Bug 3: Iteration stays 0 / thought+plan not updated — _update_progress called
        BEFORE tools run, with thought "Iteration N: calling <tool>" and a plan.

Middleware tests: BudgetGuardMiddleware, TrimHistoryMiddleware, CapOutputMiddleware
are tested directly in addition to through run_agent integration.
"""

import asyncio
import sys
import os
import time
from uuid import uuid4

_DEMO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _DEMO_ROOT not in sys.path:
    sys.path.insert(0, _DEMO_ROOT)

from agent.runner import run_agent
from agent.middleware import (
    BudgetExceeded,
    BudgetGuardMiddleware,
    CapOutputMiddleware,
    MAX_MESSAGES,
    MAX_TOOL_OUTPUT_CHARS,
    TASK_TIME_LIMIT_SECONDS,
    TrimHistoryMiddleware,
    _cap_output,
    _trim_history,
)
from agent.tools import ShellTool


# ---------------------------------------------------------------------------
# Shared helpers / fakes
# ---------------------------------------------------------------------------

class FakeSandbox:
    """Minimal sandbox that records exec calls and returns configurable output."""

    def __init__(self, exec_stdout="output"):
        self._exec_stdout = exec_stdout
        self.exec_calls = 0

    def exec(self, cmd, timeout=60):
        self.exec_calls += 1
        return {"returncode": 0, "stdout": self._exec_stdout, "stderr": ""}

    def read(self, path, line_range=None):
        return "content"

    def write(self, path, content):
        return {"success": True}


def _make_task(prompt="test"):
    return {"prompt": prompt, "iteration": 0, "thought": None, "plan": None}


# ---------------------------------------------------------------------------
# Test 1: LLM error response causes task failure (Bug 2)
# ---------------------------------------------------------------------------

class _ErrorLLM:
    def complete(self, messages, tools, extra_callbacks=None):
        return {
            "is_error": True,
            "is_final": True,
            "text": "LLM call failed: 422",
            "tool_calls": [],
        }


def test_llm_error_returns_failed():
    task = _make_task()
    result = asyncio.run(run_agent(task, FakeSandbox(), _ErrorLLM()))
    assert result["status"] == "failed"
    assert "LLM call failed" in result["output"]


# ---------------------------------------------------------------------------
# Test 2: CapOutputMiddleware truncates tool output in history (Bug 1)
# ---------------------------------------------------------------------------

class _TruncationCaptureLLM:
    def __init__(self):
        self.calls = []

    def complete(self, messages, tools, extra_callbacks=None):
        self.calls.append(list(messages))
        if len(self.calls) == 1:
            return {
                "is_final": False,
                "is_error": False,
                "text": "",
                "tool_calls": [{"name": "shell", "arguments": {"command": "ls /workspace"}}],
            }
        return {"is_final": True, "is_error": False, "text": "report", "tool_calls": []}


def test_tool_output_truncated_in_history():
    """Bug 1: CapOutputMiddleware must truncate output before it enters history."""
    huge_stdout = "x" * 10_000
    sandbox = FakeSandbox(exec_stdout=huge_stdout)
    llm = _TruncationCaptureLLM()

    result = asyncio.run(run_agent(_make_task(), sandbox, llm))

    assert len(llm.calls) == 2
    assert result["status"] == "succeeded"

    shell_msgs = [
        m for m in llm.calls[1]
        if m.get("role") == "user" and "Tool result for shell:" in m.get("content", "")
    ]
    assert shell_msgs, "Expected tool result message in second LLM call"
    content = shell_msgs[0]["content"]
    assert len(content) <= 4200
    assert "[...truncated" in content


# ---------------------------------------------------------------------------
# Test 3: iteration increments BEFORE tools run (Bug 3)
# ---------------------------------------------------------------------------

class _IterationCheckLLM:
    def __init__(self):
        self._call_count = 0

    def complete(self, messages, tools, extra_callbacks=None):
        self._call_count += 1
        if self._call_count == 1:
            return {
                "is_final": False, "is_error": False, "text": "",
                "tool_calls": [{"name": "shell", "arguments": {"command": "ls /workspace"}}],
            }
        return {"is_final": True, "is_error": False, "text": "done", "tool_calls": []}


def test_iteration_increments_before_tools_run():
    task = _make_task()
    iteration_at_exec = []

    class _CapturingSandbox(FakeSandbox):
        def exec(self, cmd, timeout=60):
            iteration_at_exec.append(task["iteration"])
            return super().exec(cmd, timeout)

    result = asyncio.run(run_agent(task, _CapturingSandbox(), _IterationCheckLLM()))
    assert result["status"] == "succeeded"
    assert iteration_at_exec and iteration_at_exec[0] == 1


# ---------------------------------------------------------------------------
# Test 4: thought and plan are populated on _update_progress (Bug 3)
# ---------------------------------------------------------------------------

class _ThoughtCaptureLLM:
    def __init__(self):
        self._call_count = 0

    def complete(self, messages, tools, extra_callbacks=None):
        self._call_count += 1
        if self._call_count == 1:
            return {
                "is_final": False, "is_error": False, "text": "",
                "tool_calls": [{"name": "shell", "arguments": {"command": "ls /workspace"}}],
            }
        return {"is_final": True, "is_error": False, "text": "done", "tool_calls": []}


def test_thought_and_plan_are_set():
    task = _make_task()
    thought_at_exec, plan_at_exec = [], []

    class _ObservingSandbox(FakeSandbox):
        def exec(self, cmd, timeout=60):
            thought_at_exec.append(task.get("thought"))
            plan_at_exec.append(task.get("plan"))
            return super().exec(cmd, timeout)

    result = asyncio.run(run_agent(task, _ObservingSandbox(), _ThoughtCaptureLLM()))
    assert result["status"] == "succeeded"
    assert thought_at_exec and "Iteration 1" in thought_at_exec[0]
    assert task.get("plan") == "Step 2 of max 50"


# ---------------------------------------------------------------------------
# Test 5: TrimHistoryMiddleware (Bug 1)
# ---------------------------------------------------------------------------

def test_history_trimmed_before_llm_call():
    """_trim_history and TrimHistoryMiddleware must enforce max_messages."""
    long_history = list(range(25))

    # Direct function (supports custom max_messages)
    trimmed = _trim_history(long_history, max_messages=20)
    assert len(trimmed) == 20
    assert trimmed[0] == 0 and trimmed[1] == 1
    assert trimmed[2] == 7   # first tail item: 25-18=7
    assert trimmed[-1] == 24

    # Short list returned unchanged
    short = list(range(10))
    assert _trim_history(short, max_messages=20) == short

    # Always <= max_messages
    for n in (0, 1, 2, 19, 20, 21, 100):
        out = _trim_history(list(range(n)), max_messages=20)
        assert len(out) <= 20

    # RunnableLambda wrapper behaves identically
    assert TrimHistoryMiddleware.invoke(long_history) == trimmed


# ---------------------------------------------------------------------------
# Test 6: CapOutputMiddleware unit tests
# ---------------------------------------------------------------------------

def test_cap_output_middleware_truncates():
    long = "x" * (MAX_TOOL_OUTPUT_CHARS + 1000)
    result = CapOutputMiddleware.invoke(long)
    assert len(result) <= MAX_TOOL_OUTPUT_CHARS + 60
    assert "[...truncated" in result
    assert result.startswith("x" * MAX_TOOL_OUTPUT_CHARS)


def test_cap_output_middleware_passthrough():
    short = "hello"
    assert CapOutputMiddleware.invoke(short) == short


def test_cap_output_function_direct():
    s = "y" * 5000
    out = _cap_output(s, max_chars=100)
    assert len(out) <= 160
    assert "[...truncated, 5000 chars total]" in out


# ---------------------------------------------------------------------------
# Test 7: BudgetGuardMiddleware (replaces guard_budget)
# ---------------------------------------------------------------------------

def test_budget_guard_raises_when_exceeded():
    """BudgetGuardMiddleware must raise BudgetExceeded when time limit is hit."""
    past = time.monotonic() - (TASK_TIME_LIMIT_SECONDS + 1)
    guard = BudgetGuardMiddleware(start_monotonic=past)
    try:
        guard.on_chat_model_start({}, [], run_id=uuid4())
        assert False, "Expected BudgetExceeded"
    except BudgetExceeded:
        pass


def test_budget_guard_does_not_raise_within_limit():
    """BudgetGuardMiddleware must not raise when the loop just started."""
    guard = BudgetGuardMiddleware(start_monotonic=time.monotonic())
    guard.on_chat_model_start({}, [], run_id=uuid4())  # must not raise


def test_budget_guard_propagates_through_run_agent():
    """BudgetExceeded raised via callback must surface as status=failed."""

    class _SlowLLM:
        def complete(self, messages, tools, extra_callbacks=None):
            for cb in (extra_callbacks or []):
                if hasattr(cb, "on_chat_model_start"):
                    cb.on_chat_model_start({}, [], run_id=uuid4())
            return {"is_final": True, "is_error": False, "text": "done", "tool_calls": []}

    past = time.monotonic() - (TASK_TIME_LIMIT_SECONDS + 1)

    class _ExpiredBudgetLLM:
        def complete(self, messages, tools, extra_callbacks=None):
            for cb in (extra_callbacks or []):
                if isinstance(cb, BudgetGuardMiddleware):
                    cb._start = past  # force expiry
                    cb.on_chat_model_start({}, [], run_id=uuid4())
            return {"is_final": True, "is_error": False, "text": "done", "tool_calls": []}

    result = asyncio.run(run_agent(_make_task(), FakeSandbox(), _ExpiredBudgetLLM()))
    assert result["status"] == "failed"
    assert "time limit" in result["output"].lower()


# ---------------------------------------------------------------------------
# Test 8: ShellTool.check allow-list
# ---------------------------------------------------------------------------

def test_shell_check_allows_rg():
    assert ShellTool.check("rg -n 'TODO|FIXME' /workspace/repo") is None


def test_shell_check_allows_git_log():
    assert ShellTool.check("git -C /workspace/repo log --oneline -5") is None


def test_shell_check_allows_git_show():
    assert ShellTool.check("git -C /workspace/repo show --stat HEAD") is None


def test_shell_check_rejects_git_push():
    reason = ShellTool.check("git push origin master")
    assert reason is not None and "not supported" in reason.lower()


def test_shell_check_rejects_pip_install():
    assert ShellTool.check("pip install requests") is not None


def test_shell_check_rejects_curl():
    assert ShellTool.check("curl https://example.com") is not None


def test_shell_check_rejects_unknown_head():
    reason = ShellTool.check("python3 script.py")
    assert reason is not None and "allow-list" in reason


def test_shell_check_allows_quoted_pipe_in_regex():
    assert ShellTool.check("rg 'TODO|FIXME' /workspace/repo") is None


def test_shell_check_rejects_git_unknown_subcommand():
    reason = ShellTool.check("git -C /workspace/repo clone https://x.com")
    assert reason is not None and "clone" in reason
