# Project Seed synchronization

This repository is the canonical source for the reusable Project Seed. The synchronization workflow sends changes to installed projects by opening pull requests; it does not merge them automatically.

## Safety model

- The workflow never replaces a target repository's active `AGENTS.md`.
- Every target receives a current reference snapshot under `.project_seed/seed/`.
- The snapshot's `AGENTS.md` is an upstream reference, **not** the active project instructions. Review its diff and adapt relevant universal changes into the target's `AGENTS.md`, preserving that project's mission, canon, safety rules, and special onboarding.
- Only explicitly mapped, shared root files are copied to their existing root paths. These are still delivered through pull requests for review.
- No project is silently changed on `main`; each target PR is the human approval gate.
- `world` and the read-only archaeology repositories are not synchronization targets.
- Miracle Depot is a staging facility, not a replacement for project canon or a place to combine unrelated project material.

## Current targets

| Repository | Root files managed by the sync PR |
|---|---|
| `wonderweave` | `DOCS.md`, `MACHINE.md`, `WORKTREE_LIFECYCLE.md` |
| `episteme` | `ORGANS.md`, `WORKTREE_LIFECYCLE.md` |
| `renaissance` | `ORGANS.md`, `WORKTREE_LIFECYCLE.md` |
| `praxis` | `ORGANS.md`, `WORKTREE_LIFECYCLE.md` |
| `organs` | `WORKTREE_LIFECYCLE.md` |
| `miracle-depot` | Reference snapshot only; no root files overwritten |

Wonderweave's `HUMAN.md` and `ORGANS.md` are intentionally excluded from root-level copying because they contain project-specific customization. Its game onboarding files are never touched by this workflow. Miracle Depot's own `AGENTS.md`, `COMMON_RULES.md`, lane instructions, and task template remain its active instructions; the upstream Seed is only a reference snapshot there.

## One-time setup

The workflow requires a fine-grained GitHub token stored as the `PROJECT_SEED_SYNC_TOKEN` Actions secret in this repository. Grant it access only to the six target repositories listed above, with **Contents: read/write** and **Pull requests: read/write** permissions. Add `miracle-depot` to the token's repository access. Do not put the token in a file or commit it.

After the secret and repository access are configured, the workflow runs whenever relevant seed files change on `main`. It can also be started manually from the repository's **Actions** tab. It creates or updates one synchronization PR per target and leaves merging to the normal review/verification process. If a target cannot be checked out, inspect the token's repository access and permissions; do not weaken permissions across unrelated repositories.
