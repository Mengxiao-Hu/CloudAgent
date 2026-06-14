"""Agent middleware: reusable hooks and transforms for the agent loop.

Two flavours:
  - BaseCallbackHandler subclasses  → side-effect hooks (budget guard)
  - RunnableLambda wrappers          → data transforms (history trim, output cap)

Usage in runner.py:
    budget_guard = BudgetGuardMiddleware(start_monotonic)
    trimmed      = TrimHistoryMiddleware.invoke(history)
    capped       = CapOutputMiddleware.invoke(raw_output)
    response     = llm.complete(trimmed, schemas, extra_callbacks=[budget_guard])
"""

from __future__ import annotations

import time

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableLambda

TASK_TIME_LIMIT_SECONDS = 10 * 60
MAX_MESSAGES = 20
MAX_TOOL_OUTPUT_CHARS = 4_000


class BudgetExceeded(Exception):
    """Raised when the agent loop exceeds its wall-clock time limit."""


class BudgetGuardMiddleware(BaseCallbackHandler):
    """LangChain callback that raises BudgetExceeded before the LLM is called.

    Registered via RunnableConfig(callbacks=[...]) in llm.complete(), so it
    fires on every LLM invocation without modifying the agent loop directly.
    """

    def __init__(self, start_monotonic: float, limit: float = TASK_TIME_LIMIT_SECONDS):
        super().__init__()
        self._start = start_monotonic
        self._limit = limit

    def _check(self) -> None:
        elapsed = time.monotonic() - self._start
        if elapsed > self._limit:
            raise BudgetExceeded(
                f"Agent loop exceeded time limit ({self._limit:.0f}s)."
            )

    def on_llm_start(self, serialized, prompts, **kwargs) -> None:
        self._check()

    def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        self._check()


# ---------------------------------------------------------------------------
# Data-transform middleware (RunnableLambda)
# ---------------------------------------------------------------------------

def _trim_history(messages: list, max_messages: int = MAX_MESSAGES) -> list:
    """Keep the first two messages (system + user prompt) and the most recent
    (max_messages - 2) messages, bounding context size."""
    if len(messages) <= max_messages:
        return messages
    head = messages[:2]
    tail = messages[2:][-(max_messages - 2):]
    return head + tail


def _cap_output(output: str, max_chars: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    """Truncate output to max_chars, appending a marker if truncated."""
    if len(output) > max_chars:
        return output[:max_chars] + f"\n[...truncated, {len(output)} chars total]"
    return output


TrimHistoryMiddleware = RunnableLambda(_trim_history)
CapOutputMiddleware = RunnableLambda(_cap_output)
