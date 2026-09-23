# CANON.md

**Organs** — the permanent rules. Not a manual, not a changelog. Everything
here should still be true a year from now regardless of which organs exist
by then. If you're editing this file, that's a big deal — say why in
Section 4.

The distinction from README.md: README describes what the system currently
does and changes every time an organ ships. This describes what the system
is always required to do, and changes almost never.

---

## 1. Non-negotiables

The rules that, if broken, break the trust model the whole system depends
on — not style preferences, things that mean an organ shouldn't ship.

1. **Every organ speaks HTTP and finds everyone else through the Registry.**
   No organ hardcodes another organ's port. The one fixed address in the
   system is the Registry itself (`http://localhost:8000` by convention,
   `ORGAN_REGISTRY_URL` to override) — because something has to be the root
   of discovery, and it's better to have exactly one such thing than to
   pretend there are zero.

2. **Every organ is built on `organ_base.py`, no exceptions.** That means,
   for every organ, always:
   - `GET /health` — `ok`/`degraded`, with per-dependency detail. Overall
     status is the AND of every registered check; one degraded dependency
     degrades the whole organ's reported health, on purpose.
   - `GET /info` — name, version, description, capability list.
   - Every error — anticipated (`OrganError`) or not (any unhandled
     `Exception`, caught and turned into a 500) — comes back as
     `{"error": {"code": "...", "message": "..."}}`. A caller (another
     organ) never has to special-case a raw stack trace.

3. **Every organ registers and heartbeats through `organ_client.py`.**
   `attach_to_registry()` on startup, a heartbeat loop after. A registry
   that's briefly unreachable at boot is logged, not fatal — the organ
   still comes up and serves traffic. `discover(name)` refuses to hand back
   an address for anything stale (missed heartbeats) — a caller should
   never get routed into a wall.

4. **A crash and a clean shutdown look identical to the Registry.** There is
   no explicit "I'm dying" signal. Both just stop heartbeating and age into
   `stale` after `REGISTRY_STALE_AFTER` seconds (default 30). This is
   deliberate: you can't rely on a crashing process to announce its own
   death, so the system doesn't build anything that assumes it will.

5. **Nothing cheap commits permanently, unsupervised.** Anything that
   becomes canon requires an explicit human decision — no automated
   process, local model included, ever makes something permanent on its
   own; it can only *suggest*. The mechanism differs by record type, and
   that's worth being precise about rather than flattening it: facts and
   scars go through an actual two-step propose → decide flow (a separate
   proposed record exists, pending, until accepted or rejected); promises
   and relations resolve through one direct call instead, with no
   separate "proposed" state ever existing for them. Same guarantee
   either way — a human always has to act, nothing resolves itself — just
   not literally the same mechanism. This is Memory's rule, and it's now
   the system's rule: any future organ that wants to make something
   permanent inherits this same guarantee rather than inventing its own,
   whichever of the two shapes actually fits what it's protecting.

6. **No organ exposes an API surface that accepts an arbitrary
   command, container, image, or unit name from a request body.** Every
   place the system can reach outside its own process boundary is a fixed,
   pre-approved allowlist, not a free parameter:
   - Orchestrator: a fixed `services.json`, edited by a human, not sent by
     a caller.
   - Sandbox: exactly two base images (`python:3.11-slim`,
     `node:20-slim`), hardcoded, no API path that accepts a third.

   The rule generalizes past these two current examples: **if a future
   organ can affect anything outside its own process, the set of things it
   can affect must be enumerable and fixed, not caller-supplied.**

7. **Every risky or permanent action is classified BEFORE it runs, and the
   classifier fails closed.** This is Critic's rule, and because Executive
   and I/O Interface both route every single action through the real
   Critic rather than reimplementing their own judgment, it's a system-wide
   guarantee, not just one organ's internal behavior: an organ, endpoint,
   or request shape the classifier doesn't recognize is `high_risk` by
   default. The allowlist has to affirmatively cover something for it to
   skip human review — never the reverse. If Critic itself is unreachable,
   every caller that depends on it (Executive, I/O Interface) treats that
   as `high_risk` too, not as an all-clear.

8. **`caution` and `high_risk` always halt for an explicit human decision.**
   No timeout-based auto-approval exists anywhere in this system, on
   purpose. Executive's step loop halts and waits; it does not proceed
   after N seconds, after N retries, or because a similar step was
   approved before. If this ever needs to change, that's a Section 4
   decision, not a quiet code change.

---

## 2. The build rule

One line, stated once, cited everywhere else in this system's docs instead
of re-argued: **each organ gets built to completion before the next one
starts.**

This exists because Akasha's failure mode — the monorepo Organs replaced —
was moving on before something was finished and never coming back (the
forge loop, `pipeline_guard` never wired in). CANON.md exists partly to
make sure Organs doesn't quietly repeat that. "Complete" means: has tests
that exercise its real behavior (not just mocks that agree with
themselves — see Section 5's sandbox entry), has a `/health` and `/info`
that mean something, and is wired into the registry/discovery convention
like everything else.

---

## 3. Safety models

There isn't one safety model in this system. There are three, and they're
different on purpose — CANON.md is where that's written down so nobody
"fixes" one to look like another later.

| Model | Where | The property |
|---|---|---|
| **Review-based** | Memory (facts, scars, promises, unknowables, relations) | Becomes permanent, so a human decides before it's canon. Cheap to propose, expensive to skip review. |
| **Containment-based** | Sandbox | Never becomes permanent. Isolation replaces review — a fresh container per job, no network by default, hard resource limits, destroyed immediately after, success or failure. The safety property is *containment*, not judgment. |
| **Gated-execution** | Critic + Executive + I/O Interface | Classification happens *before* anything runs, not after. Critic is a deterministic rule engine (explicitly not an LLM — see Section 6), Executive refuses to run a `caution`/`high_risk` step without approval, and I/O Interface — the natural-language front door — routes every single interpreted action through the same real Critic rather than getting its own shortcut just because the request arrived as a sentence instead of a curl command. |

A new organ that touches permanence, external state, or multi-step action
should be checked against this table before it's built: which of the three
models does it need, and does it actually route through the real
mechanism (real Critic call, real propose/decide flow) rather than
reimplementing a parallel one?

---

## 4. Decision log

Append-only. Not a feature changelog — a record of choices that would be
expensive to silently reverse, so a future pass through this codebase
doesn't "fix" something that was actually a deliberate boundary.

- **Pull-based Communications bus, not push.** Consumers poll via cursor
  rather than Communications pushing into every organ's inbound endpoint —
  so no organ has to implement a webhook receiver just to listen.
- **Registry treats crash and clean shutdown identically.** No
  deregister-on-crash signal exists or is planned; staleness-by-timeout is
  the only mechanism, on purpose (Section 1, item 4).
- **Critic is a fixed rule engine, not an LLM.** Chosen specifically
  because a rule engine can't be talked into approving something by
  phrasing, doesn't degrade under load, and its reasoning is always
  inspectable via `GET /critic/rules`. Revisiting this would remove the
  one part of the system where "why was this allowed" always has a fixed
  answer.
- **Executive does not do autonomous LLM planning.** Given what's already
  known about local model quality, promising autonomous planning was
  judged dishonest to ship. Plans are explicit, submitted step lists.
  Autonomous planning is a real future capability, layered on top of this
  skeleton later — not assumed now, and not something a future pass should
  quietly add without updating this entry.
- **I/O Interface is a fixed intent catalog, not free-form LLM
  interpretation.** Same reasoning as Critic: an 8B local model guessing at
  arbitrary API calls from natural language was judged as exactly the kind
  of "moon-shot cognition" this system avoids elsewhere. If nothing in the
  catalog matches, it says so and shows what it does understand — it never
  guesses at an action it isn't confident about.
- **Reflection is off by default, and the toggle lives in a file, not just
  memory.** `state.json` starts with `enabled: false`; the systemd service
  *running* is never the same thing as it *thinking*.
- **No unified `pytest` run across the whole repo, and this is not a gap
  to fix by restructuring.** Every organ has a file called `main.py` and
  its own `<organ>_core.py`. Run all twelve organs' tests in ONE Python
  process and the second organ's `import main` silently returns the
  FIRST organ's already-cached module (`sys.modules` caches by bare name,
  and nothing about pytest's own import handling changes that — it only
  affects how pytest identifies *test files*, not what those files
  import). Discovered when an external review flagged "pytest doesn't
  work from the root" as an incompleteness; the actual fix wasn't making
  it work — it was recognizing that trying to make it work would mean
  breaking the "no monorepo, no shared venv" principle from Section 2,
  for the sake of one convenience command. `run_all_tests.sh` gives the
  same one-command convenience by running each organ in its own clean
  subprocess instead — matching how they actually deploy, not forcing
  false coexistence.

---

## 5. Known ceilings — not gaps, boundaries

Pulled out of individual organ READMEs and canonized here so nobody
"discovers" one of these and quietly builds around it without checking
whether it was intentional:

- **No automatic contradiction detection or scar proposal.** The plumbing
  to *record* a contradiction or a scar is real; deciding *that* something
  contradicts, or *that* an event deserves a scar, stays a human call.
  Intentional, not deferred.
- **No autonomous reflection loop that initiates its own actions.**
  Reflection writes low-confidence entries back to Memory; it doesn't act.
  Executive is where goal-driven multi-step action lives, and even there
  it's human-plotted, not self-initiated.
- **Memory recall is a linear scan** over every embedding on every query.
  Fine at current scale; will need real vector indexing if entry count
  gets into the tens of thousands.
- **No systemd-managed automatic restart is relied upon as a safety
  property.** Unit files exist; nothing in the safety model assumes an
  organ that crashes comes back on its own.
- **No authentication or authorization on any organ's HTTP surface.**
  Every endpoint in this system — including Orchestrator's start/stop and
  Sandbox's job submission — currently assumes the whole organ set runs on
  a trusted local network with no untrusted caller able to reach it. This
  is a boundary the system currently depends on rather than enforces
  itself. See `SECURITY.md`.

**Formerly a real gap, now closed:** the Registry — the single fixed
address every other organ depends on to find anything — went untested
longer than any other organ, since it was built second (right after the
shared convention itself), before "build to completion" meant a real test
suite for every organ, no exceptions. Now has 29 tests covering every
Section 1 non-negotiable that actually lives in `registry_core.py`:
first-registered preservation across re-registration, staleness timing
at and around the threshold, snapshot persistence across a simulated
restart, corrupt-snapshot survival, and — directly — item 4's crash/
shutdown-parity claim: a test that simulates a crash (heartbeat just
stops) and confirms there is no special "crashed" state distinguishable
from ordinary staleness, only the one mechanism everything else uses.

---

## 6. Glossary

- **Organ** — an independent HTTP service, one capability, discoverable by
  name through the Registry rather than a hardcoded address.
- **Canon** (lowercase, as used throughout Memory and this document) — the
  state a fact, scar, relation, or promise reaches only after an explicit
  human decision, as opposed to a proposal, which is cheap and reversible.
- **Scar** — a permanent behavioral-lesson record in Memory. Corrections
  *supersede* an existing scar rather than overwriting it — the old
  entry's status changes to `superseded`, but its text stays readable.
- **Salience vs. confidence** — two separate decay curves on the same
  Memory entry. Salience is "how findable" (decays with time and lack of
  access; pinning stops it). Confidence is "how sure we are it's still
  true" (decays with time since last confirmation, never fully bottoms
  out — decayed-to-unsure is not the same claim as known-false).
- **Risk tier** — Critic's four-value classification (`safe`, `reversible`,
  `caution`, `high_risk`) assigned to a proposed action before it runs.
  Only the first two can auto-proceed.
- **Fail closed** — the system's default posture whenever something is
  unrecognized or unreachable: treat it as the riskiest plausible case,
  never the safest.

---

*Maintained per the project's documentation standard — see
`CONTRIBUTING.md`. Questions about a canon decision: James Earl Stambaugh
III, mythologyprospector@gmail.com.*
