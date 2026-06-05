# Backend Implementation Notes

Agent: backend-developer
Date: 2026-06-04

## Files Delivered

All paths under `demo/`.

| File | Purpose |
|------|---------|
| `demo/app/__init__.py` | Package marker |
| `demo/app/models.py` | `Task` dataclass |
| `demo/app/store.py` | In-memory task dict + deque queue |
| `demo/app/sandbox.py` | `DockerSandbox` implementing Sandbox protocol |
| `demo/app/worker.py` | `worker_loop` background function |
| `demo/app/main.py` | FastAPI app, routes, startup hook |
| `demo/Dockerfile` | Sandbox image (cloudagent-sandbox:latest) |
| `demo/requirements.txt` | Python dependencies (unpinned) |
| `demo/run.py` | Uvicorn startup script |

## Implementation Choices and Deviations

### store.py — polling dequeue

SPECS.md § 3.4 shows `dequeue` returning `None` immediately on empty
queue, leaving the caller to sleep.  The implementation moves the
poll-sleep loop inside `dequeue(timeout=1)` so the worker thread does not
busy-spin.  The external contract is identical: returns `str | None`.

### sandbox.py — `nano_cpus` instead of `cpus`

The `docker` Python SDK (docker-py) does not accept the `cpus` keyword;
the correct parameter is `nano_cpus` (integer, 1 CPU = 1e9).  The spec
value of 1.0 CPU is preserved exactly.

### sandbox.py — container command

Spec § 4.2 shows `ENTRYPOINT ["/bin/bash"]` in the Dockerfile.  Running
the container with no extra command would exit immediately.  The sandbox
starts the container with `command="tail -f /dev/null"` so it stays alive
for `exec_run` calls.  This is consistent with docker-py best practice for
long-running sidecar containers.

### sandbox.exec / read — no `shell=` on `exec_run`

`docker-py` 7.x `exec_run` does not accept `shell=True` or `input=`.
Shell commands use `["/bin/sh", "-c", cmd]`; reads use `["cat", path]`;
writes use `put_archive` with a small tar stream.

### worker.py — async run_agent support

`run_agent` (owned by llm-architect) is specified as `async def` in
SPECS.md § 2.1.  The worker runs in a plain `threading.Thread`, so it
cannot `await` directly.  `_run_with_timeout` detects coroutine functions
and runs them in a fresh `asyncio` event loop on a sub-thread, applying
`asyncio.wait_for` for the 5-minute timeout.  Synchronous `run_agent`
implementations also work (no async overhead).

### worker.py — lazy import of agent.runner

`run_agent` is imported inside `worker_loop` (not at module top-level) so
`app.main` remains importable when `agent/` has not been written yet.
A clear `RuntimeError` is raised if the import fails at runtime.

### main.py — worker receives `store` module, not just queue

The SPECS.md sketch passes `queue` as the first arg.  Because the worker
also needs `store.tasks` (to look up Task objects), the `store` module
itself is passed.  `store.dequeue` is called inside the worker loop via
`queue.dequeue(timeout=1)`.  This matches the interface signature
`worker_loop(queue, sandbox_factory, llm)` — `queue` is now the `store`
module, which exposes both `dequeue()` and `tasks`.

### Dockerfile — CMD vs ENTRYPOINT

SPECS.md uses `ENTRYPOINT ["/bin/bash"]`; the Dockerfile uses
`CMD ["/bin/bash"]` so the sandbox overrides it with `tail -f /dev/null`.
Functionally equivalent for this use-case and avoids needing `--entrypoint`
in `docker run`.

## What Is NOT Implemented Here

- `run_agent()` — llm-architect owns `agent/runner.py`
- `LangChainProvider` — llm-architect owns `agent/llm.py`
- Tool definitions — llm-architect owns `agent/tools.py`
- Frontend HTML — frontend-developer owns `frontend/index.html`
