# Dev Notes

Context that doesn't belong in `README.md` (which describes current state)
or `CANON.md` (which is permanent rules), but that whoever touches this
codebase next — including future-you — will want. Grouped by organ, in
build order, plus a running list of bugs actually caught and what caught
them.

## Why this file exists

`README.md` will always tell you *what an organ does right now*.
`CANON.md` tells you *what's never allowed to change*. Neither one tells
you *why a specific line of code looks the way it does*, or *what almost
went wrong*. That's this file's job. If you fix a bug that took real
effort to track down, or make a decision you'd want explained to yourself
in six months, it goes here.

---

## The pattern: mocks that quietly diverge from reality

This is the single most repeated lesson across this codebase's build
history, and it's worth stating once here instead of scattered:

**A green test suite proves the mock was self-consistent. It does not
prove the mock matched the real thing.**

Two concrete cases, both caught by actually running the real, unmocked
code path against a real (if imperfect) environment:

- **Sandbox** (`_run()`) originally *raised* when Docker wasn't installed,
  instead of returning the clean result-shape every other organ's `_run()`
  returns on failure. The mocked "Docker unavailable" test passed —
  because the fake simulated a return value the real function never
  actually produced. A live run against a genuinely Docker-less
  environment crashed instead of failing cleanly, caught it immediately.
  Fixed, and a second test was added that calls the *real* function
  against a real Docker-less environment specifically so this class of bug
  can't silently pass again.
- **Introspection**'s disk collector doesn't filter FUSE-backed network
  mounts. Found live, not in a test — a virtual filesystem in the build
  sandbox reported an absurd multi-petabyte size. Left unfiltered on
  purpose rather than over-fit to one sandbox's quirks — but it's a real,
  standing example of why `df` output needs a skeptical reader.
- **Reflection**'s background loop originally `sleep()`d for the
  *currently configured* interval — read once at startup, which defaults
  to 300s before you've ever had a chance to enable anything. Flipping the
  toggle on right after boot wouldn't take effect for up to five minutes.
  A live test (enable, wait 13s, expect a run, get none) caught it — not a
  code read, an actual run that came back empty when it shouldn't have.
  Fixed by splitting poll rate (checks the toggle every 5s) from tick rate
  (only runs when the real interval has elapsed).
- **Introspection**'s Ollama collector originally dropped the unit off
  every model's size (`"4.9"` instead of `"4.9 GB"`). `ollama list`'s SIZE
  column is itself two space-separated tokens, and the parser split on
  plain whitespace, grabbing only the number. A same-shaped synthetic test
  string didn't catch it because it wasn't padded the way real column
  output actually is. A live run against Bucky's real `ollama list` (23
  real models) surfaced it immediately. Fixed by splitting on runs of 2+
  spaces (`\s{2,}`) instead of any whitespace — real column boundaries are
  multi-space, a unit's internal single space isn't.
- **Sandbox**'s `_run()` had a second gap past the one below: it only
  caught `FileNotFoundError` for "docker isn't usable," not
  `PermissionError` (docker present on disk but not executable — a
  mounted binary without +x, a locked-down environment). Not
  reproducible in the environment this organ was originally built in (no
  docker at all there, so only `FileNotFoundError` ever fired) — caught by
  an external review running the suite somewhere docker exists but isn't
  executable. Now both exceptions are caught the same way, reported the
  same clean way.
- **I/O Interface**'s `orchestrator_status` pattern matched `is` with no
  word boundary, so **"run this python code: ..."** matched **"is
  python"** *inside* the word "th*is*" — misrouting a sandbox request to
  a status check on a service literally named "python." Caught by the
  test suite itself (not a live run this time) once a real phrasing was
  tested instead of only the intended-to-match cases. Fixed with a proper
  `\b` boundary; a regression test locks in the distinction — "is"
  embedded inside another word must never match, "is" as its own genuine
  word still correctly can.

**Standing rule**: any organ whose job is to truthfully report on
something real — a subprocess, a filesystem, a dependency's live status —
needs at least one test that exercises the real, unmocked path, even in an
environment where the happy path doesn't hold.

One more instance, funnier than the rest for being self-referential: the
regression test for the `FileNotFoundError` bug above originally asserted
the exact string `"not found"` in `_run()`'s error output — which
hardcoded an assumption about *which* real failure mode the test's own
environment would produce. An external review ran it somewhere `docker`
exists but isn't executable (`PermissionError`, not
`FileNotFoundError`) — a real, different, both-real environment — and the
test failed, not because the code was wrong, but because a "real,
unmocked path" test had quietly baked in an environmental assumption of
its own. Fixed to accept either real failure text, asserting only the
thing that actually matters: `_run()` never raises, always returns the
documented tuple, regardless of *which* way Docker happens to be
unavailable. A live/unmocked test is only as honest as what it actually
asserts — "call the real thing" isn't automatically immune to the same
disease it exists to catch.

---

## Registry

Was the one organ with no test suite — the highest-priority gap in the
codebase, confirmed still real by a direct external review of the
archive before it got closed. Now has 29 tests covering every Section 1
non-negotiable that actually lives in `registry_core.py`.

Worth noting for anyone touching this organ again: `registry_core.py`
loads its snapshot *eagerly*, at module import time, unlike every other
organ's core module (which load lazily, inside functions, the first time
something actually needs the data). That's why its test fixture isolates
`REGISTRY_DATA_DIR` *before* importing the module, not after — importing
it late (or reloading it) is what actually re-triggers the snapshot load
against the fresh test directory. A test written the way every other
organ's tests are structured would silently load the real, non-test
data directory instead.

One test worth calling out specifically, since it's the direct proof of
Section 1 item 4's crash/shutdown-parity claim rather than just testing
around the edges of it:
`test_crash_and_clean_shutdown_are_indistinguishable` simulates a crash
(an organ's heartbeat just stops arriving, nothing calls deregister) and
confirms there's no special "crashed" state anywhere in a stale organ's
record — the exact same staleness mechanism that would also describe a
merely-slow heartbeat. That's the actual guarantee, proven directly
rather than inferred from reading the code.

A staleness-boundary test also surfaced a small, instructive timing
lesson: an "exactly at the threshold" test is structurally impossible to
write reliably against real wall-clock time, since `get()` calls
`time.time()` itself, fractionally later than whatever the test's own
`now` captured earlier — time only ever moves forward between those two
calls. Landing safely inside the boundary (a fraction of a second of
margin) tests the real guarantee without depending on sub-millisecond
precision that was never actually being claimed.

## Memory (first organ built to completion, v0.3.0)

Proof the "build to completion" rule holds — GOAL.md's original question
set turned into fields on existing records rather than 21 separate
subsystems. Layers: ledger (permanent) → entries (searchable, salience-
scored) → archived (forgetting ≠ deletion) → facts/scars (propose →
decide → canon) → promises/unknowable/relations (structured state, one
edge table connects any two record kinds).

Worth being precise about that last group: promises and relations resolve
through a single `op_resolve_promise`/`op_resolve_relation` call, not a
separate propose-then-decide *pair* the way facts and scars actually have
one (`op_propose_scar` + `op_decide_scar`, consolidate + decide for
facts). The guarantee CANON.md cares about — nothing becomes permanent
without an explicit human call — holds for all four either way; "propose
→ decide" is just a more specific mechanism than promises/relations
literally use. Don't assume there's a `proposed_promises.jsonl`-shaped
file lying around — there isn't.

Relations, bus-integration, and a migration path were added after the
organ's initial "complete" milestone — a reminder that "complete" for v1
doesn't mean "never touched again," it means the next addition still goes
through the same discipline (tests before/with the code, not after).

## Communications (v0.1.0)

Bus (broadcast, pull-based, per-consumer cursors) and Dispatch
(round_robin/random/broadcast, generalized from an earlier `group_chat.py`
pattern) share one store but solve different problems.

**No longer true, and worth correcting since an earlier pass of this file
said otherwise: Memory DOES publish to the bus now.** Five real event
types, wired into `memory/main.py`: `fact_added`, `scar_added` /
`scar_superseded`, `promise_resolved`, `unknowable_resolved`,
`relation_resolved`. Covered by nine dedicated tests
(`test_bus_integration.py`) and proven live — a real scar accepted in
Memory landed on the real bus for a separate consumer to pick up, in the
same session Executive/Critic/I/O Interface later got built. What's still
genuinely true: nothing *subscribes* to any of these topics yet. The bus
carries real traffic; nothing's listening for it. That's the actual next
gap here, not "nothing publishes."

## Orchestrator (v0.1.0)

Deliberately can't run arbitrary commands — `services.json` is a fixed,
human-edited allowlist, and the API surface only ever means "start/stop/
status THIS named service." The `sudo -n` non-interactive check for
system-scope services (`ollama.service`) was a specific choice: fail fast
and clearly rather than hang a request on a password prompt nobody's there
to answer.

This WAS live-verified for real on the actual host, and it surfaced a
genuinely nasty gotcha worth remembering: the scoped sudoers rule
(`/etc/sudoers.d/organs-orchestrator`) has to be **exactly mode 0440**.
It was created at 0640 (owner read/write, group read) — one extra bit —
and `sudo` silently refused to trust the file rather than erroring
loudly. `sudo -n systemctl stop ollama.service` just failed with the
normal "needs a password" message, giving zero indication the actual
problem was file permissions, not a missing rule. `sudo visudo -c` and a
direct `ls -l` on the file (not just its existence) were what actually
found it. Fixed with `chmod 0440`; a live Executive goal afterward
genuinely restarted Ollama end to end — approved, executed, `"success":
true"`. Worth checking permissions with `ls -l`, not just existence, if
this ever silently "doesn't work" again on a fresh host.

## Reflection (v0.1.0)

"Old man muttering" — periodic, low-confidence, self-authored Memory
writes (`provenance: "self"`, `confidence: 0.3`), never answers anyone,
nothing waits on it. OFF by default is the entire safety story:
`state.json` starts `enabled: false`, and the systemd unit *running* is
explicitly not the same thing as it *thinking*. See the sleep()-interval
bug above if touching the loop's timing logic again.

## Introspection (v0.1.0)

A deliberately small slice of the original 13-phase `DEEPSCAN_ROADMAP.md`
plan — GPU details, security surface, storage forensics, and the full
knowledge graph are unbuilt *on purpose*, not forgotten. The core
distinction from the old `deepscan.sh` shell script: that was a report you
generated once and read; this is queryable live by any other organ. See
the FUSE-mount disk-size bug and the Ollama size-unit bug above before
trusting collector output blindly on an unfamiliar host — both were real,
both were only caught by a live run against a real machine.

## Sandbox (v0.1.0)

Containment, not review, is the safety property — see `CANON.md` Section
3. Every safety guarantee (path traversal rejected, network off unless
requested, resource limits present in the actual constructed Docker
command, workspace destroyed in all three outcomes) has its own direct
test, not just "the suite passes." See both `_run()` bugs above — the
canonical example in this codebase of a mock silently diverging from
reality, twice, in two different ways nobody's own build environment
happened to reproduce.

## Critic (v0.1.0)

Deterministic on purpose — a rule table, not an LLM, specifically so it
can't be talked into approving something by clever phrasing, doesn't
degrade under load, and its full reasoning is inspectable via `GET
/critic/rules` rather than trusted blindly. Four tiers (`safe`,
`reversible`, `caution`, `high_risk`); rule order matters, first match
wins, and the *last* rule is always "anything unrecognized →
`high_risk`" — the fail-closed default isn't a fallback bolted on, it's
structurally the final line of the table. Stateless: every call is
independent, evaluates only what's *about* to happen, never sees history.

If you add a new organ or endpoint that Executive or I/O Interface should
be able to call, **it needs a rule added here explicitly** — otherwise it
silently falls through to `high_risk`, which is safe-by-default but will
be confusing if you forget this step and wonder why a new safe action
keeps demanding approval.

## Executive (v0.1.0) — undocumented until this pass

The first organ that can chain actions across others on its own, and
correspondingly the most conservative. No autonomous LLM planning — a
human or another process submits an explicit, ordered step list, and every
step is classified by the *real* Critic at submission time (not execution
time), so a plan's full risk profile is visible before anything runs.
`op_execute_next_step` runs exactly one step per call; a failed step stops
the goal rather than cascading silently past it. Same dependency-injection
pattern as Reflection: `evaluate_risk` and `execute_call` are both
injected, so the state machine (ordering, gating, failure handling) is
fully tested without a real network — `main.py` supplies the real
implementations (real Critic call, real registry-discovered target call).

## I/O Interface (v0.1.0) — undocumented until this pass

The real front door, and deliberately narrow: a fixed, ordered pattern
catalog (`CATALOG` in `io_interface_core.py`), first-match-wins, same
shape as Critic's rule table. Not an LLM freely inventing API calls, for
the same reason Executive doesn't do autonomous planning — an 8B local
model guessing at arbitrary calls from a sentence was judged too risky to
promise. If nothing matches, it says so and lists what it *does*
understand, rather than guessing. Every interpreted action still goes
through the real Critic (`_evaluate_risk`) and, if flagged, creates a
*real* Executive goal (`_create_gated_goal`) rather than a shortcut —
routing "the request arrived as English instead of curl" around the
approval gate was explicitly rejected as a design.

Adding a new phrase to the catalog is low-risk by itself (it's just
pattern-matching to an existing organ/endpoint pair), but the endpoint it
routes to still needs a Critic rule — see Critic's note above.

---

## Before adding the next organ

The three-organ jump (Critic → Executive → I/O Interface) closed the loop
this system was originally missing: a way to *act*, gated by a way to
*judge* whether acting is safe. Whether there's a genuinely necessary
fourth piece, or whether what exists now is actually the complete set, is
worth re-checking the same way GOAL.md's original scope got checked before
Memory was built — by asking "is that really the last one," not assuming
it. That question, plus the Registry test-gap noted above, were the two
open items this file knew about as of that pass.

**Update, one pass later:** a full external review of the archive (not
just the README — unpacked, tests run independently, service layer
checked) confirmed the Registry gap was still real at that point, and
caught two things this file hadn't: Sandbox's `_run()` had a second
uncaught exception type (`PermissionError`, alongside the original
`FileNotFoundError`), and running the whole repo's tests in one `pytest`
invocation collides — every organ has a file called `main.py`, and
Python's `sys.modules` cache means the second organ's `import main`
silently returns the first organ's already-loaded module instead of
loading its own. Not a bug to patch — it's the "no monorepo, no shared
venv" principle from day one, correctly preventing false coexistence,
just never stress-tested against a unified test run before. Fixed with
`run_all_tests.sh` (each organ in its own subprocess, matching how they
actually deploy) rather than forcing shared process state for the sake
of test convenience.

**Update, same session, right after that:** Registry got its 29 tests —
see the Registry section above. `run_all_tests.sh` now includes it (it
had been left out of the organ list the first time the script was
written, an omission the aggregate run itself couldn't catch since it
just silently ran the organs that WERE listed). All ten organs, one
command: 302 passing.

**Update, later pass — the Registry gap, actually closed this time:**
"302 passing" was true but hid a live wire. `organ_client.py` resolves
`ORGAN_REGISTRY_URL` into a module-level constant the FIRST time it's
imported in a process, and none of the nine non-Registry organs' test
suites ever set it — so on any machine where the real Registry happens
to be up on its default port (i.e. Bucky, running the actual system),
the first test in each organ's process would fall through to that
default and the app-startup heartbeat loop would register (and keep
heartbeating) fake test organs into the real production Registry.
`run_all_tests.sh`'s one-subprocess-per-organ isolation made this worse
to notice, not better — it's exactly what kept each organ's tests from
polluting each OTHER organ's in-memory state, so nothing ever looked
wrong locally; only a Registry that was already live on the shared
default port would show it, and only by growing entries nobody put
there.

Fixed by having every organ's `api_client` fixture pin
`ORGAN_REGISTRY_URL` to a guaranteed-dead address (`http://127.0.0.1:1`)
before `import main` ever runs — matching the project's existing
"env vars before the import that reads them" convention (see Registry's
own `rc`/`api_client` fixtures, which do the same thing for
`REGISTRY_DATA_DIR`). Registry itself doesn't import `organ_client` (it
IS the thing being discovered), so it never needed the fix. Verified by
standing up a throwaway HTTP listener on `127.0.0.1:8000` and running
each organ's suite against it directly — zero requests arrived. All 302
tests still pass.

**Update, first real install on mythos1:** the Registry-isolation fix
held — `install.sh`'s automated test run and the live production
Registry (organs already up for 2 days at that point) never touched
each other; `/registry/organs` after install still showed the same
`first_registered` timestamps from before the install ran. Caught one
unrelated real thing in the same pass: `sandbox`'s
`test_real_run_reports_missing_docker_without_raising` hardcoded
`rc == 127` (Docker entirely absent), which was true on the machine
Sandbox was originally built on and false on mythos1, where Sandbox is
actually meant to run real jobs and Docker is installed and working.
Fixed to assert what the test's own docstring already said mattered —
`_run()` never raises, and its return shape agrees with whichever real
Docker state the environment actually has — rather than assuming one
specific state. Verified both branches: real environment here (Docker
absent, rc 127) and a faked working `docker` binary (rc 0). 302 passing
either way.

**Update, eleventh organ — Forge:** built as a direct, single-shot HTTP
organ (spec in, code out, optionally validated against the real
Sandbox) rather than the fuller telemetry/context-broker-backed
pipeline a later external roadmap review sketched — that review's own
stated development order puts Telemetry, State, and a Context Broker
ahead of Code Forge, for the same reason akasha-llm-orchestrator and
akasha-forge were judged to have failed: a model coding "blind," with
no observation layer and everything held in its own context. Building
Forge now, before that foundation exists, is a known, named deviation
from that review's advice — not an oversight. Whether that foundation
still gets built is an open decision, not a settled one.

Two external dependencies, two different existing conventions, matched
deliberately: Ollama is a raw network dependency, so `ollama_generate`
follows Memory's pattern (top-level function in `forge_core.py`, faked
directly in tests, real in main.py, always). Sandbox is another organ,
so validating generated code follows Executive's pattern instead —
`run_sandbox_call` injected into `op_build()`, real implementation
(`discover("sandbox")` + the actual call) living in `main.py`. Picking
one pattern for both would have been simpler and would have been wrong
— they're genuinely different kinds of dependency.

Forge's workspace is deliberately PERSISTENT, the one place this organ
inverts Sandbox's own convention on purpose. Sandbox's docstring already
named Forge as the reason it exists ("the piece the future code forge
needs to actually execute what it writes") and destroys its workspace
after every job because Sandbox's output is disposable. Forge's output
*is* the deliverable — nothing here auto-deletes it; `DELETE
/forge/jobs/{id}` is a human decision, same hard-veto spine as
gapforge/pipeline_guard/the gig intake pipeline. No commit, merge,
publish, or deploy verb exists anywhere in this organ.

Shipped with the same test-discipline item that got Sandbox bitten
twice and flagged Orchestrator as still missing one: one test
(`test_real_ollama_generate_survives_whatever_this_environment_has`)
calls the real, unmocked `ollama_generate` against whatever's actually
on the machine — a clean `ForgeError` here (no Ollama in this repo's
CI), real generated text on Bucky. 27 new tests, 329 passing across all
eleven organs.

**Update, twelfth organ — Telemetry, and the actual build-order call:**
Jimmy specifically wanted Telemetry and Temporal reasoning (and, this
same pass, a TUI) — none of which were on record here before a
ChatGPT-authored roadmap review surfaced them by name. Its own stated
development order put seven other things ahead of Forge, including
Telemetry; Forge got built first anyway, as a deliberate, named
deviation (see the Forge entry above). Jimmy then made explicit that
the roadmap doc was shown for the organ ideas it contained, not its
ordering, and handed build-order judgment to Claude as builder, second
call after his own.

Call made: **Telemetry, then TUI, then Temporal, one at a time.**
Reasoning — Telemetry has no dependencies of its own, so it's free to
build now. TUI needs real events to show; building it before Telemetry
existed would mean either faking a "recent activity" view or shipping
an empty one, directly undoing the no-sim/no-stub discipline Forge was
just built under. Temporal is the biggest and riskiest of the three —
it's not a new organ, it's reopening Memory, which is finished,
versioned, and has 66 tests already depending on its current schema —
and reasoning about time is more grounded with a real event timeline
to anchor "before/after/caused" relations to than designed in the
abstract first.

Storage deliberately mirrors Memory's own jsonl+sqlite pattern rather
than inventing a new one — permanent append-only `telemetry.jsonl`,
queryable `telemetry.sqlite3` index. Every event carries two clocks on
purpose: `timestamp` (wall-clock) and `monotonic_time`
(`time.monotonic()`), because wall-clock subtraction across two events
is not a reliable duration — a caller supplies `duration_ms` directly
when it measured its own operation; Telemetry never reconstructs one
from two timestamps itself. `event_id` is always server-assigned, never
trusted from a caller, so two organs emitting concurrently can never
collide. `correlation_id` threads one externally-initiated operation
into a reconstructable causal chain; `GET /telemetry/timeline` is the
concrete answer to "what actually happened for request X, in order."

Telemetry is the recorder and query surface only — nothing calls it
yet. Instrumenting the other eleven organs to actually emit events on
their own requests, mutations, and failures is real, separate work,
deliberately not done in this same pass (touching eleven already-
finished organs' main.py files is its own project, not a drive-by).
29 new tests, 358 passing across all twelve organs.

**Update, first real Forge run on mythos1 — caught live, on the first
try:** the organ's own live-Ollama test is exactly what it was built to
be. Ollama was reached (connection succeeded, mythos1 does have it
running) but generation didn't finish inside the test's 5s timeout —
almost certainly a cold model load, the first call after Ollama starts
or after the model's been idle. `ollama_generate` only caught
`urllib.error.URLError`, which wraps CONNECT-phase failures; a timeout
while reading the response is a raw `TimeoutError` outside that
wrapping entirely, and escaped uncaught — the exact "raw exception,
not a clean ForgeError" outcome the test's own docstring says is the
one unacceptable result. Fixed by catching `OSError` broadly (`URLError`
is itself an `OSError` subclass, so this is strictly broader) with a
message that distinguishes "couldn't reach it" from "reached it, too
slow" — the second one now suggests retrying or raising
`FORGE_GENERATE_TIMEOUT`, since that's actually actionable and
"connection refused" isn't the right advice for a slow-but-working
server. Test timeout bumped from 5s to 20s to give a real cold-start
call a fair chance without leaving CI hanging when Ollama's genuinely
absent (that path still fails in milliseconds regardless of the timeout
value). Added a synthetic slow-server test as a permanent regression
test, rather than depending on a live Ollama being slow to catch this
again. Logged as the 5th documented instance of CONTRIBUTING.md's
"mock diverges from reality" bug class — 359 passing across all twelve
organs.

**Update, same first real Forge run — a second, quieter bug found in
the same response:** the generated test file never imported
`solution.py`. It redefined its own copy of the target function under a
different name and tested that instead — a green test suite (had
pytest been installed) that would have validated nothing about the
real deliverable. Root cause: `op_build` made two INDEPENDENT
`ollama_generate` calls — implementation, then tests — each derived
only from English spec text, with zero coordination between them. The
model writing the test genuinely had no way to know what the real
implementation ended up being named. Fixed by including the actual
generated `impl_code` in the test-generation prompt, with an explicit
instruction not to reimplement or redefine anything from it. Verified
with a test that captures the real prompt text sent to the second
`ollama_generate` call and asserts the first call's real output
actually appears inside it — proving the coordination happened, not
just that both calls were made.

Also added `network` (default `False`, matching Sandbox's own default)
end to end — `BuildRequest` → `op_build` → `run_sandbox_call` → the
real Sandbox HTTP call — since the base test images have no test
framework preinstalled and there was previously no way to opt a build
into `pip install`-ing one. Never auto-enabled; an explicit per-build
choice, same hard-veto discipline as everything else in this organ.

Neither of these was a "mock diverges from reality" bug in
CONTRIBUTING.md's specific sense — there's no fake standing in for
Ollama here, both calls were real. It's a different, related failure:
two real, independent calls to the same real dependency, silently
diverging from EACH OTHER for lack of any shared context. Worth its own
line rather than folding it into that list under a label that doesn't
quite fit. 30 tests in forge now (was 27), 361 passing across all
twelve organs.

**Update, the real reason the last two "fixes" looked like they didn't
work:** they did — `forge_core.py` on disk had both fixes the whole
time. `install.sh` copies files and runs tests; it never restarts an
already-running systemd service. `organs-forge` was already running on
mythos1 from the earlier `install_systemd.sh` pass, so uvicorn kept
executing whatever it had loaded into memory at its last start — file
changes on disk are invisible to a running Python process until it
restarts. Confirmed by the exact symptom repeating identically across
two "reinstalls": same `sum_numbers`, same `network_enabled: false`,
because it was never re-running the new code at all, just re-serving
the same old process.

`install.sh` now detects this instead of leaving it a silent trap:
after copying files and running tests, it checks `systemctl --user
is-active` for all twelve organ services and — only for the ones
actually running — prints the exact `systemctl --user restart ...`
command needed, right after "Done", before any other hint text.
Verified both ways: with organs-forge/organs-telemetry reported as
active (prints the exact restart line, correct names) and with nothing
running (prints nothing, no false-positive noise on a first-time
install where systemd isn't set up yet).

**Update, TUI — the first tool, not organ, in this repo:** landed after
Telemetry per the build order named in the Forge/Telemetry entries
above. Deliberately NOT organ #13 — it provides no HTTP capability,
nothing calls it, and it doesn't register with the Registry. It's the
first thing in this whole system that only consumes.

Same core-vs-thin-interface split every organ already has, applied to a
client for the first time: `tui_data.py` makes every real HTTP call
(discovering base URLs through the real Registry — same discovery path
an organ uses to find another organ) and is independently testable —
17 tests, zero curses imports in the file at all. `organs_tui.py` is
deliberately dumb: it only formats and draws whatever `tui_data.py`
already fetched, no retry logic or fallback data of its own that could
make a panel look more complete than reality. curses itself isn't
meaningfully unit-testable (needs a real terminal), so its 27 render
tests instead exercise every one of the 7 panel-drawing functions
against a fake window object with three real data shapes — fully
healthy, every organ returning an error, every organ present but
empty — proving one organ being down can never take the rest of the
dashboard with it. Same resilience discipline as every organ's own
health checks, applied for the first time to something that isn't a
health check.

Zero new dependencies — `curses` is stdlib, `requirements.txt` didn't
need to grow for a TUI, which wasn't a given going in.

Confirmed exact real route paths for all twelve organs before writing a
single panel (grepped every `main.py` for its actual `@app.get`/`@app.post`
paths rather than reasoning from memory) — guessing one wrong would
have meant shipping a dashboard that silently showed nothing for part
of the system, exactly the class of thing this whole session has been
about not doing.

`run_all_tests.sh` gained a second loop (`TOOLS=(tui)`, separate from
`ORGANS=(...)`) rather than folding `tui` into the organ list — the
distinction is real, not pedantic, and the script's own job is to be
accurate about what it's running. 44 new tests, 405 passing across all
twelve organs and one tool.

Named right after this: Jimmy noted "Organs" is straining as a name now
that it covers a code forge, an observation layer, and a terminal
dashboard, not just ten small HTTP services. Open, not yet decided —
flagged here so it isn't lost, not treated as blocking anything above.

**Update, first real TUI session on mythos1 — caught a real bug in the
TUI itself, on the Forge tab:** every job's TESTS column showed `-`,
even for jobs that genuinely had `test_command` set (the pytest-not-
installed and pytest-actually-passed runs from Forge's own first real
session). Root cause: `draw_forge` checked `job.get("test_command")` —
a field `GET /forge/jobs` never actually included. `op_list_jobs`
returns a fixed projection of each ledger entry (`job_id, created,
language, model, files, deleted, sandbox_result`), and `test_command`
was never in that list — only the single-job detail endpoint
(`op_get_job`) carries the full manifest. This is exactly the kind of
gap the "confirm exact real route paths before writing a single panel"
step earlier in this file was meant to catch, and didn't — checking the
route existed wasn't the same as checking every field a panel reads
actually appears in that route's real response shape.

Fixed on both ends: `op_list_jobs` now includes `test_command` too (a
real, small API completeness fix — a plain `curl /forge/jobs` was
missing the same information), and `draw_forge` was changed to key off
`sandbox_result` being present rather than `test_command`, since that's
the more direct signal for "were tests actually attempted" and doesn't
depend on which fields a future summary projection happens to include.
Added a render test that checks the actual rendered TEXT per row (not
just "didn't crash") — `abc123`'s row must contain "passed", `def456`'s
row must contain "-" and must NOT contain "passed", proving the
distinction the original bug silently erased. 407 passing across all
twelve organs and the tool.

**Update, TUI's Input tab — the first side-effecting panel:** everything
else in the TUI is read-only; this one can act. Wired straight to the
real I/O Interface organ's existing `/io/handle` (plain text) and
`/io/interpret` (`?`-prefixed dry run) — deliberately zero new gating
logic in the TUI itself. `io_interface` already routes everything
through the real Critic and gates anything risky behind a real
Executive goal; a human typing directly into a live terminal already
IS the human-approval step, and reimplementing any part of that gate
here would be exactly the "don't build a second opinion, call the real
thing" mistake CONTRIBUTING.md's reuse rule already warns against.
Added `_post` to `tui_data.py` (mirrors `_get`'s never-raises
discipline, surfaces an organ's real structured error envelope on an
HTTPError instead of just the HTTP status) and `base_urls_from_registry`
as a public wrapper so the Input panel can look up `io_interface`'s
base_url on demand at submit time, not just inside the periodic
`fetch_all` snapshot. Navigation had to change to avoid a real
collision: 1-8 and `q` are valid characters to type, so they're only
tab-switch shortcuts outside the Input tab; PageUp/PageDown work as
tab-switches from anywhere, including mid-typing, since those keys
never collide with real input. 26 data-layer tests, 39 render tests now
(was 17/27) — the new ones include `_summarize_io_response` against
every real response shape `/io/handle`/`/io/interpret` actually
produce (matched-and-executed, matched-and-gated, unmatched, error),
not invented ones.

**Update, a real and serious bug — the `main.py` collision, confirmed
live, not theoretical:** `pytest.ini` already carried
`--import-mode=importlib`, added for a DIFFERENT collision (pytest's
own test-file identification, e.g. `memory/tests/test_api.py` vs
`orchestrator/tests/test_api.py` both wanting to register as module
`test_api`). Its own comment already said what it didn't cover: each
organ's `conftest.py` does a plain `import main` — ordinary Python
import machinery, untouched by pytest's import-mode setting. Reproduced
directly: `pytest memory/tests/test_api.py forge/tests/test_api.py` in
one process produces ten of memory's tests failing with 404s and
KeyErrors — not because anything is broken, but because memory's
fixtures ran against forge's already-imported app. Worse than a crash:
looks exactly like a real bug, sends whoever hits it chasing the wrong
thing — which is exactly what happened before this got traced back
here. The existing `importlib.reload(main)` calls scattered across
several conftest.py files don't protect against this either — reload()
re-executes the CACHED module using its ORIGINAL file location, not
whichever organ is currently trying to import it.

Fixed with a root-level `conftest.py` — a deliberate tripwire, the only
file in this repo whose entire job is to refuse to run. Its
`pytest_collection_modifyitems` hook inspects what was actually
collected and, if it spans more than one organ/tool directory, calls
`pytest.exit()` before a single test executes — "no tests ran," not ten
confusing failures. Verified four ways: the exact scenario that broke
(`pytest memory/tests/... forge/tests/...`) now refuses immediately;
bare `pytest` from the repo root (collects all 427 items across twelve
organs and the tui tool) also refuses immediately, listing every organ
involved; every legitimate invocation — a single organ from the root
(`pytest memory/tests/`), `cd`'d into one organ (what
`run_all_tests.sh` actually does), and the `tui` tool on its own — all
still pass clean, same counts as before. `run_all_tests.sh` itself
re-verified end to end afterward: still exactly 427 passing, nothing
about legitimate usage changed.

**Update, a milestone, not a bug fix:** with this edit landed, Jimmy
called a temporary feature freeze — twelve organs and one tool is
"where he wants it" as a core. Next phase is explicitly integration and
hardening, not new organs: making the whole thing behave like one
closed system, one organism, rather than twelve services that happen
to coexist. The framing given: it should know exactly what it is and
every organ should function in sync before it grows again. Concretely,
that likely means: Telemetry actually gets called by the other eleven
(the deferred step named in its own section since it was built),
cross-organ integration tests (something no test suite here currently
does — every organ's tests are real but strictly single-organ), and
probably the rename this file already flagged, since "Organs" was
already straining before this phase even started. Recorded here so the
next session opens knowing this is the current mandate, not "what
organ should I build next."


**Update, first organism-integration pass — Telemetry is now actually in the bloodstream:**

The feature-freeze mandate has begun with the first connection whose intended
behavior was already explicit in the existing documentation: Telemetry's README
said the other organs should emit their own requests, mutations, and failures,
and `organ_base.py` is already the system-wide convention every organ inherits.
Rather than touching twelve `main.py` files individually, the integration is
therefore implemented once in that existing shared boundary. A new small
`shared/telemetry_client.py` contains only the discovery-and-emit plumbing; it
finds Telemetry through the Registry and treats observation as best-effort.

Every organ built on `organ_base.py` now automatically records non-diagnostic
HTTP activity: GET/HEAD-style reads as `request`, POST/PUT/PATCH/DELETE as
`mutation`, and HTTP failures as `failure`. The event records the organ, path,
method, response status, duration, and correlation ID. An incoming
`X-Correlation-ID` is preserved; otherwise the boundary creates one and returns
it in the response. Health and info are deliberately excluded because they are
diagnostic/discovery surfaces rather than organism activity, and Telemetry does
not observe itself. Internal telemetry traffic is marked so the Registry cannot
form a recursive observation loop while Telemetry is being discovered or written.

This also exposed a real hardening bug in the existing Registry convention:
`register()` did not translate a raw `TimeoutError` into `RegistryError`, so a
slow Registry could kill the organ's heartbeat task instead of producing the
documented retry behavior. That is now caught alongside the existing URL/HTTP
errors, with a regression test.

The integration was tested at three levels: shared convention tests, the full
existing organ/tool suites, and a live HTTP probe through a real Registry and
Telemetry service. The live probe produced a real `mutation` event with the
caller-supplied correlation ID, proving the path is not merely mocked. Current
test total: **434 passing** (427 existing + 7 shared integration/convention
tests).

One important boundary remains deliberately untouched: Communications has a
real publisher (Memory) and a real pull-based consumer API, but no existing
Canon/API/Dev Note specifies which organ should consume which Memory topic.
No subscriber has been invented in this pass. That is an explicit **ASK** item,
not a missing feature to guess at.

The next technically grounded tightening is correlation propagation through
existing organ-to-organ HTTP calls. That is already promised by Telemetry's
`correlation_id`/timeline model, but the existing callers do not consistently
forward the originating ID. No new organ or new architectural channel is needed
for that work.

### Correlation propagation through the existing HTTP spine

The shared HTTP convention now keeps the incoming `X-Correlation-ID` in a
request-scoped context while an organ endpoint is executing. Existing
inter-organ HTTP calls in Executive, I/O Interface, Memory, Reflection, and
Forge forward that same ID; Registry discovery also forwards it automatically.
Background heartbeat work remains uncorrelated, as it was before, because it
has no originating request.

This is wiring, not a new message or API feature: no endpoint shapes, bus
semantics, discovery behavior, or retry policy changed. The small
`shared/correlation.py` module exists only to keep the request-scoped value
out of `organ_base.py`/`organ_client.py`'s import cycle.

Two shared integration tests prove the actual HTTP behavior: an existing
organ-style outbound request receives the caller's correlation ID, and a
Registry discovery made inside an organ request receives it too. The full
isolated test harness passed after the change.

**Update, first real cross-organ integration tests — the gap named above:**

The feature-freeze note above named "cross-organ integration tests (something
no test suite here currently does)" as part of the integration mandate. That
gap is now closed with a new top-level `live_integration/` directory — not an
organ, not a tool, deliberately excluded from `run_all_tests.sh`'s per-organ
loop and from the root `conftest.py` tripwire's concern, because unlike every
existing suite it imports nothing by bare module name from any organ. It only
ever calls organs over real HTTP, the same way a human or another organ would.

Its `conftest.py` boots Registry, Critic, Memory, Communications, and Sensei
as five real `uvicorn` subprocesses on dedicated ports with isolated on-disk
state under a per-session tmp dir, waits for real `/health` and real registry
self-registration, and tears every process down after. Critic has to be real
here, not mocked: Sensei's mutating endpoints go through the same risk-gate
middleware every organ enforces, and without a live Critic they'd fail closed
to `high_risk` and 403 rather than the `reversible` tier `critic_core.py`
actually assigns them.

Sensei was chosen as the subject because it's the newest organ and the one
whose cross-organ claims — `_write_memory`'s fire-and-forget write, `_publish_event`'s
fire-and-forget bus publish — had never been exercised against real Memory or
Communications services, only asserted via injected fakes in its own
single-organ suite. Six tests now prove, over the wire: registry discovery
actually resolves Sensei's peers by name; a `ready`-mode nudge really reaches
`sensei.nudges` on the real bus as `nudge_offered`; a `watching`-mode nudge
reaches it exactly once as `nudge_suppressed`, never queued to fire later
(the one guarantee `sensei_core.py`'s docstring is built around); an accepted
and a rejected `/sensei/respond` call each really land their low-confidence
entry in the real Memory ledger, correctly tagged and owned; and Sensei's
mutating endpoints really do clear the live Critic gate unbypassed, with no
`X-Executive-Approved` or `X-Bypass-Safety` escape hatch used.

`run_all_tests.sh` now runs `live_integration/` as its own step, after the
per-organ loop and before the tui tool, so a full run still says one thing:
pass or fail. Fire-and-forget writes are asserted with a short poll rather
than an instant check, since the whole point of fire-and-forget is that the
HTTP response doesn't wait on it landing.

Sensei's actual Observe → Detect pattern-detection loop (editor/shell/writing
watchers) is still not built — this pass only proved that the delivery half
Sensei already has behaves correctly across real process boundaries. That
remains the next open thread on Sensei specifically, separate from the
integration-suite gap this update closes.

**Update, Sensei's first real detector — the shell chain watcher:**

The prior update closed the "no cross-organ integration tests" gap but
explicitly left Sensei's actual Observe → Detect loop unbuilt — only the
mode-toggle/delivery skeleton existed. This pass builds the first real
detector against that skeleton: a shell command-chain watcher, matching
`Digital_Sensei.md`'s own example verbatim ("repeated chain → alias/script").

`sensei/shell_detector.py` is a new, pure, dependency-free module: given a
chronological list of shell commands, it finds any contiguous block of
2–4 commands repeating verbatim at least 3 times, using the same
"deterministic, always inspectable" philosophy `critic_core.py` already
uses for the same reason — a detector that's sometimes right and
sometimes not on identical input erodes trust in every nudge after it.
Redundant shorter sub-chains already covered by a longer match are
dropped rather than separately reported.

A new `POST /sensei/detect/shell` endpoint in `main.py` is the only thing
that wires that pure function to anything stateful: it runs detection,
then routes each new candidate through the exact same `op_nudge` gate
`/sensei/nudge` already uses — mode is still decided at generation time,
nothing about this new path bypasses that guarantee. "New" is tracked via
a small addition to `sensei_core.py` (`seen_chains.json`, alongside the
existing `state.json`/`nudge_history.jsonl` pattern) so a watcher can
re-scan the same rolling history window on every tick without re-nudging
about a chain that's still sitting there. `critic_core.py` gained one more
rule classifying the new endpoint `reversible`, same tier as `/sensei/nudge`
itself.

The actual Observe half is `sensei/shell_watcher.sh` — a real, installable
bash/zsh hook (`PROMPT_COMMAND`/`precmd`, or a cron/systemd timer) that
reads real shell history and POSTs it to the endpoint above. It fails
silently if Sensei is unreachable, same fire-and-forget convention as
`_write_memory`/`_publish_event`.

Tested at three levels: `shell_detector.py` in isolation (empty history,
below-threshold, exact matches, the sub-chain redundancy rule, sort order,
key stability — 10 tests), the dedup state functions in `sensei_core.py`
(6 tests), the API layer including the "don't re-nudge on a second
identical scan" behavior (5 tests) — and a new live cross-organ test,
`test_shell_detector_end_to_end_nudges_writes_memory_and_dedupes` in
`live_integration/`, proving the full loop for real: a real chain match,
a real nudge through a real Critic gate, a real bus event, a real Memory
write on accept, and no second nudge on a repeat scan — all across real
process boundaries, not mocked. Full suite: all organ/tool suites plus
`live_integration/` (14 tests total there now) still pass clean.

One bug this pass caught in itself, worth recording so it doesn't recur:
the first version of the live-integration fixture isolated Sensei's
`state.json`/`nudge_history.jsonl` paths but not the new `seen_chains.json`
one, so the new detector test passed once and then failed on every
subsequent run — not because of anything wrong in Sensei, but because the
test's own subprocess was silently falling through to the real
`sensei/seen_chains.json` on disk and persisting real "already suggested"
state across unrelated test invocations. Fixed by isolating
`SENSEI_SEEN_CHAINS_PATH` alongside the other two; the leaked file was
deleted from the repo. Recorded here as a reminder that every new
persisted-state env var an organ gains needs a matching isolation line in
`live_integration/conftest.py`, not just in that organ's own
`tests/conftest.py`.

Editor and writing detectors remain the open thread on Sensei — same
shape should work for both (a pure detection function + a thin endpoint
wiring it to `op_nudge`), but neither is built yet.

**Update, Sensei's second detector — undo storms:**

Same shape as the shell chain detector, deliberately: a new pure,
dependency-free `sensei/editor_detector.py` (`find_undo_storms`) finds a
run of consecutive `"undo"` events — any other event type breaks the
run — whose count reaches 4 and whose total span is within 30 seconds,
scoped per file. Digital_Sensei.md names "undo storms" explicitly in its
Pattern Detection list, separate from the "repeated manual sequences"
the shell detector already covers.

A new `POST /sensei/detect/editor` endpoint wires it to the real
`op_nudge` gate exactly like `/sensei/detect/shell` does, reusing the
same `seen_chains.json`-backed dedup functions in `sensei_core.py`
(already generic on a string key, as that file's own docstring
anticipated) — a storm is keyed by file+start_ts+count, so a genuinely
new storm later still nudges, but re-scanning the same event window
doesn't repeat one already flagged. `critic_core.py` gained a matching
`reversible` rule for the new path.

Tested at the same three levels as the shell detector: `editor_detector.py`
in isolation (12 tests — empty input, below-threshold, a non-undo event
breaking a run, span-too-long rejection, per-file scoping, a trailing run
at end-of-input, two separate storms, key stability, message formatting),
API tests (6 tests, including the "new storm later on the same file still
nudges" case, which is the one behavior meaningfully different from the
shell detector's dedup), and a new live cross-organ test proving the full
loop for real. Sensei's own suite: 63 tests. `live_integration/`: 8 tests.
Full repo suite still passes clean.

Deliberately NOT shipped this pass: a real editor watcher script
analogous to `shell_watcher.sh`. Unlike a shell hook (bash/zsh's
`PROMPT_COMMAND`/`precmd` are universal enough to write one script that
covers the common case), there is no single verified way to get "on
undo" events out of an arbitrary editor — it depends entirely on which
editor and what its plugin system supports. Shipping a specific
autocmd/keybinding snippet without being able to verify it actually
fires would mean install instructions that might not work, which is
worse than not shipping one. The endpoint itself is fully real and fully
tested; README now says plainly that wiring a specific editor is the one
piece of this pass that needs local hands, with steps for how to verify
it once wired.

Writing detectors remain the last open thread on Sensei's Observe →
Detect loop.
