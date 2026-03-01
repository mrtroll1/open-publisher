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

mkdir -p "$LOG_DIR"

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

# --- Run loop ---

RUN_ID=$(date +%Y%m%d_%H%M%S)

echo "=== Autonomous run $RUN_ID starting ==="
echo "Plan: $PLAN_FILE"
echo "Sessions: $ITERATIONS every ${INTERVAL}s"
echo "Max turns per session: $MAX_TURNS"
echo ""

for i in $(seq 1 $ITERATIONS); do
    SESSION_LOG="$LOG_DIR/session-${RUN_ID}-$(printf '%02d' $i).log"
    SESSION_START=$(date +%s)

    echo "--- Session $i/$ITERATIONS at $(date) ---" | tee "$SESSION_LOG"

    PROMPT=$(cat "$PROMPT_FILE")
    PROMPT="$PROMPT

[Session $i of $ITERATIONS. Plan file: $PLAN_FILE]"

    cd "$ROOT_DIR"
    claude -p "$PROMPT" \
        --allowedTools "$ALLOWED_TOOLS" \
        --disallowedTools "$DENIED_TOOLS" \
        --max-turns "$MAX_TURNS" \
        2>&1 | tee -a "$SESSION_LOG" || true

    echo "--- Session $i completed at $(date) ---" | tee -a "$SESSION_LOG"

    # Sleep only the remaining time until the next 30-min mark
    if [ $i -lt $ITERATIONS ]; then
        ELAPSED=$(( $(date +%s) - SESSION_START ))
        REMAINING=$(( INTERVAL - ELAPSED ))
        if [ $REMAINING -gt 0 ]; then
            echo "Next session in ${REMAINING}s..."
            sleep $REMAINING
        else
            echo "Session took longer than ${INTERVAL}s, starting next immediately."
        fi
    fi
done

echo "=== Autonomous run $RUN_ID completed at $(date) ==="
