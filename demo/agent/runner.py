"""Agent core loop: observe -> think -> act.

Per SPECS.md § 2.1. run_agent drives the conversation between the LLM provider
and the tool registry, executing tool calls inside the injected sandbox.

Ownership note (ROLE_CONTRACTS.md): this module owns the loop only. The Sandbox
(Docker), the Task model, the worker queue, and API routes belong to
backend-developer. We therefore treat `task` and `sandbox` as injected objects
with a minimal duck-typed interface.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from .prompts import system_prompt
from .tools import ToolRegistry

MAX_ITERATIONS = 50
TASK_TIME_LIMIT_SECONDS = 10 * 60  # 10 minutes for the agent loop (excludes clone time)
MAX_TOOL_OUTPUT_CHARS = 4000  # cap tool output appended to history (Bug 1)


class BudgetExceeded(Exception):
    """Raised by guard_budget when the task exceeds its time limit."""


def _task_prompt(task) -> str:
    if hasattr(task, "prompt"):
        return task.prompt
    if isinstance(task, dict):
        return task.get("prompt", "")
    return str(task)


def _task_started_at(task) -> float | None:
    """Best-effort epoch seconds for when the task started."""
    started = getattr(task, "started_at", None)
    if started is None and isinstance(task, dict):
        started = task.get("started_at")
    if started is None:
        return None
    if isinstance(started, datetime):
        return started.timestamp()
    if isinstance(started, (int, float)):
        return float(started)
    return None


def guard_budget(task, start_monotonic: float) -> None:
    """Raise BudgetExceeded if the agent loop has run past its time limit.

    Always uses start_monotonic (set when run_agent is called, after git clone)
    so clone time doesn't eat into the agent's budget.
    """
    elapsed = time.monotonic() - start_monotonic
    if elapsed > TASK_TIME_LIMIT_SECONDS:
        raise BudgetExceeded(
            f"Agent loop exceeded time limit ({TASK_TIME_LIMIT_SECONDS}s)."
        )


def _trim_history(history: list[dict], max_messages: int = 20) -> list[dict]:
    """Keep the first two messages (system + original prompt) and the most
    recent max_messages - 2 messages, to bound context size (Bug 1)."""
    if len(history) <= max_messages:
        return history
    head = history[:2]
    tail = history[2:][-(max_messages - 2):]
    return head + tail


def _update_progress(task, iteration: int, thought=None, plan=None) -> None:
    try:
        task.iteration = iteration
        task.last_activity = datetime.now()
    except (AttributeError, TypeError):
        # Fakes / dicts may not support attribute assignment; non-fatal.
        if isinstance(task, dict):
            task["iteration"] = iteration
    try:
        task.thought = thought
        task.plan = plan
    except (AttributeError, TypeError):
        if isinstance(task, dict):
            task["thought"] = thought
            task["plan"] = plan


async def run_agent(task, sandbox, llm, tool_registry: ToolRegistry | None = None) -> dict:
    """Run the agent loop to completion.

    Args:
        task: object/dict exposing a `prompt` (and optionally started_at/iteration).
        sandbox: injected Sandbox (exec/read/write).
        llm: LLMProvider with complete(messages, tools) -> dict.
        tool_registry: optional override; defaults to the four standard tools.

    Returns:
        {"status": "succeeded"|"failed", "output": str}
    """
    if tool_registry is None:
        tool_registry = ToolRegistry()

    start_monotonic = time.monotonic()
    history: list[dict] = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": _task_prompt(task)},
    ]

    for iteration in range(MAX_ITERATIONS):
        # --- budget guard -------------------------------------------------- #
        try:
            guard_budget(task, start_monotonic)
        except BudgetExceeded as exc:
            return {"status": "failed", "output": str(exc)}

        # --- think --------------------------------------------------------- #
        history = _trim_history(history)
        response = llm.complete(history, tool_registry.schemas())

        # An LLM-level error must fail the task, not masquerade as success.
        if response.get("is_error"):
            return {"status": "failed", "output": response.get("text", "LLM call failed")}

        # A response with no tool calls is treated as final text.
        tool_calls = response.get("tool_calls") or []
        plan = f"Step {iteration + 1} of max {MAX_ITERATIONS}"
        if response.get("is_final") and not tool_calls:
            thought = response.get("text", "")[:200]
            _update_progress(task, iteration + 1, thought=thought, plan=plan)
            return {"status": "succeeded", "output": response.get("text", "")}

        if not tool_calls:
            # Defensive: model returned nothing actionable. Nudge and continue.
            history.append(
                {
                    "role": "user",
                    "content": "No tool call detected. Use a tool, or call "
                    "finish(output=...) with your final report.",
                }
            )
            _update_progress(task, iteration + 1, plan=plan)
            continue

        # Iteration advances as soon as the LLM decides what to do, so the
        # user sees progress even during a long-running tool call (Bug 4).
        thought = (
            f"Iteration {iteration + 1}: calling "
            f"{', '.join(tc['name'] for tc in tool_calls)}"
        )
        _update_progress(task, iteration + 1, thought=thought, plan=plan)

        # --- act ----------------------------------------------------------- #
        tool_results = []
        for tool_call in tool_calls:
            name = tool_call.get("name", "")
            args = tool_call.get("arguments", {}) or {}

            if not tool_registry.is_allowed(name):
                result = {
                    "success": False,
                    "output": "",
                    "error": f"Tool '{name}' not available in this context.",
                }
            else:
                tool = tool_registry.get(name)
                try:
                    result = tool.run(args, sandbox)
                except Exception as exc:
                    result = {
                        "success": False,
                        "output": "",
                        "error": f"Tool '{name}' raised: {exc}",
                    }

            # finish short-circuits the whole loop.
            if result.get("is_final"):
                return {"status": "succeeded", "output": result.get("output", "")}

            tool_results.append({"tool": name, "input": args, "result": result})

        # --- observe ------------------------------------------------------- #
        for tr in tool_results:
            # Cap tool output so a single huge result can't overflow the
            # context window on the next llm.complete() call (Bug 1).
            output = tr["result"].get("output")
            if isinstance(output, str) and len(output) > MAX_TOOL_OUTPUT_CHARS:
                total = len(output)
                tr["result"]["output"] = (
                    output[:MAX_TOOL_OUTPUT_CHARS]
                    + f"\n[...truncated, {total} chars total]"
                )
            # Use "user" role for tool results so the model treats them as
            # environment observations rather than its own prior output.
            history.append(
                {
                    "role": "user",
                    "content": f"Tool result for {tr['tool']}: {json.dumps(tr['result'])}",
                }
            )

    return {"status": "failed", "output": "Max iterations reached."}
