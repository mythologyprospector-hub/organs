# Digital Djinn — Project Goal

## The job

Digital Djinn is being built to become a **local coding agent capable of completing real programming work**, with the eventual practical target of taking suitable Fiverr programming gigs from a customer specification to a working, reviewable deliverable.

The important word is **working**. The goal is not to make a local model that merely produces plausible-looking code. Djinn must eventually be able to:

1. understand a concrete programming request,
2. establish and maintain a real project workspace,
3. generate and modify code in that workspace,
4. run the code and its tests in a real execution environment,
5. observe the actual results rather than trusting the model's claim,
6. remember what it tried and what happened,
7. diagnose failures and iterate,
8. preserve the resulting project as a reviewable deliverable, and
9. stop for human review whenever the system's safety model requires it.

The intended architecture is therefore a **coding loop**, not a one-shot prompt:

```text
customer specification
        ↓
      goal
        ↓
       plan
        ↓
      generate
        ↓
    workspace
        ↓
       build
        ↓
       test
        ↓
     telemetry
        ↓
   current state
        ↓
   diagnose / revise
        └──────────────→ test again
                         ↓
                     deliverable
```

Telemetry answers **what happened**. Memory answers **what is worth retaining**. The workspace contains **what currently exists**. The execution environment answers **whether it actually works**. The planning/executive layer answers **what should happen next**.

A separate "trajectory" organ is not currently required. Goal-relative progress can emerge from the relationship among those existing pieces. Do not add a trajectory organ merely to give that concept a name.

## Current boundary

The current system is intentionally **not** a fully autonomous coding agent yet. Forge is the real code-generation organ; Sandbox is the real execution boundary; Executive holds explicit plans and gates risky actions; Telemetry records operational reality; Memory provides durable context. Autonomous planning, autonomous repair loops, and a polished gig-intake/delivery workflow are future capabilities, not assumptions about the current system.

## Feature freeze

The architecture is in **feature freeze**.

Feature freeze means:

- **No new organs.**
- No speculative organs copied from a roadmap merely because they sound useful.
- No new major responsibilities assigned to an existing organ.
- No autonomous planning quietly added to Executive.
- No publish/deploy/commit behavior quietly added to Forge.
- No replacement safety model invented because it seems more convenient.

Feature freeze does **not** mean the existing organs are frozen in an unfinished state.

## Maximization passes

Each existing organ may receive a **bounded maximization pass** before new capabilities are considered.

A maximization pass asks:

> Given this organ's existing contract and responsibility, is it as complete, reliable, testable, observable, and internally coherent as is reasonably appropriate for the project's current stage?

Allowed:

- complete behavior that the existing contract already promises,
- fix concrete bugs,
- harden validation and failure handling,
- improve tests around real behavior and failure boundaries,
- improve persistence/durability where already required,
- improve observability where already required,
- remove dead or misleading implementation,
- correct documentation that no longer matches reality,
- improve integration with existing organs without changing ownership.

Not allowed:

- adding a new organ because the pass discovers an interesting idea,
- giving an organ a new unrelated job,
- building abstractions for hypothetical future requirements,
- replacing a deliberate architectural boundary merely because another design is fashionable.

The maximization pass should be performed **one organ at a time**. For each organ, first establish what it is supposed to do, then inspect implementation and tests, then make only bounded improvements, then run its tests and the full isolated test suite before moving on.

## Definition of success for the project

The decisive future test is not architectural elegance. It is a real programming task.

Djinn should eventually be able to receive a suitably scoped customer programming request and demonstrate, through its own workspace, execution environment, tests, telemetry, and memory, that it can move from specification to a working deliverable without requiring a human to manually perform the programmer's normal edit/run/test/debug loop.

Until that works reliably, the project is still infrastructure for the coding agent rather than the finished coding agent.
