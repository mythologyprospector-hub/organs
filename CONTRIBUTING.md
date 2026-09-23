# Contributing to Organs

This is currently a single-maintainer project. This document exists anyway,
for two reasons: it's the checklist the maintainer holds themselves to when
adding an organ, and it's what an outside contributor — or future-you,
six months from now — needs to not accidentally break `CANON.md`.

Read `CANON.md` first. This document is about *how* to build within those
rules; `CANON.md` is what the rules are, and it changes far less often
than this file should.

---

## The one rule above all others

**Finish the organ before starting the next one.** This project exists
because an earlier one (Akasha) didn't hold this line — things got started,
half-wired, and abandoned (a forge loop, a guard module that never got
connected to anything). "Finished" has a concrete bar here, not a vibe:

- [ ] Uses `organ_base.create_organ_app()` — has real `/health` and `/info`
- [ ] Registers via `organ_client.attach_to_registry()`
- [ ] Has a test suite that exercises its actual logic, not just mocks that
      agree with themselves (see "Test discipline" below — this is the
      single most-repeated lesson in this codebase's history)
- [ ] Every error path returns the standard `{"error": {"code",
      "message"}}` envelope
- [ ] If it touches anything outside its own process (OS, filesystem,
      Docker, another organ's permanent state), it's checked against
      `CANON.md` Section 1, item 6 and Section 3's safety-model table
      *before* the API is finalized, not after
- [ ] README (or the relevant section of it) is written before or
      alongside the code, not after — undocumented-but-working isn't
      "finished" in this project's sense of the word

If an organ can't check every box, it doesn't ship, and the next organ
doesn't start.

---

## Adding a new organ

1. **Scaffold**: `organ_name/main.py`, `organ_name/organ_name_core.py`,
   `organ_name/tests/`. Business logic lives in `*_core.py` — plain
   functions, no FastAPI imports, no network calls hardcoded inside them.
   `main.py` is the thin HTTP layer on top: request/response models,
   routing, wiring `*_core.py` functions to endpoints. This split is what
   makes "test the logic without a real network" possible — see Executive
   and I/O Interface's dependency-injection pattern below.

2. **Pick a port.** The next unused one in sequence (currently 8000–8009
   are taken — check `README.md`'s layout table for the current highest).
   Set it via `<ORGAN>_BASE_URL` env var with that port as the default,
   same pattern every existing organ uses.

3. **Wire the two shared files** (`organ_base.py`, `organ_client.py`) —
   don't reimplement health/info/error-envelope or
   registration/heartbeat/discovery locally. If the shared convention is
   missing something your organ needs, that's a conversation about
   changing the shared file for everyone, not a reason to route around it
   in one organ.

4. **If it can affect anything outside its own process**, define the fixed
   allowlist of what it's allowed to touch before writing the endpoint
   that touches it. Orchestrator's `services.json` and Sandbox's two-image
   allowlist are the reference examples — the API surface should make it
   structurally impossible to pass an arbitrary command/image/unit name,
   not just validated-and-rejected at runtime.

5. **If it does something risky or permanent**, don't build your own
   review or approval logic — route it through the real Critic and, if it
   needs multi-step gating, real Executive. Reimplementing a parallel
   safety check defeats the point of having one Critic whose rule set is
   inspectable in one place (`GET /critic/rules`).

6. **Update `README.md`'s layout table and add the organ's section.** Add
   its systemd unit + `.env.example` to `systemd/`. Add it to
   `install.sh`'s copy list and run-commands echo. An organ that exists in
   code but not in `install.sh` or `README.md` isn't actually finished —
   it's undiscoverable by exactly the process meant to discover it.

---

## Test discipline

This codebase has already been bitten by the same class of bug, four
times now: **a mock that quietly diverges from what the real thing
actually does.**

- Sandbox's first `_run()` raised an exception when Docker wasn't
  installed, instead of returning the clean result every other organ's
  `_run()` returns. The mocked "Docker unavailable" test passed anyway,
  because the fake simulated a return value the real function never
  actually produced. A live run — no Docker, for real — crashed instead of
  reporting cleanly, and caught it immediately.
- The same `_run()` had a second, different gap past that fix:
  `PermissionError` (docker present but not executable) wasn't caught
  alongside `FileNotFoundError` (docker missing entirely) — a distinction
  invisible in an environment lacking Docker outright, since only one of
  the two exceptions could ever fire there. An external review running
  the suite somewhere docker exists-but-isn't-executable caught it.
- Introspection's disk collector needed a real `df` run against a live
  filesystem to catch that it doesn't filter FUSE-backed network mounts —
  a real, honestly-documented limitation a synthetic test fixture would
  never have surfaced.
- The real-Docker test itself, once it existed, still hardcoded
  `rc == 127` — assuming every environment this ever runs in has no
  working Docker at all. True on the machine Sandbox was originally
  built on; false on mythos1, where Sandbox is actually meant to run
  real jobs and Docker is installed and working. The live test designed
  specifically to avoid this bug class still smuggled in one narrower
  assumption of its own. Caught live on mythos1, fixed to assert what
  the test's own docstring already said mattered — `_run()` never
  raises, and its result agrees with whichever real state Docker is in
  — rather than assuming only one such state exists.
- Forge's `ollama_generate` caught `urllib.error.URLError` for a failed
  generation call, on the reasonable-looking assumption that any real
  network failure would come through as one. It doesn't: urllib only
  wraps CONNECT-phase failures in `URLError` — `h.request()` is inside
  its own try/except in `do_open()`. A failure while READING the
  response (`h.getresponse()`) is outside that try/except entirely and
  propagates as a raw `TimeoutError` instead. Caught live on mythos1,
  where the connection to Ollama succeeded (the model was cold-loading)
  but generation didn't finish inside the test's 5s timeout — the exact
  gap the organ's own live-Ollama test exists to catch, catching it on
  the very first real run. Fixed by catching `OSError` instead of the
  narrower `URLError` (`URLError` is itself an `OSError` subclass, so
  this is strictly broader, not a different mechanism), with a
  timeout-specific message distinguishing "unreachable" from "reached,
  but too slow." A synthetic slow-server test now reproduces the exact
  failure shape as a permanent regression test, rather than relying on
  a live Ollama being slow to catch it again.

The standing rule from all five: **when a component's whole job is to
report truthfully on something real (a subprocess result, a filesystem, a
dependency's availability), at least one test in its suite must call the
real, unmocked path** — even in an environment where the "happy path"
doesn't apply (no Docker, no GPU, whatever). A green suite proves the mock
was self-consistent, not that it matched reality. Only a live call proves
the second thing. And per Sandbox's second bug specifically: "the happy
path doesn't apply here" can itself have more than one shape — don't
assume the one unhappy path your own environment reproduces is the only
one that exists.

**Known open gap, not yet fixed:** Orchestrator shells out to
`systemctl`/`docker inspect` — the same class of external-truth
reporting as Sandbox — but every one of its 41 tests goes through
`fake_runner`; there is currently no test anywhere in `orchestrator/
tests/` that calls the real, unmocked `_run()`. By this section's own
rule, Orchestrator hasn't actually cleared the bar yet. Flagged, not
fixed — next time Orchestrator gets touched, add a live test mirroring
Sandbox's, before adding anything else.

For organs that make multi-step or externally-effecting calls (Reflection,
Executive, I/O Interface), the standing pattern is **dependency injection**:
the actual HTTP call is a parameter (`evaluate_risk`, `execute_call`,
`create_gated_goal` in Executive and I/O Interface), injected with a real
implementation in `main.py` and a fake in tests. This makes the
state-machine logic (ordering, gating, failure handling) fully testable
without a real network nearby — use this pattern for any organ whose core
logic needs to call another organ.

---

## Code conventions actually in use

- Every core module opens with a docstring explaining *why* it's built the
  way it is, not just what it does — read any existing `*_core.py` for the
  tone. This isn't decoration; several of these docstrings are the only
  place a non-obvious design decision is recorded (e.g. Critic's fail-closed
  rationale, Executive's "no autonomous planning yet" scope note).
- `OrganError` (or an organ-specific subclass pattern, e.g. `CriticError`,
  `ExecutiveError`) for anticipated failures; let genuinely unexpected
  exceptions hit `organ_base`'s catch-all rather than swallowing them.
- Pydantic models for request bodies in `main.py`; plain dicts/dataclasses
  in `*_core.py`. Keeps the core logic testable without importing FastAPI.
- Config via environment variables with sane localhost defaults, documented
  in a table in that organ's README section — not buried in code comments
  only.

---

## Before opening a PR (or calling your own work done)

- [ ] `pytest tests/ -v` passes for the organ you touched, run from
      *that organ's own directory* — never a bare `pytest` from the repo
      root. Every organ has a file called `main.py`; running them all in
      one Python process makes the second organ's `import main` silently
      return the first organ's cached module instead of its own. Not a
      bug to work around — see `CANON.md`'s decision log. Use
      `./run_all_tests.sh` from the repo root instead when you want
      everything checked at once — it runs each organ in its own clean
      subprocess and aggregates the result.
- [ ] `GET /health` and `GET /info` actually work against a running
      instance — not just asserted in a test
- [ ] If you changed anything in `shared/`, run `./run_all_tests.sh` —
      that file has no version of its own, so a breaking change there
      breaks the whole system at once, and this is the one-command way
      to actually confirm nothing did
- [ ] `CANON.md` still describes something true. If your change makes a
      line in it false, that's a Section 4 decision-log entry, discussed
      before merging, not a doc fixed after the fact

---

*Maintainer: James Earl Stambaugh III —
[mythologyprospector@gmail.com](mailto:mythologyprospector@gmail.com) —
[github.com/mythologyprospector-hub/organs](https://github.com/mythologyprospector-hub/organs)*
