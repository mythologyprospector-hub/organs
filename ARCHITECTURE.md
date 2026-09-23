# Organs Architecture

## Status

This document defines the intended role of **Organs** as a reusable runtime substrate.
It is a migration/architecture baseline, not a claim that the existing implementation
already satisfies every item below.

## Purpose

Organs provides the shared machinery on which larger systems can be built:

- organ discovery and lifecycle
- inter-organ communication
- durable state and memory primitives
- deterministic safety gates
- explicit execution
- constrained sandboxed execution
- system orchestration
- introspection and reflection
- operational telemetry
- human-facing inspection

Domain-specific capabilities should live in separate organs and compose through these
shared contracts rather than forcing the substrate to become the domain application.

## Existing substrate

The imported implementation contains these principal organs/components:

| Component | Role |
|---|---|
| Registry | discovery, registration, heartbeat, lookup |
| Communications / BUS | persistent pub/sub and dispatch |
| Memory | durable knowledge/state primitives |
| Critic | deterministic pre-action risk classification |
| Executive | explicit goal/plan/step tracking and Critic-gated execution |
| Sandbox | ephemeral constrained execution |
| Orchestrator | fixed, configuration-defined service control |
| Introspection | live system self-knowledge |
| Reflection | optional background reflection |
| Telemetry | operational observation/history |
| I/O Interface | deterministic front door and routing |
| TUI | human-facing monitoring/inspection |
| Sensei | local developer/context assistance |

## Core contracts to preserve

1. Organs are independently addressable services.
2. Registry is the discovery mechanism; organs should not hardcode peer addresses when
   discovery is appropriate.
3. Communication uses the BUS for asynchronous inter-organ events where appropriate.
4. The standard organ boundary exposes `/health` and `/info` and uses the shared error
   envelope.
5. Operational requests/mutations are observable through Telemetry at the organ boundary.
6. Critic can reject/recommend but is not an authorization authority for risky actions.
7. Executive tracks explicit work rather than inventing autonomous plans.
8. Sandbox is the execution containment boundary and does not confer trust on outputs.
9. Orchestrator controls only its fixed, approved service set; it does not become an
   arbitrary command execution endpoint.
10. Persistent state must have an explicit owner and must not be silently conflated with
    transient runtime state.

## Extension model

A new domain organ should be able to:

1. implement the standard organ lifecycle;
2. register with Registry;
3. discover peers through Registry;
4. communicate through the shared BUS/client conventions;
5. emit boundary telemetry;
6. use Memory, Sandbox, Critic, Executive, or other substrate services through explicit
   contracts; and
7. remain independently testable and replaceable.

## Current architectural direction

Organs is the substrate, not the Renaissance application itself.

Future domain organs such as Episteme, Provenance, Atlas, Unknowns, Experimentalist,
Referee, and Rosetta belong above this substrate and should be introduced only after
Human Gate approval of their contracts.

## Non-goals

Organs does not itself define:

- a single worldview or doctrine;
- a civilization-wide knowledge ontology;
- an autonomous machine authority;
- a universal planning intelligence;
- a replacement for human judgment.

Those concerns belong to higher-level projects and their own canonical documents.
