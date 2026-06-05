# CloudAgent

Autonomous agent platform — **8h MVP** (four pillars, curl demo). See `_requirements.txt`. Binding spec: `.claude/docs/` (PM creates when missing).

**Runnable code:** `demo/` (app, agent, frontend, `Dockerfile`, `scripts/demo.sh`). Build sandbox image from `demo/`.

## How to work here

**Main agent:** `agent-organizer` — start every session as organizer. It spawns `product-manager` first if `.claude/docs/MVP.md` or `SPECS.md` is missing, then delegates implementation.

Specs and read/write rules: [`.claude/docs/README.md`](.claude/docs/README.md). LLM default: [`.claude/docs/REFERENCES.md`](.claude/docs/REFERENCES.md) → `learn-agent/learn_LangChain/start.py` (Together + Qwen).

## Kickoff

```
/cloudagent-kickoff
```

Or delegate to subagent: `Use agent-organizer for CloudAgent minimal demo.`

## Also in `.claude/`

| Folder | Purpose |
|--------|---------|
| `skills/` | `/cloudagent-kickoff`, `/spawn-pm` |
| `rules/` | Team workflow + path-scoped coding rules |
| `settings.json` | Shared permissions (commit). Use `settings.local.json` for personal overrides (gitignored). |

## Agents

- **Main:** `agent-organizer` (you start here)
- **Spawned by organizer (iterative):** `product-manager` → then `llm-architect`, `backend-developer`, `frontend-developer`, `qa-expert` as needed — agent loop first per requirements

Definitions: `.claude/agents/`
