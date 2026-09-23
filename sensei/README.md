# Sensei

Digital Sensei's real skeleton, built on `organ_base.py` like every other
organ: registry discovery, `/health`, `/info`, standard error envelope,
BUS events, fire-and-forget writes into Memory.

## What's here

The **mode toggle and nudge pipeline**, plus two real detectors:
`shell_detector.py` (repeated command chains) and `editor_detector.py`
(undo storms). Writing detection is still future work. `/sensei/nudge`
remains the general landing point any detector calls, and that endpoint
already enforces the one rule that had to be right from day one:

**Mode is checked once, at the moment a nudge is generated — not at
delivery.** A nudge generated while "watching" is recorded as suppressed
and is never queued to fire later. Flipping to "ready" does not release
a backlog. See the docstring at the top of `sensei_core.py` and the test
`test_suppressed_nudges_never_batch_deliver_on_unmute` in
`tests/test_core.py` for exactly what that guarantees.

## Two modes, not four

- `watching` — default on every boot. Observes, never interrupts.
- `ready` — observes and is allowed to surface nudges.

No "off" mode. The service is always running, like every other organ —
what changes is whether it's allowed to talk to you, not whether it
exists. "Leave me to my work" is `watching`; "I'm ready to be helped"
is `ready`.

## Toggling it

Three ways in, same one endpoint underneath (`POST /sensei/mode`):

- CLI: `sensei ready` / `sensei mute` / `sensei status`
  (`sensei_cli.py` — put it on PATH as `sensei`)
- TUI: a keybind in `organs_tui.py` hitting the same endpoint
  (not wired up in this pass — the CLI script is the reference client)
- Hotkey daemon: bind a key in your WM/DE to run `sensei mute` /
  `sensei ready` — this is the one you'd actually use mid-task without
  switching windows

## Nudge delivery

`ready`-mode nudges fire as a desktop toast via `notify-send`. If
`notify-send` isn't on PATH (headless box, no DE), it logs instead of
crashing.

## Run it

```
pip install fastapi uvicorn requests --break-system-packages
uvicorn main:app --host 127.0.0.1 --port 8012
```

## Endpoints

- `GET  /sensei/status` — current mode, nudge count, last nudge time
- `POST /sensei/mode`   — `{"mode": "watching" | "ready"}`
- `POST /sensei/nudge`  — `{"kind", "message", "source"}` — called by
  detectors; suppressed or delivered depending on current mode
- `POST /sensei/detect/shell` — `{"commands": [...]}` — chronological,
  oldest-first shell history. Runs `shell_detector.find_repeated_chains`
  and routes any new candidate chain through the same `/sensei/nudge`
  gate. Chains already suggested before are skipped (`seen_chains.json`),
  so a watcher can re-scan the same rolling window on every tick without
  re-nudging about a pattern that's still there.
- `POST /sensei/detect/editor` — `{"events": [{"type","ts","file"}, ...]}`
  — chronological, oldest-first editor events. Runs
  `editor_detector.find_undo_storms` and routes any new storm through
  the same gate, same dedup convention (a storm is keyed by
  file+start_ts+count, so a genuinely new storm later still nudges, but
  a re-scan of the same window doesn't repeat one already flagged).
- `POST /sensei/respond` — `{"nudge_ts", "accepted"}` — records
  acceptance/rejection, writes a tagged low-confidence entry to Memory
- `GET  /sensei/history` — `?n=20&delivered_only=false`

## The shell detector

`shell_detector.py` is pure and stateless: given a list of recent shell
commands, it finds any CONTIGUOUS block of 2–4 commands that recurs
verbatim at least 3 times, and drops shorter redundant sub-chains already
covered by a longer match it also found (e.g. won't separately nudge
about `git add . / git commit` once `git add . / git commit / git push`
has already been flagged as a 3-chain). `main.py`'s `/sensei/detect/shell`
endpoint is the only thing that wires it to real state (dedup) and real
delivery (`op_nudge`).

`shell_watcher.sh` is the actual Observe half — a real script for a real
`.bashrc`/`.zshrc` (or a cron/systemd timer) that reads your real shell
history and POSTs it there. See the script's own header for install
steps. It fails silently and never blocks your shell if Sensei isn't
reachable, same fire-and-forget convention as everything else here.

## The editor detector

`editor_detector.py` is the same shape: pure, stateless, given a list of
`{"type", "ts", "file"}` events it finds a run of consecutive `"undo"`
events (any other event type breaks the run) whose count reaches 4 and
whose total time span is within 30 seconds — a burst, not just "undid a
few things over the course of an afternoon." Storms on different files
don't merge.

**No real watcher ships for this one yet.** Unlike the shell hook, there
isn't a single generic, verified way to get "on undo" events out of an
arbitrary editor — it depends entirely on which editor you use and what
its plugin/keybinding system supports, and getting that wrong here would
mean shipping install instructions that don't actually work. The
endpoint itself is fully real and fully tested (unit, API, and live
cross-organ — see Testing below); wiring a specific editor to it is the
one piece of this pass that needs your own hands on your own machine.

## Testing

Everything in this repo runs and is verified as part of building it —
`./run_all_tests.sh` from the `organs/` root covers every organ
(including Sensei's 63 tests) plus `live_integration/`'s real
cross-organ HTTP tests. None of that requires anything from you.

**The one thing that can't be tested without your actual machine:**
whichever editor hook you wire to `POST /sensei/detect/editor`. To check
it for real:

1. Run Sensei for real: `uvicorn main:app --host 127.0.0.1 --port 8012`
   from this directory (plus Registry/Critic/Communications/Memory if
   you want nudges to actually reach the bus/Memory too — Sensei itself
   will just log a quiet warning and keep working if they're not up).
2. `sensei ready` (via `sensei_cli.py`) so nudges actually surface.
3. Trigger your editor hook enough times to produce ≥4 undos within 30
   seconds on one file, however you've wired it to call
   `POST /sensei/detect/editor` with those events.
4. You should see a desktop toast via `notify-send` (or, headless, a log
   line: `[sensei nudge] ...`). `curl localhost:8012/sensei/history` also
   shows it landed.

If you want, tell me what editor you actually use and I'll write the
specific hook for it next, rather than guessing at one now.

## Not built yet

Writing detectors — the last third of the Observe → Detect → Nudge loop
from `Digital_Sensei.md` (drift/thesis hints, rewrite patterns). Should
follow the same shape as the two detectors above: a pure, testable
detection function, plus a small endpoint that dedupes and routes into
`op_nudge`. See `live_integration/test_sensei_cross_organ.py`'s
`test_shell_detector_end_to_end_...` and
`test_editor_detector_end_to_end_...` for what "proven end to end"
looks like for a detector in this codebase.
