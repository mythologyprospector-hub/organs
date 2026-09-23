# Repository Migration Baseline

This repository is the version-controlled home for the **Organs runtime substrate**.
It was initialized from the existing `/srv/organs` implementation and its accompanying
source archive after Forge was deliberately removed from the live system.

## Deliberate import choices

- Forge source and Forge systemd units are not included.
- Generated runtime state, caches, SQLite databases, JSONL histories, and machine-local
  state are not included.
- Existing source, tests, documentation, systemd templates, and configuration examples
  are preserved as the baseline.
- Historical references in documents may remain until reviewed; historical notes are not
  to be rewritten merely to make the migration look cleaner.

## First engineering mission

Before adding new organs or major features, audit this baseline and establish the
canonical Organs v1 contracts for:

1. lifecycle and health/info behavior;
2. Registry discovery and persistence;
3. BUS/event semantics and correlation;
4. persistence ownership;
5. Critic/Executive safety boundaries;
6. Sandbox contract;
7. Telemetry contract;
8. API/error/version conventions;
9. installation/update/uninstallation and systemd ownership; and
10. testing/reproducibility requirements.

The installer must be derived from those contracts rather than becoming their source of
truth.
