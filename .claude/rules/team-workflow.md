# CloudAgent team workflow

Loaded every session. Spec matrix: `.claude/docs/README.md`.

## Roles

- **agent-organizer** — main entry; delegates; writes `DECISIONS.md` only under `.claude/docs/`
- **product-manager** — only role that reads `_requirements.txt`; reads `skeleton.py` to inform specs (may simplify for MVP)
- **Implementation agents** — **binding spec:** `.claude/docs/`; may **refer to** `skeleton.py` for ideas, not required to match it line-for-line

## Code principles (minimal demo)

- Prefer contracts in `.claude/docs/SPECS.md`. `skeleton.py` is a reference sketch — adapt when simpler
- **Demo repo:** public https://github.com/vllm-project/vllm (shallow clone in sandbox)
- **Demo agent:** simple tools (read, write, shell for rg/grep); **reject** heavy/unsafe requests with clear errors
- read/write execute **inside** `Sandbox`, not on the worker host
- Build **iteratively** (agent loop ↔ API ↔ Docker ↔ UI), not a fixed hour-by-hour schedule
- LLM API keys stay in the worker process, not in the container
- Prefer small, reviewable diffs; match stack in `SPECS.md` once it exists
- Scope changes belong in `.claude/docs/` (PM or organizer), not ad-hoc expansion
