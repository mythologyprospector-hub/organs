# shell_hook.bash — Sensei's shell watcher hook.
#
# Add this to your ~/.bashrc:
#
#   source /srv/organs/sensei/watchers/shell_hook.bash
#
# What it does: after each command finishes (right before the next
# prompt draws), grabs that command from history and hands it to
# shell_watcher.py in the background. Uses PROMPT_COMMAND rather than
# `trap DEBUG` deliberately — DEBUG fires on every sub-command inside
# functions, loops, and pipelines too, which is noisy and would log
# things that were never typed at the prompt. PROMPT_COMMAND fires
# once per completed top-level command, same mechanism shell-history
# tools like atuin/mcfly use for this.
#
# Backgrounded with `&` so a slow or unreachable Sensei/Telemetry
# organ NEVER makes your prompt hang — worth stating plainly since
# it's the one thing that would actually be annoying if it broke.

_organs_sensei_watcher="${SENSEI_SHELL_WATCHER_PATH:-/srv/organs/sensei/watchers/shell_watcher.py}"

_organs_sensei_capture() {
    # Skip if the watcher script isn't actually there — e.g. this
    # hook got sourced on a box where Sensei isn't installed yet.
    [ -f "$_organs_sensei_watcher" ] || return 0

    local cmd
    cmd="$(HISTTIMEFORMAT= history 1 | sed 's/^[[:space:]]*[0-9]*[[:space:]]*//')"

    # Only fire on a genuinely new command, not every prompt redraw
    # (PROMPT_COMMAND can run more than once per command in some setups).
    if [ "$cmd" != "$_organs_sensei_last_cmd" ]; then
        _organs_sensei_last_cmd="$cmd"
        ( python3 "$_organs_sensei_watcher" "$cmd" "$PWD" >/dev/null 2>&1 & )
    fi
}

if [[ "$PROMPT_COMMAND" != *_organs_sensei_capture* ]]; then
    PROMPT_COMMAND="_organs_sensei_capture${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
fi
