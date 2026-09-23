#!/usr/bin/env bash
# shell_watcher.sh — the real Observe half of Sensei's shell detector.
#
# What this is: a script you actually run, on your actual machine, that
# actually reads your actual shell history and POSTs a recent window of it
# to the real /sensei/detect/shell endpoint. Detection and dedup all live
# server-side (shell_detector.py + sensei_core.py's seen_chains tracking)
# — this script's only job is getting real commands there. It never sees
# or decides anything about mode; whether a detected chain actually
# surfaces as a toast is still decided by Sensei's mode at generation
# time, same as every other nudge source.
#
# Install:
#   1. put this on PATH, chmod +x it
#   2. add ONE line to your shell rc so it runs after every command
#      (bash, in ~/.bashrc):
#          PROMPT_COMMAND="sensei_shell_watcher_tick; ${PROMPT_COMMAND}"
#      or just run it periodically from cron/a systemd timer instead —
#      it's a stateless, idempotent scan of your recent history either
#      way, not something that needs to fire on literally every prompt.
#   3. (zsh) same idea via precmd():
#          sensei_shell_watcher_tick() { .../shell_watcher.sh --tick; }
#          precmd_functions+=(sensei_shell_watcher_tick)
#
# This degrades the same way every other fire-and-forget path in this
# codebase does: if Sensei isn't reachable, curl fails quietly and your
# shell is never blocked or slowed by it (a short --max-time bounds the
# worst case).

set -uo pipefail

SENSEI_URL="${SENSEI_BASE_URL:-http://localhost:8012}"
HISTORY_WINDOW="${SENSEI_SHELL_WINDOW:-200}"

_recent_commands_json() {
    # `history` (bash) / `fc -l` (zsh) both prefix each line with a
    # history number; strip that, drop blank lines, keep the last N,
    # and hand back a JSON array of strings — no jq dependency, this is
    # simple enough to do with a small here-doc via python3 (already a
    # hard requirement for this whole codebase).
    if [ -n "${BASH_VERSION:-}" ]; then
        history "$HISTORY_WINDOW" | sed -E 's/^[[:space:]]*[0-9]+[[:space:]]*//'
    elif [ -n "${ZSH_VERSION:-}" ]; then
        fc -l -n 1 | tail -n "$HISTORY_WINDOW"
    else
        echo "shell_watcher.sh: unsupported shell (need bash or zsh)" >&2
        return 1
    fi
}

sensei_shell_watcher_tick() {
    local lines
    lines="$(_recent_commands_json)" || return 0

    python3 - "$SENSEI_URL" <<'PYEOF' <<<"$lines"
import json
import sys
import urllib.error
import urllib.request

base_url = sys.argv[1]
commands = [line for line in sys.stdin.read().splitlines() if line.strip()]
if not commands:
    sys.exit(0)

payload = json.dumps({"commands": commands}).encode("utf-8")
req = urllib.request.Request(
    f"{base_url}/sensei/detect/shell", data=payload,
    headers={"Content-Type": "application/json"}, method="POST",
)
try:
    urllib.request.urlopen(req, timeout=3.0)
except (urllib.error.URLError, urllib.error.HTTPError):
    pass  # fire-and-forget — sensei being unreachable never blocks the shell
PYEOF
}

# Allow `./shell_watcher.sh --tick` as a one-shot invocation (cron/systemd
# timer usage) in addition to being sourced for PROMPT_COMMAND/precmd use.
if [ "${1:-}" = "--tick" ]; then
    sensei_shell_watcher_tick
fi
