from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Callable

from app import store
from app.sandbox import DockerSandbox

logger = logging.getLogger(__name__)

_TASK_TIMEOUT_SECONDS = 660  # 11 minutes: up to 3 min clone + 8 min agent loop


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def worker_loop(
    queue,  # module reference; we call queue.dequeue()
    sandbox_factory,  # class with .create(task) -> sandbox
    llm,  # LLMProvider passed to run_agent
) -> None:
    """
    Main background worker.  Runs in a dedicated daemon thread.

    Continuously dequeues task IDs, executes each task inside an
    ephemeral DockerSandbox, and updates the in-memory task state.

    The worker imports ``run_agent`` lazily so that the agent module can
    be absent during unit-testing of the worker itself.
    """
    # Lazy import — agent/runner.py is owned by llm-architect.
    # We import here (not at module level) so the worker module remains
    # importable even when the agent package has not been written yet.
    try:
        from agent.runner import run_agent  # noqa: PLC0415
    except ImportError:
        logger.error(
            "agent.runner not found — worker will mark all tasks as failed "
            "until llm-architect delivers agent/runner.py"
        )
        run_agent = None  # type: ignore[assignment]

    logger.info("Worker loop started (thread=%s)", threading.current_thread().name)

    while True:
        task_id = queue.dequeue(timeout=1)
        if task_id is None:
            continue

        task = store.tasks.get(task_id)
        if task is None:
            logger.warning("Dequeued unknown task_id=%s — skipping", task_id)
            continue

        task.status = "running"
        task.started_at = _utcnow()
        task.thought = "Initializing sandbox..."
        logger.info("Task %s started", task_id)

        sandbox = None
        try:
            # ----------------------------------------------------------
            # Create sandbox
            # ----------------------------------------------------------
            sandbox = sandbox_factory.create(task)

            # ----------------------------------------------------------
            # Initialise workspace
            # ----------------------------------------------------------
            task.thought = "Cloning vllm repository (this may take 1-2 minutes)..."
            clone_result = sandbox.exec(
                "git clone --depth 1 https://github.com/vllm-project/vllm /workspace/repo",
                timeout=120,
            )
            if clone_result["returncode"] != 0:
                logger.warning(
                    "git clone exited %d: %s",
                    clone_result["returncode"],
                    clone_result["stdout"],
                )

            sandbox.exec("mkdir -p /workspace/out", timeout=10)
            task.thought = "Repository ready. Starting agent loop..."

            # ----------------------------------------------------------
            # Run agent (with per-task timeout)
            # ----------------------------------------------------------
            if run_agent is None:
                raise RuntimeError("agent.runner.run_agent is not available")

            result = _run_with_timeout(run_agent, task, sandbox, llm, timeout=_TASK_TIMEOUT_SECONDS)

            task.status = result.get("status", "succeeded")
            output = result.get("output", "")
            if task.status == "failed":
                # Route failure messages to task.error so the frontend shows them correctly.
                task.error = output
            else:
                task.result = output
            logger.info("Task %s completed with status=%s", task_id, task.status)

        except TimeoutError:
            task.status = "failed"
            task.error = "Task execution timeout (exceeded 11 minutes)"
            logger.error("Task %s timed out", task_id)
        except Exception as exc:  # noqa: BLE001
            task.status = "failed"
            task.error = str(exc)
            logger.exception("Task %s failed: %s", task_id, exc)
        finally:
            if sandbox is not None:
                sandbox.destroy()
            task.completed_at = _utcnow()


# ---------------------------------------------------------------------------
# Timeout helper
# ---------------------------------------------------------------------------

def _run_with_timeout(run_agent, task, sandbox, llm, timeout: int) -> dict:
    """
    Execute ``run_agent(task, sandbox, llm)`` with a hard wall-clock timeout.

    ``run_agent`` may be a coroutine function (async def).  We detect that
    and run it in a fresh event loop on a secondary thread so we can apply
    a threading-level timeout regardless.
    """
    result_holder: list[dict] = []
    exc_holder: list[Exception] = []

    def _target():
        try:
            if asyncio.iscoroutinefunction(run_agent):
                loop = asyncio.new_event_loop()
                try:
                    res = loop.run_until_complete(
                        asyncio.wait_for(
                            run_agent(task, sandbox, llm),
                            timeout=timeout,
                        )
                    )
                finally:
                    loop.close()
            else:
                res = run_agent(task, sandbox, llm)
            result_holder.append(res)
        except asyncio.TimeoutError:
            exc_holder.append(TimeoutError("asyncio timeout"))
        except Exception as exc:  # noqa: BLE001
            exc_holder.append(exc)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        # Thread is still running; we cannot kill it but we raise TimeoutError
        # so the caller marks the task as failed and moves on.
        raise TimeoutError(f"run_agent exceeded {timeout}s wall-clock limit")

    if exc_holder:
        raise exc_holder[0]

    return result_holder[0] if result_holder else {"status": "failed", "output": "No result returned"}
