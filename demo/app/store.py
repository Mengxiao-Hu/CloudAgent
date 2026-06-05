from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Task

# Global in-memory task store: {task_id: Task}
tasks: dict[str, "Task"] = {}

# In-memory FIFO queue of task IDs
task_queue: deque[str] = deque()


def enqueue(task_id: str) -> None:
    """Append a task ID to the back of the queue."""
    task_queue.append(task_id)


def dequeue(timeout: float = 1) -> str | None:
    """
    Pop the next task ID from the front of the queue.

    If the queue is empty, poll up to *timeout* seconds (0.05 s intervals)
    before returning None.  A timeout of 0 makes a single non-blocking
    attempt.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            return task_queue.popleft()
        except IndexError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(0.05, remaining))
