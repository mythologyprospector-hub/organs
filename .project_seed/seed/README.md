# Universal Project Seed

This directory contains the portable operating constitution for projects built with Jimmy and the assistant.

The seed is intentionally **not** a project architecture.

It carries the stable relationship, workflow, communication, truth, verification, and machine conventions that should survive from one repository to the next.

## Installation

Copy the contents of this seed into a new repository.

Install the complete seed bundle:

```text
AGENTS.md
DOCS.md
HUMAN.md
MACHINE.md
ORGANS.md
README.md
```

`AGENTS.md` is the entry-point operating constitution, but it relies on the supporting references. The complete bundle preserves the owner's working relationship and Genie Principle (`HUMAN.md`), machine constants (`MACHINE.md`), documentation rules (`DOCS.md`), and Organs integration contract (`ORGANS.md`). Do not install only `AGENTS.md` and assume the full operating model is present.

## Miracle Depot

Use [Miracle Depot](https://github.com/mythologyprospector-hub/miracle-depot) when a project needs a temporary, auditable staging area for source material, bulk archives, research notes, exports, logs, or other material that should be inventoried and processed before selected results return to the authoritative project repository.

Place material only in its matching `projects/<repo-name>/incoming/` lane. Preserve originals, record provenance, put derived work in `working/`, inventories in `inventory/`, and concise evidence-based handoffs in `reports/`. Process one lane at a time; do not mix or transfer material between projects without explicit authorization. Review results before copying anything into a project's canonical repository. The depot is private but hosted on GitHub, permissions apply to the whole repository, and Git history can retain deleted material. Never store credentials or authentication secrets there.

Miracle Depot is optional infrastructure, not a required dependency. Small tasks that are better handled directly in the project should stay there. Read the depot's own `AGENTS.md` and the target lane's `README.md` before processing material.

## What does not belong here

Do not put these in the universal seed:

- project-specific architecture;
- project-specific roadmap;
- project-specific APIs;
- project-specific canon;
- project-specific tests;
- current project status;
- temporary decisions;
- repository-specific dependencies.

Those belong to the project itself.

## The intended bootstrap

```text
New repository
    ↓
Install Project Seed
    ↓
Point assistant at repository
    ↓
Human: "We're building ______."
    ↓
Assistant inspects repository
    ↓
Assistant establishes / discovers project canon
    ↓
Assistant drives the work
```

The Seed should make the relationship work without requiring the human to re-explain it.
