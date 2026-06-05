# `.claude/docs/` — specification hub

Project specs for subagents. **Not** repo-root `docs/`.

**Upstream (outside this folder):**
- `_requirements.txt` — read only by **product-manager**
- `skeleton.py` — **reference architecture** (not strict). PM reads and translates into docs; other agents may read for context but **`.claude/docs/` wins** if anything conflicts

**Session workflow** (which agent to spawn): see project root `CLAUDE.md`.

---

## Per-file read / write

| File | product-manager | agent-organizer | backend-developer | llm-architect | frontend-developer | qa-expert |
|------|-----------------|-----------------|-------------------|---------------|--------------------|-----------|
| `MVP.md` | **W** | R | R | R | R | R |
| `SPECS.md` | **W** | R | R, **W** (backend/sandbox sections) | R, **W** (agent/tool sections) | R | R |
| `ROLE_CONTRACTS.md` | **W** | R | R | R | R | R |
| `ACCEPTANCE.md` | **W** | R | R | R | R | R, **W** |
| `BACKEND.md` | — | R | **W** | R | — | R |
| `AGENT_RUNTIME.md` | — | R | R | **W** | — | R |
| `FRONTEND.md` | — | R | — | — | **W** | R |
| `TESTING.md` | — | R | — | — | — | **W** |
| `DECISIONS.md` | — | **W** | R | R | R | R |
| `REFERENCES.md` | **W** | R | R | R | — | R |

**W** = create or update · **R** = read when relevant · **—** = not unless organizer requests

### Agent summary

| Agent | Reads | Writes here |
|-------|--------|-------------|
| product-manager | `_requirements.txt`, `skeleton.py`, `REFERENCES.md` | `MVP.md`, `SPECS.md`, `ROLE_CONTRACTS.md`, `ACCEPTANCE.md`, `REFERENCES.md` |
| agent-organizer | all files in this folder | `DECISIONS.md` only |
| backend-developer | this folder + optional `skeleton.py` | `BACKEND.md`; `SPECS.md` backend sections |
| llm-architect | this folder + optional `skeleton.py` | `AGENT_RUNTIME.md`; `SPECS.md` agent sections |
| frontend-developer | this folder | `FRONTEND.md` |
| qa-expert | this folder | `TESTING.md`; `ACCEPTANCE.md` |

Implementation agents: **do not** read `_requirements.txt`. May read `skeleton.py` as reference only; **follow `.claude/docs/`** for binding decisions. Deviations from skeleton → note in domain doc or `SPECS.md`. Large scope changes → organizer re-spawns product-manager.

---

## Core files (PM creates first)

| File | Purpose |
|------|---------|
| `MVP.md` | In/out of scope; IMPLEMENT / STUB / DEFER |
| `SPECS.md` | APIs, layout, protocols, demo repo + prompt |
| `ROLE_CONTRACTS.md` | Code ownership per subagent |
| `ACCEPTANCE.md` | Definition of done, curl/scripts |
| `REFERENCES.md` | LLM stack + optional external repos (seeded; PM may update) |

**Status:** `REFERENCES.md` seeded. **PM still needed** for `MVP.md`, `SPECS.md`, `ROLE_CONTRACTS.md`, `ACCEPTANCE.md` — run **agent-organizer** → spawn **product-manager**.
