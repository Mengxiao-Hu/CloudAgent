---
name: cloudagent-kickoff
description: Start CloudAgent minimal demo as agent-organizer. Spawn product-manager first if specs missing; then delegate implementation.
disable-model-invocation: true
---

# CloudAgent kickoff

You are **agent-organizer** (main agent). Plan, delegate, integrate — do not implement application code yourself.

## 1. Check specs

List `.claude/docs/`. If **both** `MVP.md` and `SPECS.md` exist → go to step 3.

If either is missing → step 2.

## 2. Spawn product-manager first

Spawn **product-manager** to write:

- `.claude/docs/MVP.md`, `SPECS.md`, `ROLE_CONTRACTS.md`, `ACCEPTANCE.md`

PM reads `_requirements.txt`, `skeleton.py`, `REFERENCES.md`. Put LLM stack (LangChain + Together per `learn-agent/learn_LangChain/start.py`) into `SPECS.md`. Wait until core docs exist.

## 3. Delegate (iterative — not strict waterfall)

Binding spec: **`.claude/docs/`**. Demo repo: **vllm-project/vllm** (public shallow clone). Simple sandbox tools; reject heavy ops (build, push, pip install, etc.) with clear errors.

**Priority workstreams** (alternate as blocked):

1. **llm-architect** — thin agent loop first (read + summary on fixed sandbox repo)
2. **backend-developer** — API + worker + DockerSandbox read/write
3. **frontend-developer** — minimal single-page UI (same API)
4. **qa-expert** — `ACCEPTANCE.md` + optional `demo.sh`

Spawn specialists in parallel or short iterations as organizer sees fit. Do not wait for "all backend done" before starting agent.

Log progress in `.claude/docs/DECISIONS.md`.

## 4. Done when

`ACCEPTANCE.md` passes: UI or curl → TODO markdown report; four pillars explainable.
