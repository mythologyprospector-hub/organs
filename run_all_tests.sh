#!/bin/bash
# run_all_tests.sh — runs every organ's test suite, aggregates the result.
#
# Deliberately does NOT run `pytest` once from the repo root. Every organ
# has a file called main.py, memory_core.py-style core module, etc. — if
# all eleven organs' tests ran in ONE Python process, the second organ's
# `import main` would silently return the FIRST organ's already-cached
# module instead of loading its own (Python caches by bare module name
# in sys.modules, and pytest's own import-mode setting can't change
# that — it only affects how pytest itself identifies test FILES, not
# what those files import). That's not a bug to work around — it's the
# "no monorepo, no shared venv" principle from day one, doing exactly
# what it's supposed to: these organs were never meant to coexist in one
# interpreter, only to talk over HTTP. This script respects that by
# giving each organ its own subprocess, same as it actually deploys.

set -uo pipefail

TMP_OUTPUT=$(mktemp)
trap 'rm -f "$TMP_OUTPUT"' EXIT

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORGANS=(registry memory communications orchestrator reflection introspection sandbox critic executive io_interface telemetry)
# Tools: real, tested code that lives in this repo but is NOT an organ —
# no main.py, no HTTP service, nothing registers with the Registry.
# tui/ is a client, the first thing here that only consumes; it gets the
# same subprocess-isolated test treatment for the same reason (its own
# fixtures reload tui_data.py fresh, same "no shared venv" principle),
# but it's kept in its own list so this script never calls it an organ.
TOOLS=(tui sensei)

total_pass=0
total_fail=0
failed_organs=()

echo "== Running shared convention tests =="

shared_dir="$REPO_ROOT/shared"
if [ -d "$shared_dir/tests" ]; then
    echo "--- shared ---"
    if (cd "$shared_dir" && python3 -m pytest tests/ -q >"$TMP_OUTPUT" 2>&1); then
        test_rc=0
    else
        test_rc=$?
    fi
    cat "$TMP_OUTPUT"
    summary_line=$(tail -1 "$TMP_OUTPUT")
    echo "  $summary_line"
    if [ "$test_rc" -ne 0 ] || echo "$summary_line" | grep -qE "failed|error" || ! echo "$summary_line" | grep -qE "passed"; then
        failed_organs+=("shared")
    fi
    echo
fi

echo "== Running each organ's tests in its own subprocess =="
echo

for organ in "${ORGANS[@]}"; do
    dir="$REPO_ROOT/$organ"
    if [ ! -d "$dir/tests" ]; then
        echo "  (skipping $organ — no tests/ directory)"
        continue
    fi

    echo "--- $organ ---"
    if (cd "$dir" && python3 -m pytest tests/ -q >"$TMP_OUTPUT" 2>&1); then
        test_rc=0
    else
        test_rc=$?
    fi
    cat "$TMP_OUTPUT"
    summary_line=$(tail -1 "$TMP_OUTPUT")
    echo "  $summary_line"

    if [ "$test_rc" -ne 0 ] || echo "$summary_line" | grep -qE "failed|error" || ! echo "$summary_line" | grep -qE "passed"; then
        failed_organs+=("$organ")
    fi
    echo
done

echo "== Running live cross-organ integration tests (real subprocesses, real HTTP) =="
echo

live_dir="$REPO_ROOT/live_integration"
if [ -d "$live_dir" ]; then
    echo "--- live_integration ---"
    if (cd "$live_dir" && python3 -m pytest -q >"$TMP_OUTPUT" 2>&1); then
        test_rc=0
    else
        test_rc=$?
    fi
    cat "$TMP_OUTPUT"
    summary_line=$(tail -1 "$TMP_OUTPUT")
    echo "  $summary_line"
    if [ "$test_rc" -ne 0 ] || echo "$summary_line" | grep -qE "failed|error" || ! echo "$summary_line" | grep -qE "passed"; then
        failed_organs+=("live_integration")
    fi
    echo
fi

echo "== Running each tool's tests (not an organ, same isolation) =="
echo

for tool in "${TOOLS[@]}"; do
    dir="$REPO_ROOT/$tool"
    if [ ! -d "$dir/tests" ]; then
        echo "  (skipping $tool — no tests/ directory)"
        continue
    fi

    echo "--- $tool ---"
    if (cd "$dir" && python3 -m pytest tests/ -q >"$TMP_OUTPUT" 2>&1); then
        test_rc=0
    else
        test_rc=$?
    fi
    cat "$TMP_OUTPUT"
    summary_line=$(tail -1 "$TMP_OUTPUT")
    echo "  $summary_line"

    if [ "$test_rc" -ne 0 ] || echo "$summary_line" | grep -qE "failed|error" || ! echo "$summary_line" | grep -qE "passed"; then
        failed_organs+=("$tool")
    fi
    echo
done

echo "== Summary =="
if [ ${#failed_organs[@]} -eq 0 ]; then
    echo "All organs' and tools' test suites passed."
    exit 0
else
    echo "Failures: ${failed_organs[*]}"
    echo "Scroll up for details, or re-run one directly:"
    echo "  cd <organ-or-tool> && python3 -m pytest tests/ -v"
    exit 1
fi
