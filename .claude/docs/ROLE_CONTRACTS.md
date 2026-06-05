# Role Contracts — Code Ownership & Responsibilities

## Binding Location

All specifications are binding in `.claude/docs/`. Implementation agents may consult `skeleton.py` for architectural ideas, but `.claude/docs/SPECS.md` and `MVP.md` are the source of truth. If a deviation is necessary, document it in this file or in the relevant domain spec (BACKEND.md, AGENT_RUNTIME.md, FRONTEND.md).

---

## llm-architect

### Responsible For

1. **Agent loop implementation** (`run_agent()` function)
   - Iterate over tool calls and LLM responses
   - Maintain conversation history
   - Implement iteration limits and timeout guards
   - Integrate LLM provider with tool registry

2. **LLM integration**
   - Wrap Together AI + Qwen via LangChain
   - Parse tool calls from LLM response
   - Format messages for OpenAI-compatible API
   - Handle tool binding and schema injection

3. **Tool implementations**
   - Define `Tool` protocol
   - Implement all four tools: ReadFile, WriteFile, Shell, Finish
   - Tool input validation and schema definition
   - Tool execution error handling within agent loop

4. **System prompt & prompt engineering**
   - Craft effective system prompt for code analysis
   - Rejection messages for unsupported operations
   - Guidelines for agent behavior (when to read, when to write, when to finish)

5. **Agent test scenarios**
   - Create simple agent tests with mock sandbox/LLM
   - Verify tool call parsing and loop termination
   - Test rejection logic for unsupported operations

### NOT Responsible For

- Backend API routes and FastAPI setup (backend-developer owns)
- Docker container lifecycle and sandboxing mechanics (backend-developer owns)
- Worker queue implementation (backend-developer owns)
- Frontend UI and HTML rendering (frontend-developer owns)
- End-to-end integration tests (qa-expert owns)
- Database/persistence layer (MVP has none)

### Write Permission

- `SPECS.md`: Agent/tool sections only (§ 2, § 6)
- Optional: `AGENT_RUNTIME.md` (if detailed agent flow needs separate doc)

### Read Permission

- `_requirements.txt` (NO — product-manager reads only)
- `skeleton.py` (optional reference)
- `SPECS.md` (entire file)
- `MVP.md`
- `REFERENCES.md`

---

## backend-developer

### Responsible For

1. **REST API layer**
   - FastAPI application
   - `POST /tasks` and `GET /tasks/{id}` endpoints
   - JSON request/response serialization
   - Error responses (4xx, 5xx)

2. **Task management**
   - In-memory task store (dict with task IDs as keys)
   - Task state transitions (queued → running → succeeded/failed)
   - Task lifecycle (creation, status updates, completion)

3. **Worker loop**
   - Background worker process
   - Task queue (deque-based, in-memory)
   - Enqueue/dequeue logic
   - Worker error handling and task failure marking

4. **Docker sandbox implementation**
   - `DockerSandbox` class implementing `Sandbox` protocol
   - Container creation with resource limits
   - `exec()`, `read()`, `write()` implementations
   - Container cleanup (`destroy()`)
   - Git clone logic for demo repo

5. **Integration of sandbox + agent**
   - Call `run_agent()` from within worker loop
   - Pass sandbox instance to agent
   - Capture agent output and update task.result
   - Handle agent exceptions and timeouts

6. **Configuration & startup**
   - Docker image build (Dockerfile)
   - Port setup (default: 8000)
   - Environment variable handling (TOGETHER_API_KEY)
   - Startup script for FastAPI + worker

### NOT Responsible For

- LLM provider implementation (llm-architect owns)
- Tool definitions and logic (llm-architect owns)
- Frontend HTML/JS (frontend-developer owns)
- Test case design (qa-expert owns)
- System prompt tuning (llm-architect owns)

### Write Permission

- `SPECS.md`: Backend/sandbox sections only (§ 3, § 4)
- Optional: `BACKEND.md` (detailed backend design if needed)

### Read Permission

- `SPECS.md` (entire file)
- `MVP.md`
- `skeleton.py` (optional reference)
- `REFERENCES.md`

---

## frontend-developer

### Responsible For

1. **Minimal web interface**
   - Single-page HTML form (or minimal React app)
   - Task prompt input field
   - Submit button
   - Task ID display after submission

2. **Polling & status display**
   - Poll `/api/tasks/{id}` at regular intervals (e.g., 1s)
   - Display current task status (queued, running, succeeded, failed)
   - Show iteration count while running

3. **Result rendering**
   - Display markdown output when task succeeds
   - Display error message when task fails
   - HTML escaping for security

4. **Form validation**
   - Validate prompt input (non-empty or use default)
   - Handle API errors gracefully

### NOT Responsible For

- API route implementation (backend-developer owns)
- Authentication or authorization (not in MVP)
- Design system or advanced CSS (keep minimal)
- Backend server startup (backend-developer owns)

### Write Permission

- `FRONTEND.md` (optional; detailed UI spec if needed)
- `.html` or `.js` files in the codebase (as designated by organizer)

### Read Permission

- `SPECS.md` (Frontend section § 5 and API § 3.2)
- `MVP.md`
- `REFERENCES.md`

---

## qa-expert

### Responsible For

1. **Acceptance test design**
   - Translate MVP success criteria into executable tests
   - Design curl scripts and/or pytest assertions
   - Create `demo.sh` script for end-to-end verification

2. **Test scenarios**
   - Task submission → polling → result retrieval
   - Error cases (rejected operations like `pip install`)
   - Timeout handling
   - Container cleanup verification

3. **Manual verification checklist**
   - Verify four pillars are demonstrable (code pointers)
   - Test with vllm TODO/FIXME analysis task
   - Verify markdown output is well-formed
   - Check that unsupported operations show clear rejection messages

4. **Test documentation**
   - `ACCEPTANCE.md` with curl commands
   - `demo.sh` script
   - README section on "How to run tests"

### NOT Responsible For

- Implementation of features (other agents own)
- Product decisions or scope (product-manager owns)
- Architecture design (llm-architect, backend-developer own)

### Write Permission

- `ACCEPTANCE.md` (amend with test scenarios and results)
- `TESTING.md` (detailed test spec if needed)
- `scripts/demo.sh` (acceptance test script)

### Read Permission

- `SPECS.md` (entire file)
- `MVP.md`
- `ACCEPTANCE.md` (initial version from PM)
- All implementation files (to understand behavior)

---

## product-manager (You, initial setup)

### Responsible For (Initial Phase)

1. **Scope definition** → `MVP.md` created ✓
2. **Technical specification** → `SPECS.md` created ✓
3. **Role contracts** → `ROLE_CONTRACTS.md` created ✓
4. **Acceptance criteria** → `ACCEPTANCE.md` created (next)
5. **Reference updates** → `REFERENCES.md` (keep LLM pointer accurate)

### NOT Responsible For

- Implementation of any features (delegate to agents)
- Frontend styling or detailed UI (frontend-developer owns)
- Database schema design (MVP has none)
- Deployment configuration (post-MVP)

### Read/Write for Remaining Docs

See `.claude/docs/README.md` for matrix. After initial four docs are written, PM role is complete unless scope changes or organizer requests updates.

---

## agent-organizer (Delegation & Decisions)

### Responsible For

1. **Agent spawning:** Which agent to delegate to, in what order
2. **Conflict resolution:** When agents disagree on spec interpretation
3. **Scope management:** Decide if changes warrant re-running PM
4. **Progress tracking:** Update `DECISIONS.md` on major decisions

### Read Permission

- All files in `.claude/docs/`
- `skeleton.py` (reference)
- `_requirements.txt` (context only)

### Write Permission

- `DECISIONS.md` only

---

## Cross-Agent Communication

### Spec Disputes

If an implementation agent discovers that SPECS.md cannot be satisfied (e.g., "I cannot implement this tool in 2 hours"), they must:
1. Document the issue in their domain spec (BACKEND.md, AGENT_RUNTIME.md, etc.)
2. Flag it for organizer review
3. Organizer may re-spawn product-manager to adjust scope

### Reference Updates

If REFERENCES.md needs updating (e.g., LangChain version conflict), product-manager handles it. Agents should flag the need via organizer.

### Simplified Implementations

Skeleton.py is a reference sketch. Agents may simplify if it reduces scope meaningfully:
- Instead of Plan/Step tracking, use simple iteration counter ✓ (noted in SPECS.md § 9)
- Instead of policy engine, use tool allow-list ✓ (noted in SPECS.md § 9)
- Instead of persistence, use in-memory store ✓ (noted in SPECS.md § 9)

Document departures in SPECS.md or domain-specific files.

---

## Code Locations (Expected)

After agent implementation, files may live under:

```
/root/CloudAgent/
├── demo/                         # runnable MVP (backend + agent + frontend + Docker)
│   ├── app/                      # backend-developer
│   ├── agent/                    # llm-architect
│   ├── frontend/                 # frontend-developer
│   ├── scripts/demo.sh           # qa-expert
│   ├── tests/
│   ├── Dockerfile                # cloudagent-sandbox:latest
│   ├── requirements.txt
│   └── run.py
├── fixtures/                     # offline sample repo
└── .claude/docs/
    ├── MVP.md
    ├── SPECS.md
    ├── ROLE_CONTRACTS.md
    ├── ACCEPTANCE.md
    ├── BACKEND.md                # (optional, backend-developer)
    ├── AGENT_RUNTIME.md          # (optional, llm-architect)
    ├── FRONTEND.md               # (optional, frontend-developer)
    ├── TESTING.md                # (optional, qa-expert)
    └── DECISIONS.md              # agent-organizer
```

Exact structure is flexible; what matters is clear ownership and `.claude/docs/` as binding spec.

---

## Summary: Who Owns What

| Domain | Primary | Authority |
|--------|---------|-----------|
| Agent loop, LLM, tools | llm-architect | SPECS.md § 2, § 6 |
| REST API, worker, sandbox | backend-developer | SPECS.md § 3, § 4 |
| Frontend form, polling, display | frontend-developer | SPECS.md § 5 |
| Acceptance tests, demo.sh | qa-expert | ACCEPTANCE.md |
| Spec, scope, product decisions | product-manager + organizer | MVP.md, SPECS.md, ROLE_CONTRACTS.md |

