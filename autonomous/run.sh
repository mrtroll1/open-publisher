#!/bin/bash
# Autonomous Claude Code runner
# Launches Claude every 30 minutes to work through plan files sequentially.
# Advances to the next plan when the current one has no unchecked items.
#
# Usage: ./autonomous/run.sh <duration> <plan1> [plan2] [plan3] ...
# Example: ./autonomous/run.sh 6h plan-5
#          ./autonomous/run.sh 12h plan-5 plan-6 plan-7 plan-8

set -euo pipefail

if [ $# -lt 2 ]; then
    echo "Usage: ./autonomous/run.sh <duration> <plan1> [plan2] [plan3] ..."
    echo "  duration: Xh format (e.g. 6h, 12h)"
    echo "  Plan files must exist at autonomous/plans/<name>.md"
    echo ""
    echo "Example: ./autonomous/run.sh 12h plan-5 plan-6 plan-7 plan-8"
    exit 1
fi

DURATION_ARG="$1"
shift
PLAN_NAMES=("$@")

# Parse duration (Xh format)
if [[ ! "$DURATION_ARG" =~ ^[0-9]+h$ ]]; then
    echo "ERROR: Duration must be in Xh format (e.g. 2h, 6h, 12h)"
    exit 1
fi
TOTAL_HOURS="${DURATION_ARG%h}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/autonomous/logs"
PROMPT_FILE="$ROOT_DIR/.claude/autonomous-prompt.md"
INTERVAL=1800  # 30 minutes
ITERATIONS=$(( TOTAL_HOURS * 3600 / INTERVAL ))
MAX_TURNS=80

# Verify we're on the right branch
CURRENT_BRANCH=$(git -C "$ROOT_DIR" branch --show-current)
if [ "$CURRENT_BRANCH" != "claude-autonomous" ]; then
    echo "ERROR: Must be on claude-autonomous branch (currently on $CURRENT_BRANCH)"
    exit 1
fi

# Verify all plan files exist
PLAN_FILES=()
for name in "${PLAN_NAMES[@]}"; do
    pf="$ROOT_DIR/autonomous/plans/${name}.md"
    if [ ! -f "$pf" ]; then
        echo "ERROR: Plan file not found: $pf"
        exit 1
    fi
    PLAN_FILES+=("$pf")
done

# --- Helpers ---

plan_is_complete() {
    # Returns 0 (true) if plan has no unchecked items
    local plan_file="$1"
    if grep -q '\- \[ \]' "$plan_file"; then
        return 1  # has unchecked items
    fi
    return 0  # all checked (or no checkboxes at all)
}

get_current_plan() {
    # Find the first incomplete plan, or return empty if all done
    for pf in "${PLAN_FILES[@]}"; do
        if ! plan_is_complete "$pf"; then
            echo "$pf"
            return
        fi
    done
    echo ""  # all plans complete
}

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

# --- Build plan queue description ---

PLAN_QUEUE=""
for idx in "${!PLAN_NAMES[@]}"; do
    PLAN_QUEUE="${PLAN_QUEUE}  $((idx+1)). ${PLAN_NAMES[$idx]} (${PLAN_FILES[$idx]})"$'\n'
done

# --- Run loop ---

log "=== RUN STARTED ==="
log "Plans: ${PLAN_NAMES[*]}"
log "Duration: ${TOTAL_HOURS}h | Sessions: $ITERATIONS x ${INTERVAL}s, max $MAX_TURNS turns each"
log ""

# Also start the detailed last-run log (overwritten each run)
cp /dev/null "$LAST_RUN_LOG"
echo "=== Detailed log for run $RUN_ID ===" >> "$LAST_RUN_LOG"
echo "Started: $(date)" >> "$LAST_RUN_LOG"
echo "Plans: ${PLAN_NAMES[*]}" >> "$LAST_RUN_LOG"
echo "" >> "$LAST_RUN_LOG"

COMPLETED=0
FAILED=0

for i in $(seq 1 $ITERATIONS); do
    SESSION_DETAIL="$LOG_DIR/session-${RUN_ID}-$(printf '%02d' $i).log"
    SESSION_START=$(date +%s)

    # Determine current plan (first incomplete one)
    CURRENT_PLAN=$(get_current_plan)
    if [ -z "$CURRENT_PLAN" ]; then
        log "All plans complete! Stopping early."
        break
    fi

    CURRENT_PLAN_NAME=$(basename "$CURRENT_PLAN" .md)
    log "--- Session $i/$ITERATIONS started [plan: $CURRENT_PLAN_NAME] ---"
    echo "====== SESSION $i/$ITERATIONS [plan: $CURRENT_PLAN_NAME] at $(date) ======" >> "$LAST_RUN_LOG"

    PROMPT=$(cat "$PROMPT_FILE")
    PROMPT="$PROMPT

[Session $i of $ITERATIONS. Current plan file: $CURRENT_PLAN]

Plan queue (work through in order, advance when current plan has no unchecked items):
$PLAN_QUEUE"

    cd "$ROOT_DIR"

    # Capture exit code
    EXIT_CODE=0
    claude -p "$PROMPT" \
        --allowedTools "$ALLOWED_TOOLS" \
        --disallowedTools "$DENIED_TOOLS" \
        --max-turns "$MAX_TURNS" \
        2>&1 | tee "$SESSION_DETAIL" >> "$LAST_RUN_LOG" || EXIT_CODE=$?

    SESSION_END=$(date +%s)
    DURATION=$(( SESSION_END - SESSION_START ))
    DURATION_MIN=$(( DURATION / 60 ))

    # Detect what happened
    if [ $EXIT_CODE -ne 0 ]; then
        STATUS="FAILED (exit code $EXIT_CODE)"
        FAILED=$(( FAILED + 1 ))
    else
        STATUS="OK"
        COMPLETED=$(( COMPLETED + 1 ))
    fi

    # Check if current plan just completed
    if plan_is_complete "$CURRENT_PLAN"; then
        log ">>> Plan $CURRENT_PLAN_NAME is now COMPLETE <<<"
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
log "Completed: $COMPLETED | Failed: $FAILED  | Total: $ITERATIONS"

# Final plan status
for idx in "${!PLAN_FILES[@]}"; do
    if plan_is_complete "${PLAN_FILES[$idx]}"; then
        log "  ${PLAN_NAMES[$idx]}: DONE"
    else
        REMAINING_ITEMS=$(grep -c '\- \[ \]' "${PLAN_FILES[$idx]}" || true)
        log "  ${PLAN_NAMES[$idx]}: ${REMAINING_ITEMS} items remaining"
    fi
done

echo "=== Run finished at $(date) ===" >> "$LAST_RUN_LOG"
echo "Completed: $COMPLETED | Failed: $FAILED " >> "$LAST_RUN_LOG"
