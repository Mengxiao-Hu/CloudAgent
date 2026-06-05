from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Task:
    id: str
    prompt: str
    status: str  # "queued" | "running" | "succeeded" | "failed"
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: str | None = None
    iteration: int = 0
    error: str | None = None
    thought: str | None = None   # current LLM reasoning (set by runner each iteration)
    plan: str | None = None       # current step description (set by runner each iteration)
