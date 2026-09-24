# Organs

**The runtime substrate for Renaissance.**

Organs is the reusable service infrastructure underneath the Renaissance
constellation: discovery, communication, memory, bounded execution, safety
gates, coordination, introspection, telemetry, and human-facing operation.

Renaissance's north star is:

> **Renaissance exists to increase humanity's ability to understand, explore,
> create, and flourish.**

Organs exists to make that possible at the runtime layer.

---

## What Organs is

Organs is a collection of small, independently testable services called
**organs**.

They communicate through explicit contracts rather than becoming one giant
application.

## Current organs

| Organ | Purpose |
|---|---|
| Registry | service registration, discovery, heartbeat, staleness |
| Memory | durable runtime memory and state primitives |
| Communications | persistent pull-based event BUS |
| Orchestrator | bounded control of a fixed service allowlist |
| Reflection | optional background reflection |
| Introspection | live system self-observation |
| Sandbox | isolated, resource-bounded execution |
| Critic | deterministic risk classification |
| Executive | explicit goal/plan/step coordination |
| I/O Interface | deterministic human-facing request routing |
| Telemetry | operational event history |

### Operator tools

- **TUI** — live terminal dashboard and human control surface.

These tools consume Organs; they are not additional authority layers.

## What Organs does not decide

Organs does not decide:

- what humanity should believe;
- what Renaissance ultimately is;
- which domain claims are true;
- what political, moral, religious, or cultural worldview people should adopt;
- whether a machine should become sovereign;
- whether a runtime mechanism deserves authority simply because it exists.

Those questions belong to humans and to the appropriate higher-level Renaissance
canon and domain processes.

## Safety and agency

Organs is designed around bounded machinery:

- unknown or unrecognized risky actions fail closed;
- consequential actions can require explicit human approval;
- Sandbox contains execution rather than declaring outputs trustworthy;
- Critic is deterministic and inspectable;
- Executive coordinates explicit work but is not sovereign;
- operational telemetry is kept distinct from epistemic evidence;
- services are intended to remain replaceable.

Security details and current limitations are documented in SECURITY.md.

## Development

Run the complete isolated test suite:

    cd /srv/organs
    ./run_all_tests.sh

Run one organ:

    cd /srv/organs/<organ>
    python3 -m pytest tests/ -q

Read:

- CANON.md — permanent runtime rules
- ARCHITECTURE.md — technical architecture
- GOAL.md — project purpose
- CONTRIBUTING.md — development discipline
- SECURITY.md — actual security posture
- DEV_NOTES.md — implementation history and rationale

## Historical note

Organs began as infrastructure for an earlier coding-agent experiment. That
mission is retired.

The reusable runtime work survived because it is useful to Renaissance.

Historical references are retained only where they explain how the current
implementation came to exist. They do not define the current purpose.
