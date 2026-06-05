from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import store
from app.models import Task
from app.sandbox import DockerSandbox
from app.worker import worker_loop

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="CloudAgent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Pydantic request/response schemas
# ---------------------------------------------------------------------------


class TaskRequest(BaseModel):
    prompt: str


class TaskResponse(BaseModel):
    id: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: str | None = None
    iteration: int | None = None
    error: str | None = None
    thought: str | None = None
    plan: str | None = None

    class Config:
        # Exclude None values from serialised output
        # (handled manually in the endpoint for fine-grained control)
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _task_to_dict(task: Task) -> dict[str, Any]:
    """Serialise a Task to a dict, omitting fields that are None."""
    raw = {
        "id": task.id,
        "status": task.status,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "result": task.result,
        "iteration": task.iteration,
        "error": task.error,
        "thought": task.thought,
        "plan": task.plan,
    }
    return {k: v for k, v in raw.items() if v is not None}


# ---------------------------------------------------------------------------
# API routes — prefix /api
# ---------------------------------------------------------------------------


@app.post("/api/tasks", status_code=202)
def create_task(body: TaskRequest) -> dict[str, Any]:
    """
    Submit a new agent task.

    Returns 202 Accepted with the task id, status, and created_at timestamp.
    The task is queued for processing by the background worker.
    """
    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        prompt=body.prompt,
        status="queued",
        created_at=_utcnow(),
    )
    store.tasks[task_id] = task
    store.enqueue(task_id)
    logger.info("Task %s queued", task_id)
    return {
        "id": task.id,
        "status": task.status,
        "created_at": task.created_at,
    }


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    """
    Retrieve the current state of a task.

    None fields are omitted from the response so the client can reliably
    use key presence to determine task phase.
    """
    task = store.tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return _task_to_dict(task)


# ---------------------------------------------------------------------------
# Frontend — serve index.html at root
# ---------------------------------------------------------------------------

_FRONTEND_PATH = Path(__file__).parent.parent / "frontend" / "index.html"


@app.get("/", include_in_schema=False)
def serve_frontend() -> FileResponse:
    if not _FRONTEND_PATH.exists():
        raise HTTPException(status_code=404, detail="Frontend not built")
    return FileResponse(str(_FRONTEND_PATH), media_type="text/html")


# ---------------------------------------------------------------------------
# Startup: launch background worker thread
# ---------------------------------------------------------------------------


def _build_llm():
    """
    Construct the LangChainProvider.

    Imported lazily so the app starts even when agent/ is not present yet
    (e.g., during early development of just the API layer).
    """
    api_key = os.environ.get("TOGETHER_API_KEY", "")
    if not api_key:
        logger.warning("TOGETHER_API_KEY is not set — agent calls will fail")
    try:
        from agent.llm import LangChainProvider  # noqa: PLC0415
        return LangChainProvider(api_key=api_key)
    except ImportError:
        logger.error("agent.llm not found — worker will run without a real LLM")
        return None


@app.on_event("startup")
def startup_event() -> None:
    llm = _build_llm()
    thread = threading.Thread(
        target=worker_loop,
        args=(store, DockerSandbox, llm),
        name="cloudagent-worker",
        daemon=True,
    )
    thread.start()
    logger.info("Background worker thread started")
