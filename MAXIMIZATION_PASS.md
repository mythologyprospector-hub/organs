# Maximization Pass — 2026-08-18

## Scope

This pass was performed under `GOAL.md` and the existing feature freeze.

The rule was: **improve an existing organ only where the improvement is concrete, bounded, and already belongs to that organ's responsibility. No new organs and no speculative architecture.**

The pass covered the existing HTTP organs plus the TUI tool, with the strongest implementation attention on the organs directly responsible for the eventual coding loop: Forge, Sandbox, Executive, Memory, and Telemetry.

## Baseline

Before changes, the repository's isolated test runner passed all existing organ/tool suites.

The final run after the pass is also green:

- **451 tests passed**
- all organ suites passed in their required isolated subprocesses
- TUI tests passed
- existing FastAPI deprecation warnings remain; they are framework warnings, not test failures

## Changes made

### Forge

Forge is the organ most directly tied to the project's actual purpose, so the pass tightened its existing behavior without expanding its responsibility.

1. **Validate the complete build request before calling Ollama.**
   A request containing `test_spec` but missing `test_filename` or `test_command` now fails before an expensive model call and before a persistent job directory is created.

2. **Do not leave orphaned persistent job directories on failed generation.**
   A Forge job becomes persistent only after its manifest has been written and ledgered. If generation or test generation fails first, the partial directory is removed. If Sandbox is unreachable, that remains a validation result and the generated deliverable is preserved, as intended.

3. **Reject empty Ollama generation responses.**
   A successful HTTP response with a missing, empty, or whitespace-only `response` is now treated as a Forge error instead of producing an apparently valid one-line/empty deliverable.

4. **Added regression tests** for all three boundaries.

None of these changes add a new capability. They make the existing `spec → generate → persist → optionally validate` contract less surprising and more reliable.

### Telemetry

Telemetry already had the right role and storage model. One concrete query-boundary bug was tightened:

- `limit=0` or a negative query limit is now rejected instead of reaching SQLite. Negative SQLite `LIMIT` values have special behavior and should not be an accidental way around Telemetry's declared query bounds.
- Added regression coverage for both zero and negative limits.

### Other organs

No speculative code changes were made to the remaining organs during this pass. Their existing contracts were checked against the feature-freeze rule and current test behavior; where a change would have amounted to a new responsibility, it was deliberately left alone.

That restraint is part of the pass. A maximization pass is not permission to redesign the organism because an interesting improvement can be imagined.

## Explicit non-changes

### No trajectory organ

The project does not need a trajectory organ at this stage. Goal-relative progress can be derived from existing goal/plan, workspace, telemetry, memory, and execution results. Adding an organ solely to represent that concept would violate the feature-freeze discipline.

### No new language support

Forge remains a language-parameterized code generator and Sandbox remains constrained to its currently approved execution environments. C/Java/Kotlin support is a future **bounded extension of the existing Forge/Sandbox responsibilities**, not a reason to create new organs during this pass.

### No autonomous coding loop yet

The eventual edit → run → inspect → repair loop is part of the project goal, but implementing a new autonomous loop during this maximization pass would be a substantive capability addition. The current Forge remains the existing single-shot generation/optional validation organ.

## Remaining observations

The biggest meaningful future capability gap is not telemetry versus trajectory. It is the **closed coding iteration loop**:

```text
spec → generate → execute → observe → diagnose → modify → execute again
```

The current organs already contain much of the infrastructure required to build that later. The next step should be driven by an actual end-to-end coding experiment rather than by adding architecture speculatively.
