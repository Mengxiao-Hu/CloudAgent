---
paths:
  - "demo/agent/**"
  - "src/llm/**"
  - "src/tools/**"
---

# Agent runtime (LLM loop + tools)

Ownership: **llm-architect** per `.claude/docs/ROLE_CONTRACTS.md`.

- Agent loop per `SPECS.md` — vllm repo; **read**, **write** (out dir), **shell** (analysis commands), **finish**
- Reject heavy/unsupported ops with explicit tool error messages
- **Do not** add FastAPI routes or Docker lifecycle code here
- System prompt and `MAX_ITERS` / budget guards per `MVP.md`
