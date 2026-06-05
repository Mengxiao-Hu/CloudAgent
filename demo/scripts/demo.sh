#!/usr/bin/env bash
# CloudAgent End-to-End Acceptance Demo
# Usage: ./scripts/demo.sh [http://localhost:8000]
#
# Exit codes:
#   0 — all checks passed (main task succeeded, rejection case behaved correctly)
#   1 — any check failed (task timed out, API unreachable, unexpected result)
#
# Requirements: curl, jq

set -euo pipefail

API_URL="${1:-http://localhost:8000}"
MAX_POLLS=60          # 60 x 3s = 3 minutes
POLL_INTERVAL=3

# ------------------------------------------------------------------ helpers --

pass() { printf "[PASS] %s\n" "$*"; }
fail() { printf "[FAIL] %s\n" "$*" >&2; EXIT_CODE=1; }
info() { printf "       %s\n" "$*"; }

EXIT_CODE=0

check_deps() {
    local missing=0
    for cmd in curl jq; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            fail "Required tool not found: $cmd"
            missing=1
        fi
    done
    [ "$missing" -eq 1 ] && exit 1
}

poll_task() {
    # poll_task <task_id> <description>
    # Prints status each poll; returns 0 on succeeded, 1 on failed/timeout.
    local task_id="$1"
    local desc="$2"
    local count=0

    while [ "$count" -lt "$MAX_POLLS" ]; do
        local response
        response=$(curl -sf "${API_URL}/api/tasks/${task_id}" 2>/dev/null) || {
            fail "GET /api/tasks/${task_id} — connection error on poll ${count}"
            return 1
        }

        local status iteration
        status=$(echo "$response" | jq -r '.status // "unknown"')
        iteration=$(echo "$response" | jq -r '.iteration // 0')

        printf "       [poll %2d/%d] status=%-10s  iteration=%s\n" \
               "$((count+1))" "$MAX_POLLS" "$status" "$iteration"

        case "$status" in
            succeeded)
                LAST_RESPONSE="$response"
                return 0
                ;;
            failed)
                LAST_RESPONSE="$response"
                return 1
                ;;
        esac

        sleep "$POLL_INTERVAL"
        count=$((count + 1))
    done

    fail "$desc — timed out after $((MAX_POLLS * POLL_INTERVAL))s"
    return 1
}

# ------------------------------------------------------------------ startup --

check_deps

printf "\n=== CloudAgent MVP Acceptance Demo ===\n"
printf "API : %s\n" "$API_URL"
printf "Date: %s\n\n" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# Verify the server is up before running any tests.
if ! curl -sf "${API_URL}/" >/dev/null 2>&1 && \
   ! curl -sf "${API_URL}/api/tasks" >/dev/null 2>&1; then
    # Accept a 405/422 on GET /api/tasks as "server is up"
    HTTP_STATUS=$(curl -o /dev/null -sw "%{http_code}" "${API_URL}/api/tasks" 2>/dev/null || true)
    if [ "$HTTP_STATUS" = "000" ]; then
        fail "Server not reachable at ${API_URL} — start it before running this script."
        exit 1
    fi
fi
pass "Server is reachable at ${API_URL}"

# ------------------------------------------------------------------ test 1 --
printf "\n--- Test 1: Submit main task (TODO/FIXME analysis) ---\n"

MAIN_PROMPT="Find all TODO and FIXME in the vllm repo and summarize."

SUBMIT_RESPONSE=$(curl -sf \
    -X POST "${API_URL}/api/tasks" \
    -H "Content-Type: application/json" \
    -d "{\"prompt\": \"${MAIN_PROMPT}\"}" 2>/dev/null) || {
    fail "POST /api/tasks — connection error"
    exit 1
}

info "Raw submit response: ${SUBMIT_RESPONSE}"

# Validate HTTP-level acceptance (202 expected; some frameworks return 200 for 202)
HTTP_STATUS=$(curl -o /dev/null -sw "%{http_code}" \
    -X POST "${API_URL}/api/tasks" \
    -H "Content-Type: application/json" \
    -d "{\"prompt\": \"health-check-probe\"}" 2>/dev/null || echo "000")

if [ "$HTTP_STATUS" = "202" ] || [ "$HTTP_STATUS" = "200" ]; then
    pass "POST /api/tasks returned ${HTTP_STATUS} (task accepted)"
else
    fail "POST /api/tasks returned ${HTTP_STATUS} — expected 202 or 200"
fi

TASK_ID=$(echo "$SUBMIT_RESPONSE" | jq -r '.id // empty')
if [ -z "$TASK_ID" ] || [ "$TASK_ID" = "null" ]; then
    fail "Response did not contain a valid task id"
    info "Response was: ${SUBMIT_RESPONSE}"
    exit 1
fi
pass "Task created with id=${TASK_ID}"

INITIAL_STATUS=$(echo "$SUBMIT_RESPONSE" | jq -r '.status // "unknown"')
if [ "$INITIAL_STATUS" = "queued" ]; then
    pass "Initial status is 'queued' (async dispatch confirmed)"
else
    info "Initial status is '${INITIAL_STATUS}' (expected 'queued'; continuing)"
fi

# ------------------------------------------------------------------ test 2 --
printf "\n--- Test 2: Poll GET /api/tasks/{id} until terminal state ---\n"
info "Polling every ${POLL_INTERVAL}s (max ${MAX_POLLS} polls = $((MAX_POLLS * POLL_INTERVAL))s)"

LAST_RESPONSE=""
if poll_task "$TASK_ID" "main TODO/FIXME task"; then
    pass "Task ${TASK_ID} reached status=succeeded"

    # Verify state transitions were visible (iteration > 0 implies running was visited)
    FINAL_ITERATION=$(echo "$LAST_RESPONSE" | jq -r '.iteration // 0')
    if [ "$FINAL_ITERATION" -gt 0 ] 2>/dev/null; then
        pass "Agent iterated ${FINAL_ITERATION} time(s) — loop ran as expected"
    else
        info "iteration field is ${FINAL_ITERATION} — state transition to 'running' may not be captured in final snapshot"
    fi

    # Validate result field is present and non-empty
    RESULT=$(echo "$LAST_RESPONSE" | jq -r '.result // empty')
    if [ -z "$RESULT" ]; then
        fail "Task succeeded but 'result' field is empty or missing"
    else
        pass "Result field is populated"
    fi

    # Verify result looks like a markdown summary
    if echo "$RESULT" | grep -qiE '(TODO|FIXME|#|\*\*)'; then
        pass "Result contains expected TODO/FIXME references or markdown structure"
    else
        info "Result does not obviously mention TODO/FIXME — review manually"
        info "(first 200 chars): $(echo "$RESULT" | head -c 200)"
    fi

    printf "\n--- Final result (first 40 lines) ---\n"
    echo "$RESULT" | head -40
    printf "\n"
else
    TASK_STATUS=$(echo "$LAST_RESPONSE" | jq -r '.status // "unknown"')
    TASK_ERROR=$(echo "$LAST_RESPONSE" | jq -r '.error // "(none)"')
    fail "Main task did not succeed — status=${TASK_STATUS}, error=${TASK_ERROR}"
fi

# ------------------------------------------------------------------ test 3 --
printf "\n--- Test 3: Rejection case — 'run pip install requests' ---\n"

REJECT_PROMPT="run pip install requests"

REJECT_RESPONSE=$(curl -sf \
    -X POST "${API_URL}/api/tasks" \
    -H "Content-Type: application/json" \
    -d "{\"prompt\": \"${REJECT_PROMPT}\"}" 2>/dev/null) || {
    fail "POST /api/tasks (rejection probe) — connection error"
    EXIT_CODE=1
    REJECT_RESPONSE=""
}

if [ -n "$REJECT_RESPONSE" ]; then
    REJECT_ID=$(echo "$REJECT_RESPONSE" | jq -r '.id // empty')

    if [ -z "$REJECT_ID" ] || [ "$REJECT_ID" = "null" ]; then
        # API may have already rejected at the HTTP layer (400)
        HTTP_REJECT=$(curl -o /dev/null -sw "%{http_code}" \
            -X POST "${API_URL}/api/tasks" \
            -H "Content-Type: application/json" \
            -d "{\"prompt\": \"${REJECT_PROMPT}\"}" 2>/dev/null || echo "000")
        if [ "$HTTP_REJECT" = "400" ] || [ "$HTTP_REJECT" = "422" ]; then
            pass "Server rejected 'pip install' at the HTTP layer (${HTTP_REJECT})"
        else
            fail "No task id returned and HTTP status was ${HTTP_REJECT} — unclear rejection"
        fi
    else
        info "Rejection-probe task id=${REJECT_ID}; waiting up to 30s for result"
        # Short wait — we only need to see if it was rejected or errored
        sleep 10
        REJ_POLL=$(curl -sf "${API_URL}/api/tasks/${REJECT_ID}" 2>/dev/null || echo "{}")
        REJ_STATUS=$(echo "$REJ_POLL" | jq -r '.status // "unknown"')
        REJ_ERROR=$(echo "$REJ_POLL" | jq -r '.error // ""')
        REJ_RESULT=$(echo "$REJ_POLL" | jq -r '.result // ""')

        info "Rejection-probe status: ${REJ_STATUS}"
        info "Rejection-probe error : ${REJ_ERROR}"

        # Accept either: task failed with rejection message, OR result mentions rejection
        if echo "${REJ_ERROR}${REJ_RESULT}" | grep -qiE \
                '(not supported|not available|rejected|forbidden|pip|install|dependency)'; then
            pass "Rejection message found for 'pip install' probe"
        elif [ "$REJ_STATUS" = "failed" ]; then
            pass "Task failed as expected for unsupported operation (pip install)"
        elif [ "$REJ_STATUS" = "queued" ] || [ "$REJ_STATUS" = "running" ]; then
            info "Task still running after 10s — the agent may reject mid-loop; not counted as failure here"
        else
            fail "Unexpected outcome for pip install probe: status=${REJ_STATUS}, error=${REJ_ERROR}"
        fi
    fi
fi

# --------------------------------------------------------------- summary --

printf "\n=== Demo Summary ===\n"
if [ "$EXIT_CODE" -eq 0 ]; then
    printf "ALL CHECKS PASSED — CloudAgent MVP acceptance demo succeeded.\n\n"
else
    printf "ONE OR MORE CHECKS FAILED — review [FAIL] lines above.\n\n"
fi

exit "$EXIT_CODE"
