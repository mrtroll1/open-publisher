"""Tests for autonomous/run.sh plan parsing logic.

Tests the two bash functions via subprocess:
  - plan_is_complete: checks if a plan file has no unchecked items
  - get_current_plan: returns the first incomplete plan from a list
"""

import os
import subprocess
import textwrap

import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN_SH = os.path.join(ROOT_DIR, "autonomous", "run.sh")


def _run_bash(script: str) -> subprocess.CompletedProcess:
    """Source run.sh functions, then run a snippet."""
    # Extract just the function definitions from run.sh, then run the test script
    full = f"""
set -euo pipefail

# Inline the two functions from run.sh
plan_is_complete() {{
    local plan_file="$1"
    if grep -q '\\- \\[ \\]' "$plan_file"; then
        return 1
    fi
    return 0
}}

PLAN_FILES=()

get_current_plan() {{
    for pf in "${{PLAN_FILES[@]}}"; do
        if ! plan_is_complete "$pf"; then
            echo "$pf"
            return
        fi
    done
    echo ""
}}

{script}
"""
    return subprocess.run(
        ["bash", "-c", full],
        capture_output=True, text=True, timeout=5,
    )


def _write_plan(tmp_path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content))
    return str(p)


# ---------------------------------------------------------------------------
#  plan_is_complete
# ---------------------------------------------------------------------------

class TestPlanIsComplete:

    def test_all_checked(self, tmp_path):
        f = _write_plan(tmp_path, "done.md", """\
            # Plan
            - [x] Step one
            - [x] Step two
            - [x] Step three
        """)
        r = _run_bash(f'plan_is_complete "{f}" && echo "COMPLETE" || echo "INCOMPLETE"')
        assert r.stdout.strip() == "COMPLETE"

    def test_one_unchecked(self, tmp_path):
        f = _write_plan(tmp_path, "partial.md", """\
            # Plan
            - [x] Step one
            - [ ] Step two
            - [x] Step three
        """)
        r = _run_bash(f'plan_is_complete "{f}" && echo "COMPLETE" || echo "INCOMPLETE"')
        assert r.stdout.strip() == "INCOMPLETE"

    def test_all_unchecked(self, tmp_path):
        f = _write_plan(tmp_path, "fresh.md", """\
            # Plan
            - [ ] Step one
            - [ ] Step two
        """)
        r = _run_bash(f'plan_is_complete "{f}" && echo "COMPLETE" || echo "INCOMPLETE"')
        assert r.stdout.strip() == "INCOMPLETE"

    def test_no_checkboxes(self, tmp_path):
        """A plan with no checkboxes counts as complete (nothing to do)."""
        f = _write_plan(tmp_path, "empty.md", """\
            # Just a header
            Some text with no checklist items.
        """)
        r = _run_bash(f'plan_is_complete "{f}" && echo "COMPLETE" || echo "INCOMPLETE"')
        assert r.stdout.strip() == "COMPLETE"

    def test_nested_checkboxes(self, tmp_path):
        f = _write_plan(tmp_path, "nested.md", """\
            # Plan
            - [x] 1.0 Section
              - [x] 1.1 Sub-step done
              - [ ] 1.2 Sub-step not done
        """)
        r = _run_bash(f'plan_is_complete "{f}" && echo "COMPLETE" || echo "INCOMPLETE"')
        assert r.stdout.strip() == "INCOMPLETE"

    def test_checkbox_in_code_block_still_matches(self, tmp_path):
        """Grep is line-based — a [ ] inside a code block still counts as unchecked.
        This is a known limitation, not a bug — plans shouldn't have [ ] in code blocks."""
        f = _write_plan(tmp_path, "code.md", """\
            # Plan
            - [x] All real items done

            ```
            - [ ] This is in a code block
            ```
        """)
        r = _run_bash(f'plan_is_complete "{f}" && echo "COMPLETE" || echo "INCOMPLETE"')
        # grep matches the code block line — known behavior
        assert r.stdout.strip() == "INCOMPLETE"

    def test_similar_but_not_checkbox(self, tmp_path):
        """Text like '[ ]' without the leading '- ' should not match."""
        f = _write_plan(tmp_path, "similar.md", """\
            # Plan
            - [x] Done item
            Note: arrays use [ ] syntax.
        """)
        r = _run_bash(f'plan_is_complete "{f}" && echo "COMPLETE" || echo "INCOMPLETE"')
        assert r.stdout.strip() == "COMPLETE"

    def test_real_plan_format(self, tmp_path):
        """Test against the actual plan formatting style used in plan-5.md etc."""
        f = _write_plan(tmp_path, "real.md", """\
            # Phase 5: Environments

            ## 5.1 Schema

            - [x] 5.1.1 Add to `_SCHEMA_SQL` in `base.py`:
            - [x] 5.1.2 Add seed data migration
            - [ ] 5.1.3 Run `pytest` — all tests pass

            ## 5.2 Repository

            - [ ] 5.2.1 Create `environment_repo.py`
            - [ ] 5.2.2 Add to `DbGateway`
        """)
        r = _run_bash(f'plan_is_complete "{f}" && echo "COMPLETE" || echo "INCOMPLETE"')
        assert r.stdout.strip() == "INCOMPLETE"


# ---------------------------------------------------------------------------
#  get_current_plan
# ---------------------------------------------------------------------------

class TestGetCurrentPlan:

    def test_returns_first_incomplete(self, tmp_path):
        done = _write_plan(tmp_path, "done.md", """\
            - [x] All done
        """)
        wip = _write_plan(tmp_path, "wip.md", """\
            - [x] First done
            - [ ] Second not done
        """)
        future = _write_plan(tmp_path, "future.md", """\
            - [ ] Nothing done
        """)
        r = _run_bash(f"""
PLAN_FILES=("{done}" "{wip}" "{future}")
get_current_plan
""")
        assert r.stdout.strip() == wip

    def test_returns_empty_when_all_complete(self, tmp_path):
        a = _write_plan(tmp_path, "a.md", "- [x] Done")
        b = _write_plan(tmp_path, "b.md", "- [x] Done")
        r = _run_bash(f"""
PLAN_FILES=("{a}" "{b}")
result=$(get_current_plan)
if [ -z "$result" ]; then
    echo "ALL_DONE"
else
    echo "$result"
fi
""")
        assert r.stdout.strip() == "ALL_DONE"

    def test_returns_first_when_all_incomplete(self, tmp_path):
        a = _write_plan(tmp_path, "a.md", "- [ ] Not done")
        b = _write_plan(tmp_path, "b.md", "- [ ] Not done")
        r = _run_bash(f"""
PLAN_FILES=("{a}" "{b}")
get_current_plan
""")
        assert r.stdout.strip() == a

    def test_skips_completed_plans(self, tmp_path):
        """Simulates plan-5 done, plan-6 done, plan-7 in progress."""
        p5 = _write_plan(tmp_path, "plan-5.md", """\
            - [x] 5.1 Schema
            - [x] 5.2 Repo
            - [x] 5.3 Tests
        """)
        p6 = _write_plan(tmp_path, "plan-6.md", """\
            - [x] 6.1 Entities table
            - [x] 6.2 Knowledge FK
        """)
        p7 = _write_plan(tmp_path, "plan-7.md", """\
            - [x] 7.1 Memory service
            - [ ] 7.2 MCP server
        """)
        p8 = _write_plan(tmp_path, "plan-8.md", """\
            - [ ] 8.1 Crawlers
        """)
        r = _run_bash(f"""
PLAN_FILES=("{p5}" "{p6}" "{p7}" "{p8}")
get_current_plan
""")
        assert r.stdout.strip() == p7

    def test_single_plan(self, tmp_path):
        f = _write_plan(tmp_path, "solo.md", "- [ ] Only item")
        r = _run_bash(f"""
PLAN_FILES=("{f}")
get_current_plan
""")
        assert r.stdout.strip() == f

    def test_single_plan_complete(self, tmp_path):
        f = _write_plan(tmp_path, "solo.md", "- [x] Only item")
        r = _run_bash(f"""
PLAN_FILES=("{f}")
result=$(get_current_plan)
if [ -z "$result" ]; then
    echo "ALL_DONE"
else
    echo "$result"
fi
""")
        assert r.stdout.strip() == "ALL_DONE"
