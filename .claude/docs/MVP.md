# MVP Scope — CloudAgent 8-Hour Demo

**Objective:** Demonstrate four architectural pillars through a functional end-to-end agent system that analyzes a public GitHub repository.

**Target Duration:** 8 hours (iterative, not waterfall)

## Scope: IN

### Core Pillars (all required)

1. **Agent Orchestration & Scheduling**
   - REST API: `POST /tasks` (submit prompt), `GET /tasks/{id}` (poll status)
   - In-memory task queue + single worker
   - Task states: `queued` → `running` → `succeeded` | `failed`
   - No persistence layer; memory-only is acceptable for demo

2. **Sandbox & Isolated Execution**
   - Docker-based sandbox (`DockerSandbox` class)
   - Shallow clone of `https://github.com/vllm-project/vllm` into `/workspace/repo` at task start
   - Execute read/write operations **inside container**, not on worker host
   - Cleanup: destroy container after task completion

3. **LLM Integration & Tool Calling**
   - LangChain wrapper around Together AI API (Qwen2.5-7B-Instruct-Turbo)
   - Agent loop: observe → think → act → iterate
   - Four simple tools: **read**, **write**, **shell**, **finish**
   - Rejection logic: Clear error messages for unsupported operations (pip install, git push, private repos)

4. **Extensible Architecture**
   - Three Protocols: `LLMProvider`, `Tool`, `Sandbox`
   - One implementation per protocol
   - No rigid alignment to skeleton.py; simplify where helpful

### Demonstration Scenario

- **Default task prompt:** "Clone completed. Find all TODO/FIXME in `/workspace/repo`. Summarize findings in markdown."
- **Analysis method:** Use `shell` tool for `rg 'TODO|FIXME'` or `grep -r`, then `read` relevant snippets
- **Output:** Markdown report written to `/workspace/out/report.md`
- **No user login, no GitHub write access, no dependency installation**

### UI & Submission

- **Minimal frontend** (recommended P0): Single HTML page or minimal React
  - Input: task prompt text
  - Submit button → POST /tasks
  - Polling display of task status
  - Markdown result display when complete
- **OR curl alternative:** `scripts/demo.sh` demonstrates same API flow
- **No authentication, no design system**

## Scope: OUT (P1 / Post-MVP)

- Multi-worker setup, Redis/SQLite, multi-tenant
- Policy engine, LangSmith instrumentation
- Firecracker, K8s, seccomp tuning
- User-selectable repo URLs, private repos, push/PR capability
- In-sandbox `pip install` and full vllm build
- GitHub token management
- Plan persistence & recovery across container restarts
- Advanced agent features (artifact editing, sub-planning, feedback loops beyond basic tool error handling)

## Implementation Approach (Iterative Priority)

| Priority | Phase | Focus |
|----------|-------|-------|
| 1 | **Agent thin loop** | Clone + `rg` + read + finish → reject heavy ops |
| 2 | **API + worker** | POST/GET → enqueue → async agent execution |
| 3 | **Docker isolation** | Real read/write in container, destroy after |
| 4 | **Minimal UI** | Text input → submit → poll → display markdown |
| 5 | **Polish & demo** | Prompt tuning, error messages, `demo.sh`, README |

**Principle:** Do agent behavior first (spend most time here); keep orchestration & frontend thin.

## Success Criteria (Definition of Done)

### Functional
- [x] Agent accepts task prompt via API
- [x] Agent executes in Docker sandbox (real isolation)
- [x] LLM makes tool calls; tools execute in sandbox
- [x] Loop iterates until agent calls `finish`
- [x] Rejects unsupported operations (pip, push, private repos) with clear message
- [x] Produces markdown report for vllm TODO/FIXME analysis

### Architectural
- [x] `LLMProvider` + `Tool` + `Sandbox` protocols defined and implemented
- [x] Tool calls routed through single interface
- [x] LLM API keys on worker only (not in container)
- [x] Sandbox destroy cleans up container

### Demonstration
- [x] Curl script (`scripts/demo.sh`) or frontend can submit and retrieve result
- [x] Task moves through states visibly
- [x] Final markdown report displays in terminal or browser
- [x] Can point to code for each of four pillars

## Non-Goals

- Beautification or UX polish beyond "functional"
- Persistence of tasks beyond process lifetime
- Multi-language or plugin architecture
- Real-time streaming output
- Production-grade logging/monitoring
- Full vllm test suite or build inside sandbox
