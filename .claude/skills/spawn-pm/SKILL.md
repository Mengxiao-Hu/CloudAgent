---
name: spawn-pm
description: Organizer action — spawn product-manager to generate .claude/docs specs from _requirements.txt and skeleton.py when MVP.md or SPECS.md is missing.
disable-model-invocation: true
---

# Spawn product-manager

As **agent-organizer**, spawn **product-manager** now to create specs.

**PM reads:** `_requirements.txt`, `skeleton.py`, `CLAUDE.md`, `.claude/docs/README.md`, `.claude/docs/REFERENCES.md`

Include from `_requirements.txt`: **8h P0**, **demo repo vllm**, **simple tools + reject policy** (not fixed 3 tools), **minimal frontend**, iterative build. Document clone depth, rg-first analysis, reject list in `SPECS.md`.

**PM writes under `.claude/docs/`:**
- `MVP.md`
- `SPECS.md`
- `ROLE_CONTRACTS.md`
- `ACCEPTANCE.md`

Use `skeleton.py` as reference — simplify for minimal demo where needed. No application code.

When PM finishes, continue orchestration (delegate backend → llm → frontend → qa per `ROLE_CONTRACTS.md`).
