# Organs — Project Goal

## Purpose

**Organs exists solely to provide runtime infrastructure for Renaissance.**

Renaissance exists to increase humanity's ability to understand, explore,
create, and flourish. Organs is the machinery that lets Renaissance
capabilities operate as a coherent, inspectable, replaceable system.

Organs is not a separate product, ideology, agent, business, or destination.
Its job is to provide dependable infrastructure for the Renaissance
constellation.

## What Organs provides

Organs supplies the reusable runtime substrate needed by Renaissance
capabilities, including:

1. Discovery — services identify one another without hardcoded peer addresses.
2. Communication — components exchange durable events and requests through
   explicit contracts.
3. Persistence — runtime memory/state has explicit ownership and lifecycle.
4. Execution boundaries — work can run inside constrained environments.
5. Safety gates — risky actions can be classified and stopped before execution.
6. Human approval paths — consequential actions can require an explicit human
   decision.
7. Coordination — explicit goals, plans, and steps can be tracked without
   making the coordinator sovereign.
8. Introspection — the running system can report its actual operational state.
9. Telemetry — operational events can be observed and reconstructed.
10. Human interface — people can inspect and operate the system without
    knowing every internal endpoint.

These are infrastructure capabilities, not claims that any one current organ
is the final Renaissance design.

## Architectural relationship

    RENAISSANCE
         |
         | constitutional / system canon
         v
    DOMAIN CAPABILITIES
    Episteme · Provenance · Atlas · ...
         |
         v
    ORGANS
    runtime infrastructure
         |
         +-- Registry
         +-- Communications / BUS
         +-- Memory
         +-- Sandbox
         +-- Critic
         +-- Executive
         +-- Orchestrator
         +-- Introspection
         +-- Reflection
         +-- Telemetry
         +-- Human/operator interfaces

Renaissance defines the larger purpose and constitutional boundaries.
Organs implements runtime infrastructure.

**No implementation detail inside Organs becomes Renaissance canon merely
because it exists, is old, or is widely used.**

## Current boundary

The repository contains working infrastructure services and operator tools.
Some are mature; some are intentionally limited; some are candidates for later
refinement.

The current set includes:

- Registry
- Communications / BUS
- Memory
- Sandbox
- Critic
- Executive
- Orchestrator
- Introspection
- Reflection
- Telemetry
- I/O Interface
- TUI
- Sensei, as an optional operator/developer aid

Forge was deliberately removed and is not part of the architecture.

## Success condition

Organs succeeds when Renaissance capabilities can rely on it as boring,
predictable infrastructure:

- services discover one another reliably;
- communication semantics are explicit;
- persistent state has clear ownership;
- risky actions fail closed;
- consequential actions retain human control;
- execution is bounded;
- operational reality is observable;
- components remain replaceable;
- failures are diagnosable;
- tests reproduce the behavior being claimed.

The point is not to make Organs impressive.

The point is to make Renaissance possible.

## Scope discipline

Organs may grow when Renaissance requires infrastructure that genuinely belongs
at the runtime layer.

It must not grow by absorbing domain knowledge, becoming a universal
intelligence, or assigning itself authority that belongs to humans or to
Renaissance's higher-level canon.

New organs and major responsibility changes require an explicit architectural
decision in accordance with Renaissance change control.
