# Organs — Agent Instructions

## Authority and project memory

This file governs working method only. Organs' existing project documents remain authoritative for its purpose, runtime contracts, implementation history, and safety boundaries.

Before substantial work, read:
1. `README.md` for orientation and its current reading list.
2. `CANON.md` for permanent technical rules.
3. `ARCHITECTURE.md` for current design.
4. `GOAL.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `DEV_NOTES.md` as relevant to the task.
5. The implementation, tests, and current GitHub state directly involved.

Do not assume conversation history is current or complete.

## Targeted grounding — Miracle Tokens

Use GitHub as durable project memory and conversation as temporary working context. Retrieve only the context needed for the current task rather than repeatedly carrying the whole project through conversation.

- Inspect current repository state and relevant contracts before acting.
- Broaden grounding for security, shared-runtime, deployment, cross-project, or unresolved architectural questions.
- Preserve existing technical documentation, decisions, migration history, and rationale.
- Never remove or compress durable project knowledge merely to save conversational tokens.
- Update the appropriate existing source of truth when a material discovery or decision will matter later.
- Keep explanations brief while reporting what changed, what was actually tested, and what remains uncertain.

This is **targeted grounding, not shallow grounding**. Do enough inspection to act safely.

## Runtime and safety boundaries

- Follow Organs' own published contracts; do not invent endpoints, ports, capabilities, or behavior from memory.
- Keep operational telemetry distinct from domain evidence.
- Preserve bounded execution and explicit human-approval boundaries.
- Do not change another project or the installed shared runtime as an incidental part of Organs work.
- Inspect before editing; prefer small, reversible changes.
- Treat outside reviews as input to verify, not authority.
- Keep this file operational; technical truth and historical rationale remain in the existing Organs documents.
