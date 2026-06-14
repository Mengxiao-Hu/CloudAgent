"""Agent core loop: observe -> think -> act.

Per SPECS.md § 2.1. run_agent drives the conversation between the LLM provider
and the tool registry, executing tool calls inside the injected sandbox.

Ownership note (ROLE_CONTRACTS.md): this module owns the loop only. The Sandbox
(Docker), the Task model, the worker queue, and API routes belong to
backend-developer. We therefore treat `task` and `sandbox` as injected objects
with a minimal duck-typed interface.

Middleware (budget guard, history trim, output cap) lives in middleware.py and
is composed into the loop via LangChain callbacks and RunnableLambda transforms.
"""

from __future__ import annotations

import json
import time

from .middleware import (
    BudgetExceeded,
    BudgetGuardMiddleware,
    CapOutputMiddleware,
    TrimHistoryMiddleware,
)
from .prompts import system_prompt
from .tools import ToolRegistry

MAX_ITERATIONS = 50


def _task_prompt(task) -> str:
    if hasattr(task, "prompt"):
        return task.prompt
    if isinstance(task, dict):
        return task.get("prompt", "")
    return str(task)


def _update_progress(task, iteration: int, thought=None, plan=None) -> None:
    if isinstance(task, dict):
        task["iteration"] = iteration
        task["thought"] = thought
        task["plan"] = plan
    else:
        task.iteration = iteration
        task.thought = thought
        task.plan = plan


async def run_agent(task, sandbox, llm, tool_registry: ToolRegistry | None = None) -> dict:
    """Run the agent loop to completion.

    Args:
        task: object/dict exposing a `prompt` (and optionally started_at/iteration).
        sandbox: injected Sandbox (exec/read/write).
        llm: LLMProvider with complete(messages, tools, extra_callbacks) -> dict.
        tool_registry: optional override; defaults to the four standard tools.

    Returns:
        {"status": "succeeded"|"failed", "output": str}
    """
    if tool_registry is None:
        tool_registry = ToolRegistry()

    start_monotonic = time.monotonic()
    budget_guard = BudgetGuardMiddleware(start_monotonic)

    history: list[dict] = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": _task_prompt(task)},
    ]

    for iteration in range(MAX_ITERATIONS):
        # --- think --------------------------------------------------------- #
        # TrimHistoryMiddleware limits what the LLM sees without discarding
        # history entries; CapOutput (observe phase) caps what enters history.
        trimmed = TrimHistoryMiddleware.invoke(history)
        try:
            response = llm.complete(
                trimmed, tool_registry.schemas(), extra_callbacks=[budget_guard]
            )
        except BudgetExceeded as exc:
            return {"status": "failed", "output": str(exc)}

        if response.get("is_error"):
            return {"status": "failed", "output": response.get("text", "LLM call failed")}

        tool_calls = response.get("tool_calls") or []
        plan = f"Step {iteration + 1} of max {MAX_ITERATIONS}"
        if response.get("is_final") and not tool_calls:
            thought = response.get("text", "")[:200]
            _update_progress(task, iteration + 1, thought=thought, plan=plan)
            return {"status": "succeeded", "output": response.get("text", "")}

        if not tool_calls:
            history.append(
                {
                    "role": "user",
                    "content": "No tool call detected. Use a tool, or call "
                    "finish(output=...) with your final report.",
                }
            )
            _update_progress(task, iteration + 1, plan=plan)
            continue

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

            if result.get("is_final"):
                return {"status": "succeeded", "output": result.get("output", "")}

            tool_results.append({"tool": name, "input": args, "result": result})

        # --- observe ------------------------------------------------------- #
        for tr in tool_results:
            output = tr["result"].get("output")
            if isinstance(output, str):
                # CapOutputMiddleware prevents context-window overflow on the
                # next llm.complete() call.
                tr["result"]["output"] = CapOutputMiddleware.invoke(output)
            history.append(
                {
                    "role": "user",
                    "content": f"Tool result for {tr['tool']}: {json.dumps(tr['result'])}",
                }
            )

    return {"status": "failed", "output": "Max iterations reached."}
