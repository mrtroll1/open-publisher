#!/bin/bash
# Autonomous Claude Code runner
# Launches Claude every 30 minutes for 12 hours to work on the current plan.
# Usage: ./autonomous/run.sh <plan-name>
# Example: ./autonomous/run.sh my-feature

set -euo pipefail

if [ $# -eq 0 ]; then
    echo "Usage: ./autonomous/run.sh <plan-name>"
    echo "Plan file must exist at autonomous/plans/<plan-name>.md"
    exit 1
fi

PLAN_NAME="$1"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/autonomous/logs"
PROMPT_FILE="$ROOT_DIR/.claude/autonomous-prompt.md"
PLAN_FILE="$ROOT_DIR/autonomous/plans/${PLAN_NAME}.md"
ITERATIONS=24
INTERVAL=1800  # 30 minutes
MAX_TURNS=80

# Verify we're on the right branch
CURRENT_BRANCH=$(git -C "$ROOT_DIR" branch --show-current)
if [ "$CURRENT_BRANCH" != "claude-autonomous" ]; then
    echo "ERROR: Must be on claude-autonomous branch (currently on $CURRENT_BRANCH)"
    exit 1
fi

# Verify plan file exists
if [ ! -f "$PLAN_FILE" ]; then
    echo "ERROR: Plan file not found: $PLAN_FILE"
    echo "Create a plan first using the planner agent."
    exit 1
fi

# --- Permissions ---

ALLOWED_TOOLS=$(cat <<'EOF'
Read,
Write,
Edit,
Glob,
Grep,
Agent,
WebSearch,
WebFetch,
Bash(git add:*),
Bash(git commit:*),
Bash(git push:*),
Bash(git status:*),
Bash(git diff:*),
Bash(git log:*),
Bash(git stash:*),
Bash(python:*),
Bash(.venv/bin/python:*),
Bash(.venv/bin/pip install:*),
Bash(ls:*),
Bash(mkdir:*),
Bash(cat:*),
Bash(head:*),
Bash(tail:*),
Bash(curl:*),
Bash(wc:*),
Bash(touch:*),
Bash(cp:*),
Bash(mv:*),
Bash(echo:*),
Bash(grep:*),
Bash(sort:*),
Bash(find:*),
Bash(rm:*),
Bash(docker compose:*),
Bash(pip:*)
EOF
)
# Strip newlines/spaces — claude CLI expects a single comma-separated string
ALLOWED_TOOLS=$(echo "$ALLOWED_TOOLS" | tr -d '\n ' )

DENIED_TOOLS=$(cat <<'EOF'
Bash(rm -rf:*),
Bash(rm -r:*),
Bash(rmdir:*),
Bash(git branch:*),
Bash(git checkout:*),
Bash(git switch:*),
Bash(git merge:*),
Bash(git rebase:*),
Bash(git reset --hard:*),
Bash(git clean:*),
Bash(git push --force:*),
Bash(git push -f:*),
Bash(chmod:*),
Bash(chown:*),
Bash(sudo:*),
Bash(sh:*),
Bash(bash:*),
Bash(eval:*)
EOF
)
DENIED_TOOLS=$(echo "$DENIED_TOOLS" | tr -d '\n ' )

# --- Logging ---

RUN_ID=$(date +%Y%m%d_%H%M%S)
RUN_LOG="$LOG_DIR/run-${RUN_ID}.log"
LAST_RUN_LOG="$LOG_DIR/last-run.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" | tee -a "$RUN_LOG"
}

# --- Run loop ---

log "=== RUN STARTED ==="
log "Plan: $PLAN_NAME ($PLAN_FILE)"
log "Sessions: $ITERATIONS x ${INTERVAL}s, max $MAX_TURNS turns each"
log ""

# Also start the detailed last-run log (overwritten each run)
cp /dev/null "$LAST_RUN_LOG"
echo "=== Detailed log for run $RUN_ID ===" >> "$LAST_RUN_LOG"
echo "Started: $(date)" >> "$LAST_RUN_LOG"
echo "Plan: $PLAN_FILE" >> "$LAST_RUN_LOG"
echo "" >> "$LAST_RUN_LOG"

COMPLETED=0
FAILED=0
STUCK=0

for i in $(seq 1 $ITERATIONS); do
    SESSION_DETAIL="$LOG_DIR/session-${RUN_ID}-$(printf '%02d' $i).log"
    SESSION_START=$(date +%s)

    log "--- Session $i/$ITERATIONS started ---"
    echo "====== SESSION $i/$ITERATIONS at $(date) ======" >> "$LAST_RUN_LOG"

    PROMPT=$(cat "$PROMPT_FILE")
    PROMPT="$PROMPT

[Session $i of $ITERATIONS. Plan file: $PLAN_FILE]"

    cd "$ROOT_DIR"

    # Capture exit code
    EXIT_CODE=0
    timeout "${INTERVAL}s" claude -p "$PROMPT" \
        --allowedTools "$ALLOWED_TOOLS" \
        --disallowedTools "$DENIED_TOOLS" \
        --max-turns "$MAX_TURNS" \
        2>&1 | tee "$SESSION_DETAIL" >> "$LAST_RUN_LOG" || EXIT_CODE=$?

    SESSION_END=$(date +%s)
    DURATION=$(( SESSION_END - SESSION_START ))
    DURATION_MIN=$(( DURATION / 60 ))

    # Detect what happened
    if [ $EXIT_CODE -eq 124 ]; then
        STATUS="STUCK (timed out after ${INTERVAL}s)"
        STUCK=$(( STUCK + 1 ))
    elif [ $EXIT_CODE -ne 0 ]; then
        STATUS="FAILED (exit code $EXIT_CODE)"
        FAILED=$(( FAILED + 1 ))
    else
        STATUS="OK"
        COMPLETED=$(( COMPLETED + 1 ))
    fi

    # Changelog: what commits were made during this session?
    COMMITS=$(git -C "$ROOT_DIR" log --oneline --since="@${SESSION_START}" --until="@${SESSION_END}" 2>/dev/null || true)
    if [ -z "$COMMITS" ]; then
        COMMITS="(no commits)"
    fi

    log "Session $i: $STATUS | ${DURATION_MIN}m$(( DURATION % 60 ))s | $COMMITS"
    echo "--- Session $i result: $STATUS (${DURATION}s) ---" >> "$LAST_RUN_LOG"
    echo "Commits: $COMMITS" >> "$LAST_RUN_LOG"
    echo "" >> "$LAST_RUN_LOG"

    # Sleep only the remaining time until the next 30-min mark
    if [ $i -lt $ITERATIONS ]; then
        REMAINING=$(( INTERVAL - DURATION ))
        if [ $REMAINING -gt 0 ]; then
            log "Next session in ${REMAINING}s..."
            sleep $REMAINING
        else
            log "Session ran long, starting next immediately."
        fi
    fi
done

log ""
log "=== RUN FINISHED ==="
log "Completed: $COMPLETED | Failed: $FAILED | Stuck: $STUCK | Total: $ITERATIONS"

echo "=== Run finished at $(date) ===" >> "$LAST_RUN_LOG"
echo "Completed: $COMPLETED | Failed: $FAILED | Stuck: $STUCK" >> "$LAST_RUN_LOG"
