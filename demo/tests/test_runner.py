"""Unit tests for three bug fixes in agent/runner.py.

Bug 1: Context overflow — tool output truncated to 4000 chars; history trimmed
        to max_messages before each llm.complete() call.
Bug 2: LLM errors returned as "succeeded" — is_error response now fails the task.
Bug 3: Iteration stays 0 / thought+plan not updated — _update_progress called
        BEFORE tools run, with thought "Iteration N: calling <tool>" and a plan.
"""

import asyncio
import sys
import os
import time

# Ensure the demo package root is on sys.path so `from agent.runner import ...`
# resolves correctly when pytest is invoked from /root/CloudAgent/demo/.
_DEMO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _DEMO_ROOT not in sys.path:
    sys.path.insert(0, _DEMO_ROOT)

from agent.runner import _trim_history, run_agent, guard_budget, BudgetExceeded, TASK_TIME_LIMIT_SECONDS
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
    """Return a minimal dict-based task compatible with runner duck-typing."""
    return {"prompt": prompt, "iteration": 0, "thought": None, "plan": None}


# ---------------------------------------------------------------------------
# Test 1: LLM error response causes task failure (Bug 2)
# ---------------------------------------------------------------------------

class _ErrorLLM:
    """Always returns an is_error response on the first call."""

    def complete(self, messages, tools):
        return {
            "is_error": True,
            "is_final": True,
            "text": "LLM call failed: 422",
            "tool_calls": [],
        }

    def schemas(self):
        return []


def test_llm_error_returns_failed():
    """Bug 2: an is_error LLM response must produce status=failed, not succeeded."""
    task = _make_task()
    result = asyncio.run(run_agent(task, FakeSandbox(), _ErrorLLM()))

    assert result["status"] == "failed", (
        f"Expected status='failed', got '{result['status']}'"
    )
    assert "LLM call failed" in result["output"], (
        f"Expected 'LLM call failed' in output, got: {result['output']!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: Tool output is truncated in history before next LLM call (Bug 1)
# ---------------------------------------------------------------------------

class _TruncationCaptureLLM:
    """
    Call 1: returns a shell tool call.
    Call 2: returns is_final=True with text "report".
    Records all messages passed to complete() for later inspection.
    """

    def __init__(self):
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append(list(messages))  # snapshot
        call_num = len(self.calls)
        if call_num == 1:
            return {
                "is_final": False,
                "is_error": False,
                "text": "",
                "tool_calls": [{"name": "shell", "arguments": {"command": "ls /workspace"}}],
            }
        return {
            "is_final": True,
            "is_error": False,
            "text": "report",
            "tool_calls": [],
        }


def test_tool_output_truncated_in_history():
    """Bug 1: tool output >4000 chars must be truncated before being added to history."""
    huge_stdout = "x" * 10_000
    sandbox = FakeSandbox(exec_stdout=huge_stdout)
    llm = _TruncationCaptureLLM()
    task = _make_task()

    result = asyncio.run(run_agent(task, sandbox, llm))

    # The agent should reach the second LLM call and succeed.
    assert len(llm.calls) == 2, f"Expected 2 LLM calls, got {len(llm.calls)}"
    assert result["status"] == "succeeded"

    # Inspect messages passed to the second complete() call.
    second_call_messages = llm.calls[1]
    # Find the user message that contains the shell tool result (role changed to
    # "user" so the model treats it as an environment observation, not its own output).
    shell_messages = [
        m for m in second_call_messages
        if m.get("role") == "user" and "Tool result for shell:" in m.get("content", "")
    ]
    assert shell_messages, "Expected a 'Tool result for shell:' user message in second call"

    tool_content = shell_messages[0]["content"]
    # The raw output was 10,000 chars; after truncation it must fit within
    # 4000 content chars + a short "[...truncated" suffix — well under 4200.
    assert len(tool_content) <= 4200, (
        f"Tool message in history is {len(tool_content)} chars; expected ≤ 4200 "
        f"(4000 cap + truncation suffix)."
    )
    assert "[...truncated" in tool_content, (
        "Expected '[...truncated' marker in tool history entry"
    )


# ---------------------------------------------------------------------------
# Test 3: iteration increments BEFORE tools run (Bug 3)
# ---------------------------------------------------------------------------

class _IterationCheckLLM:
    """
    Call 1: returns a shell tool call.
    Call 2: returns is_final=True with text "done".
    """

    def complete(self, messages, tools):
        call_num = getattr(self, "_call_count", 0) + 1
        self._call_count = call_num
        if call_num == 1:
            return {
                "is_final": False,
                "is_error": False,
                "text": "",
                "tool_calls": [{"name": "shell", "arguments": {"command": "ls /workspace"}}],
            }
        return {
            "is_final": True,
            "is_error": False,
            "text": "done",
            "tool_calls": [],
        }


def test_iteration_increments_before_tools_run():
    """Bug 3: task['iteration'] must be 1 by the time the sandbox executes."""
    task = _make_task()
    iteration_at_exec_time = []

    class _CapturingSandbox(FakeSandbox):
        def exec(self, cmd, timeout=60):
            iteration_at_exec_time.append(task["iteration"])
            return super().exec(cmd, timeout)

    result = asyncio.run(run_agent(task, _CapturingSandbox(), _IterationCheckLLM()))

    assert result["status"] == "succeeded", f"Unexpected status: {result['status']}"
    assert iteration_at_exec_time, "sandbox.exec was never called"
    assert iteration_at_exec_time[0] == 1, (
        f"Expected iteration=1 when exec ran, got {iteration_at_exec_time[0]}. "
        "iteration must be updated BEFORE tools are executed."
    )


# ---------------------------------------------------------------------------
# Test 4: thought and plan are populated on _update_progress (Bug 3)
# ---------------------------------------------------------------------------

class _ThoughtCaptureLLM:
    """
    Call 1: returns a shell tool call.
    Call 2: returns is_final=True with text "done".
    Captures the task state just before exec so we can verify thought was set.
    """

    def __init__(self, task_ref):
        self._task = task_ref
        self._call_count = 0

    def complete(self, messages, tools):
        self._call_count += 1
        if self._call_count == 1:
            return {
                "is_final": False,
                "is_error": False,
                "text": "",
                "tool_calls": [{"name": "shell", "arguments": {"command": "ls /workspace"}}],
            }
        return {
            "is_final": True,
            "is_error": False,
            "text": "done",
            "tool_calls": [],
        }


def test_thought_and_plan_are_set():
    """Bug 3: thought must contain 'Iteration 1' and plan must be 'Step 1 of max 50'
    after the first tool-calling iteration."""
    task = _make_task()
    thought_at_exec = []
    plan_at_exec = []

    class _ObservingSandbox(FakeSandbox):
        def exec(self, cmd, timeout=60):
            thought_at_exec.append(task.get("thought"))
            plan_at_exec.append(task.get("plan"))
            return super().exec(cmd, timeout)

    llm = _ThoughtCaptureLLM(task)
    result = asyncio.run(run_agent(task, _ObservingSandbox(), llm))

    assert result["status"] == "succeeded"

    # thought should have been set before exec ran
    assert thought_at_exec, "sandbox.exec was never called"
    first_thought = thought_at_exec[0]
    assert first_thought is not None, "task['thought'] was None when exec ran"
    assert "Iteration 1" in first_thought, (
        f"Expected 'Iteration 1' in thought, got: {first_thought!r}"
    )

    # After the final iteration the plan must reflect step 2 (the finishing step)
    final_plan = task.get("plan")
    assert final_plan is not None, "task['plan'] was never set"
    assert "Step 2 of max 50" == final_plan, (
        f"Expected plan='Step 2 of max 50', got: {final_plan!r}"
    )


# ---------------------------------------------------------------------------
# Test 5: _trim_history keeps first 2 + most recent N (Bug 1)
# ---------------------------------------------------------------------------

def test_history_trimmed_before_llm_call():
    """Bug 1: _trim_history must enforce the max_messages bound correctly."""

    # Case A: list longer than max_messages — keep first 2 + last 18 = 20
    long_history = list(range(25))
    trimmed = _trim_history(long_history, max_messages=20)
    assert len(trimmed) == 20, (
        f"Expected 20 items, got {len(trimmed)}"
    )
    # First two items preserved
    assert trimmed[0] == 0
    assert trimmed[1] == 1
    # Tail: items 7..24 (last 18 of indices 2..24)
    assert trimmed[2] == 7, (
        f"Expected first tail item to be 7 (index 25-18=7), got {trimmed[2]}"
    )
    assert trimmed[-1] == 24

    # Case B: list shorter than or equal to max_messages — returned unchanged
    short_history = list(range(10))
    result = _trim_history(short_history, max_messages=20)
    assert result == short_history, (
        f"Short history should be returned unchanged, got {result}"
    )
    assert len(result) == 10

    # Case C: length is always <= max_messages regardless of input size
    for n in (0, 1, 2, 19, 20, 21, 100):
        h = list(range(n))
        out = _trim_history(h, max_messages=20)
        assert len(out) <= 20, (
            f"_trim_history({n} items) returned {len(out)} items, expected ≤ 20"
        )


# ---------------------------------------------------------------------------
# Test 6: guard_budget raises BudgetExceeded after time limit
# ---------------------------------------------------------------------------

def test_guard_budget_raises_when_exceeded():
    """guard_budget must raise BudgetExceeded when elapsed > TASK_TIME_LIMIT_SECONDS."""
    task = _make_task()
    # Simulate a start time far in the past.
    past = time.monotonic() - (TASK_TIME_LIMIT_SECONDS + 1)
    try:
        guard_budget(task, past)
        assert False, "Expected BudgetExceeded to be raised"
    except BudgetExceeded:
        pass


def test_guard_budget_does_not_raise_within_limit():
    """guard_budget must not raise when the loop just started."""
    task = _make_task()
    now = time.monotonic()
    guard_budget(task, now)  # should not raise


# ---------------------------------------------------------------------------
# Test 7: ShellTool.check allow-list
# ---------------------------------------------------------------------------

def test_shell_check_allows_rg():
    assert ShellTool.check("rg -n 'TODO|FIXME' /workspace/repo") is None


def test_shell_check_allows_git_log():
    assert ShellTool.check("git -C /workspace/repo log --oneline -5") is None


def test_shell_check_allows_git_show():
    assert ShellTool.check("git -C /workspace/repo show --stat HEAD") is None


def test_shell_check_rejects_git_push():
    reason = ShellTool.check("git push origin master")
    assert reason is not None
    assert "not supported" in reason.lower()


def test_shell_check_rejects_pip_install():
    reason = ShellTool.check("pip install requests")
    assert reason is not None


def test_shell_check_rejects_curl():
    reason = ShellTool.check("curl https://example.com")
    assert reason is not None


def test_shell_check_rejects_unknown_head():
    reason = ShellTool.check("python3 script.py")
    assert reason is not None
    assert "allow-list" in reason


def test_shell_check_allows_quoted_pipe_in_regex():
    # '|' inside a quoted rg pattern must NOT be treated as a pipe operator.
    assert ShellTool.check("rg 'TODO|FIXME' /workspace/repo") is None


def test_shell_check_rejects_git_unknown_subcommand():
    reason = ShellTool.check("git -C /workspace/repo clone https://x.com")
    assert reason is not None
    assert "clone" in reason
