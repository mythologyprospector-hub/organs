# Organs Canon

Organs is the runtime substrate of Renaissance.

This file defines the permanent technical rules of Organs. It does not replace
or outrank Renaissance constitutional canon. If a local Organs rule conflicts
with Renaissance canon, the conflict must be resolved explicitly; Organs does
not silently elevate its implementation into higher authority.

---

## 1. Runtime non-negotiables

1. **Every organ uses the shared organ boundary.**
   Every organ exposes /health and /info, uses the shared error envelope, and
   is built on shared/organ_base.py.

2. **Every organ participates in discovery through Registry.**
   Peer addresses must not be hardcoded when Registry discovery is appropriate.
   The Registry itself is the one fixed discovery root.

3. **Every organ registers and heartbeats through the shared client.**
   Staleness is determined by missed heartbeats. A crash and a clean shutdown
   are intentionally indistinguishable to Registry.

4. **Runtime state has an explicit owner.**
   Persistent state, caches, telemetry, and transient process state must not be
   silently conflated.

5. **No implementation component becomes a source of truth merely by being
   infrastructure.**
   In particular, Organs Memory is runtime memory. It is not the Renaissance
   epistemology and it is not a substitute for provenance-bearing domain
   knowledge.

6. **External effects are bounded.**
   A service that can affect something outside its own process must use a
   fixed, enumerable allowlist rather than accepting arbitrary commands,
   containers, images, or service names from callers.

7. **Risk classification happens before risky execution.**
   Critic fails closed. An unrecognized action is not silently treated as safe.

8. **Consequential actions retain an explicit human approval path.**
   There is no timeout-based auto-approval.

9. **Sandbox containment is not evidence.**
   Code that executes successfully has demonstrated execution behavior, not
   truth, correctness, or authority.

10. **Operational telemetry is not epistemic evidence.**
    Telemetry can establish what the runtime reported or did; it does not by
    itself establish that a domain claim is true.

---

## 2. Structural rules

### One capability, one owner

An organ should have one clearly stated primary responsibility. Shared
mechanisms belong in shared infrastructure rather than being duplicated in
multiple organs.

### Explicit contracts

An inter-organ dependency must be visible in code and documentation. Hidden
coupling is a defect.

### Replaceability

Organs should be independently testable and replaceable behind their
contracts.

### Human agency

Organs must never acquire authority merely because a mechanism makes an action
possible. Human approval remains a real decision boundary where the system
requires it.

### No hidden autonomy

A component may not acquire self-directed consequential behavior through a
"convenience" change that leaves its documented contract unchanged.

---

## 3. Relationship to Renaissance

Renaissance has the higher-level constitutional hierarchy:

    Constitutional Canon
            |
            v
    Charter / Foundational Canon
            |
            v
    Established Requirements & Architecture
            |
            v
    Implementation
            |
            v
    Experiments / Proposals

Organs lives at the implementation/runtime layer.

Therefore:

- Organs may implement Renaissance requirements.
- Organs may expose reusable runtime contracts.
- Organs may propose architectural improvements.
- Organs may not silently redefine Renaissance.
- Organs implementation details do not become constitutional principles through
  age, convenience, or repeated use.

---

## 4. Decision record

This canon was aligned to Renaissance when the project relationship was made
explicit.

The important decisions are:

- Organs exists solely to serve Renaissance.
- The former Digital Djinn/coding-agent mission is retired.
- Forge is not part of the runtime architecture and must not be resurrected
  as a hidden dependency.
- The runtime substrate remains modular so Renaissance domain capabilities can
  evolve independently.
- Organs Memory is runtime infrastructure, not Renaissance's epistemic canon.
- Critic, Executive, Registry, and other mechanisms have bounded roles and no
  inherent sovereignty.
- Local security and safety mechanisms remain implementation mechanisms; they
  do not become civilization-level governance merely by existing here.

Future changes to these rules require an explicit decision record in the
Renaissance project.
