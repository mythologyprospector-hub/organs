# Organs Architecture

## Status

Organs is the **Renaissance runtime substrate**.

This document describes the technical role of the repository. Renaissance's
constitutional and foundational documents remain the higher-level authority.

## Layering

    Renaissance constitutional canon
                |
                v
    Renaissance architecture and domain contracts
                |
                v
    Organs runtime substrate
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
                +-- human/operator interfaces

The important boundary is directional:

**Renaissance tells Organs what the larger system requires. Organs does not
decide what Renaissance is.**

## Current components

| Component | Runtime responsibility |
|---|---|
| Registry | discovery, registration, heartbeat, staleness |
| Communications / BUS | persistent pull-based event transport and dispatch |
| Memory | durable runtime memory and state primitives |
| Sandbox | bounded isolated execution |
| Critic | deterministic pre-action risk classification |
| Executive | explicit goal/plan/step tracking and gated execution |
| Orchestrator | control of a fixed, approved service set |
| Introspection | observation of live system state |
| Reflection | optional background reflection that does not own execution |
| Telemetry | append-oriented operational observation |
| I/O Interface | deterministic human-facing request routing |
| TUI | human-facing inspection and operation |

## Authority boundaries

Organs contains mechanisms, not sovereignty.

- Registry discovers; it does not decide.
- BUS transports; it does not interpret.
- Memory stores runtime state; it does not establish Renaissance truth.
- Critic classifies configured risks; it is not a moral or constitutional
  authority.
- Executive coordinates explicitly approved work; it is not sovereign.
- Sandbox contains execution; successful execution does not make an output
  true.
- Orchestrator controls only its explicit service allowlist.
- Telemetry records operational events; operational telemetry is not epistemic
  evidence.
- Reflection may suggest or record; it does not grant itself authority.
- I/O Interface translates within a fixed catalog; it does not invent
  capabilities.
- TUI exposes human interaction; it does not become a hidden authority.

## Domain boundary

Renaissance domain capabilities should remain independently defined.

They may consume Organs services through explicit interfaces.

Organs should not absorb their domain semantics merely because doing so would
be convenient.

## Replaceability

An organ is replaceable when another implementation can satisfy its published
contract without requiring the rest of the system to know its internals.

This is a design requirement, not a claim that every current organ already
meets it perfectly.

## Current technical posture

The repository is Python/FastAPI based and is intentionally organized as
independently testable services rather than one shared application process.

The test runner executes service suites in isolated subprocesses. That is an
implementation constraint of the current layout, not a claim that isolation
is the only possible future architecture.
