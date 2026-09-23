# Security

This document describes the actual current security posture of Organs —
not an aspirational one. Some of what's below is a real limitation, stated
plainly rather than glossed over, because the alternative (a security doc
that oversells the system) is worse than no doc at all.

## Threat model this system currently assumes

**Organs binds every organ's HTTP port to 127.0.0.1 only — reachable
solely from processes running on this same machine, not from the local
network, and not from the internet.** This was not always true; earlier
versions bound to `0.0.0.0` (all interfaces), which meant anything on the
local network could reach every organ directly, bypassing every safety
mechanism below. That was found and fixed. The rest of this document
describes what's true given the *current*, narrower assumption: **any
process able to run as this machine's user is trusted.** That's a
reasonable model for a single-operator personal machine. It is very
likely NOT the right model the moment this is shared with, sold to, or
run on behalf of anyone else — see "What would need to change" below.

Concretely, as of this version:

- **No organ's HTTP surface has cryptographic authentication.** A caller
  is never asked to prove *who* it is. What has changed since an earlier
  version of this document: a shared risk gate (`shared/organ_base.py`)
  now sits in front of every mutating (POST/PUT/DELETE) endpoint on every
  organ and calls Critic before letting it through. An action Critic
  classifies `caution` or `high_risk` — restarting a real service,
  running code with network access, deciding a fact is permanent canon —
  is rejected outright unless the request carries proof it came through
  Executive's real approval flow (`X-Executive-Approved: 1`, set only by
  Executive's own outbound call, only after a step was actually approved)
  or an explicit `X-Bypass-Safety` header for deliberate direct testing
  (logged, never silent, never the default). **This closes the specific
  gap where a direct HTTP call to an organ's own endpoint could skip
  Critic and Executive entirely** — found by an external review, fixed
  the same day. It does NOT amount to authentication: both headers are
  bare strings. Anything already running as this machine's user can read
  the source, learn the header name, and set it itself. The gate raises
  the bar from "any caller" to "any caller willing to read the code" — a
  real improvement against accidents and careless scripts, not a defense
  against a local adversary with your own level of access.
- The Registry itself has no access control either. Anything that can
  reach it can register as any organ name, including impersonating an
  existing one. `/registry/register` is also deliberately exempt from the
  risk gate above — every organ's heartbeat depends on it working even
  when Critic is briefly unreachable, so gating it risked a worse failure
  mode (the whole system unable to boot) than the trust gap it would have
  closed.
- Communications between organs (organ-to-organ HTTP calls, e.g. Executive
  calling Critic, I/O Interface calling Executive) are plain HTTP, not
  TLS, and carry no signing or shared-secret verification.

**Do not bind any organ to anything other than 127.0.0.1, and do not
expose any organ's port to an untrusted network — including the open
internet — without adding real authentication first.** If you need
remote access, a private overlay network (e.g. Tailscale, as used
elsewhere in this maintainer's setup) that keeps the whole system off the
public internet is the current substitute for organ-level auth, not a
replacement the system should be assumed to have on its own.

## What *is* enforced, and where

The absence of cryptographic auth doesn't mean the system has no safety
model — see `CANON.md` Section 3. Four real mechanisms exist and are
worth distinguishing from the (currently absent) authentication layer
above, because each solves a different problem:

- **The shared risk gate** (described above) means a `caution`/
  `high_risk` mutating action is rejected by default, system-wide, unless
  it's provably approved or the caller explicitly, visibly opts out of
  the safety net. This is new since the previous version of this
  document, which described *no* organ-level enforcement at all — that
  was accurate at the time and is no longer accurate.
- **Sandbox's containment** limits what a piece of *code* can do once it's
  running — isolated container, no network by default, hard resource
  limits, destroyed after every job. This protects the host from a
  malicious or buggy job. It does not protect the Sandbox organ's own
  HTTP endpoint from an unauthorized *caller* — the risk gate above
  covers that half now, at the process-trust level described above, not
  the identity level.
- **Critic's fail-closed classification** and **Executive's mandatory
  human-approval gate** mean a `caution`/`high_risk` action can't execute
  without an explicit decision. This is a workflow guarantee, not an
  identity guarantee — it assumes the human making that approval call is
  legitimate, because nothing currently verifies *who* is calling
  `/executive/goals/{id}/steps/{id}/approve`. Executive's own endpoints
  are themselves exempt from the risk gate (its whole API surface IS the
  approval mechanism — gating it would be circular), so this remains the
  one place "a human decided" and "any local caller sent a POST" are
  indistinguishable.
- **Orchestrator's fixed `services.json` allowlist** means even a caller
  that clears the risk gate can only start/stop/restart a pre-configured,
  named service — never run an arbitrary command. The scoped `sudo -n`
  rule (see README's Orchestrator section) further limits what the
  underlying OS user can do even if the Orchestrator process itself were
  compromised.

In short: the system now defends by default against a *legitimate but
risky* action running unreviewed, AND against a bare direct call to a
risky endpoint that skips the approval flow entirely. What it still does
not do is verify *identity* — anything already running as this machine's
own user can clear every mechanism above by reading how they work. That
gap is fine when "this machine's user" is only ever you. It stops being
fine the moment it isn't.

## Sandbox specifically

Job containment (isolated container, no default network, resource limits,
guaranteed teardown) is tested directly per-property — see `CONTRIBUTING.md`'s
test-discipline section for why that mattered in practice, not just in
theory. That containment is real and load-bearing. It is scoped to *what a
submitted job can do*, not *who is allowed to submit a job* — see above.

## Reporting a vulnerability

This is a single-maintainer hobby/personal-infrastructure project, not a
funded security-response operation — set expectations accordingly. If you
find a real vulnerability (not just "there's no auth," which is the known,
documented state above), email:

**James Earl Stambaugh III — mythologyprospector@gmail.com**

Please include which organ, the endpoint or behavior, and a minimal
reproduction. Given the project's current stage, a fix timeline isn't
promised, but reports are read and taken seriously.

## What would need to change before this is shared with, sold to, or run on behalf of anyone other than the current operator

Not a roadmap commitment, just an honest list of what the process-trust
model above actually implies is missing, for anyone evaluating whether to
expose this beyond a single trusted operator on a single machine:

- Per-request authentication on every organ (shared secret, mTLS, or an
  API-gateway layer in front of the whole registry) — the risk gate's
  current `X-Executive-Approved`/`X-Bypass-Safety` headers are bare
  strings, not cryptographic proof, and were deliberately scoped that way
  (see above) for a single-operator machine, not a shared one
- Signed or otherwise verified organ-to-organ calls, so one organ can't be
  spoofed by anything else on the network
- Authenticated identity behind Executive's approve/reject calls, since
  right now "a human decided" and "any local caller sent a POST" are
  indistinguishable
- TLS between organs, not just at any external edge
- A real answer to "who is 'the operator' when more than one person or
  tenant is involved" — everything above assumes a single trusted user;
  multi-tenant use needs its own design, not just stronger crypto bolted
  onto the current single-user assumptions
