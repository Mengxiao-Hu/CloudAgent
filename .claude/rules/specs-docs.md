---
paths:
  - ".claude/docs/**"
---

# Editing project specs

You are working in `.claude/docs/`. See `README.md` for per-agent read/write permissions.

- **product-manager** creates: `MVP.md`, `SPECS.md`, `ROLE_CONTRACTS.md`, `ACCEPTANCE.md`
- **agent-organizer** writes: `DECISIONS.md` only
- **backend-developer** may write `BACKEND.md` and amend backend sections of `SPECS.md`
- **llm-architect** may write `AGENT_RUNTIME.md` and amend agent/tool sections of `SPECS.md`
- **frontend-developer** may write `FRONTEND.md`
- **qa-expert** may write `TESTING.md` and amend `ACCEPTANCE.md`

Keep `SPECS.md` internally consistent when amending. Specs should stand alone (no “see skeleton” as the only detail). If you diverge from `skeleton.py`, say so explicitly in `SPECS.md` or `MVP.md`.
