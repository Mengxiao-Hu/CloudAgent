---
paths:
  - "demo/app/**"
  - "demo/run.py"
  - "demo/requirements.txt"
  - "demo/Dockerfile"
---

# Backend (orchestration + sandbox)

Ownership: **backend-developer** per `.claude/docs/ROLE_CONTRACTS.md`.

- Python 3.11+, FastAPI, async where appropriate
- Sandbox per `SPECS.md` — `exec`/`read`/`write`; shallow `git clone` vllm into `/workspace/repo`
- **Do not** implement `run_agent()`, LLM clients, or tool registry here
- Expose stable sandbox interface for llm-architect (document in `SPECS.md` if changed)
