# Worktree Lifecycle

**Status:** Canonical
**Governs:** How agents create, identify, track, preserve, and retire temporary Git worktrees; `AGENTS.md` remains the governing operating constitution.
**Last verified:** 2026-10-13

## Purpose

Git worktrees are an optional tool for a concrete need such as parallel implementation or isolated review. They are not the normal way to work. The owner's ordinary checkout remains `~/projects/<repo>`.

A Git worktree registration remembers a checkout path and commit. It does not reliably explain why the checkout exists, which task owns it, whether local-only files matter, or when it may be removed. The workflow must supply that missing lifecycle record.

## When a worktree is justified

Prefer the existing checkout and ordinary branch workflow. Create a worktree only when isolation or genuine parallelism provides a specific benefit that cannot be achieved more simply.

Before creation:
- Inspect the current checkout, status, branch, existing registered worktrees, and destination folders.
- Reuse a suitable existing worktree rather than create a near-duplicate.
- Use `~/projects/.worktrees/<repo>/<purpose>` for temporary worktrees on Bucky.
- Give the folder a purpose-based name tied to an issue, PR, review, or clearly stated task.
- Ensure the work is represented by a GitHub issue/PR or another durable task record.

## Discovery is mandatory

At the start of local work in a repository, and before handing work off, inspect both:

1. Git's registrations using `git worktree list --porcelain`.
2. The physical contents of the repository's dedicated worktree home, if it exists.

Reconcile the two lists. A folder on disk may be unregistered, and a registered worktree may have a missing or moved directory. Never assume the main checkout is the only checkout because the conversation did not mention others.

For each worktree, inspect its path, branch or detached HEAD, status (including untracked files), relevant commit history, and relationship to local/remote branches and GitHub tasks. Do not treat `git log main..HEAD` alone as proof that a commit is lost or redundant. Do not treat a clean `git status` as proof that the worktree has no useful history.

## The active register

Create a repository-root `WORKTREES.md` when the repository has one or more worktrees whose purpose or disposition is not obvious from durable task records. Do not keep an empty register in projects that do not use worktrees. Keep the register short and operational, and update it whenever a worktree is created, repurposed, moved, becomes review-ready, or is retired.

For each entry record:

| Field | Record |
|---|---|
| Path | Worktree path/name |
| Purpose | Why it exists |
| Task | Issue/PR link or other durable task record |
| State | Branch or detached commit |
| Local state | Dirty/untracked files and commits needing preservation, or explicitly none found |
| Disposition | `ACTIVE`, `WAITING`, `REVIEW`, `INVESTIGATE`, or `CLEANUP-READY` |
| Exit condition | What must happen before retirement |
| Next action | The next responsible step |

If purpose, history, or local state is unknown, use `INVESTIGATE`. Never turn an assumption into a fact. A GitHub issue/PR may serve as the durable record instead of `WORKTREES.md` when it unambiguously tracks every active worktree and its retirement; do not duplicate the same information in multiple ledgers.

## Retirement protocol

A worktree is not disposable merely because its task looks old, it is detached, or its commits are absent from `main`.

1. Confirm the task is complete, cancelled, or superseded.
2. Inspect tracked changes, untracked files, relevant ignored files, unique commits, and local dependency/configuration differences. Check whether valuable commits are present on an appropriate remote branch or otherwise preserve them.
3. Preserve any useful or uncertain files and commits outside the worktree before removing it. Never overwrite a different local file merely because another copy appears newer.
4. Remove a confirmed disposable worktree using `git worktree remove <path>`. Never use `rm -rf`, `git worktree remove --force`, destructive resets, or history rewriting as cleanup shortcuts.
5. If Git refuses removal, stop and investigate. Do not force the removal to make the command succeed.
6. Verify `git worktree list --porcelain` and the physical worktree directory afterward. Confirm preserved artifacts still exist, then update or remove the corresponding register entry and close the task only when cleanup is truly complete.

Do not run `git worktree prune` as a substitute for understanding stale or missing registrations. Pruning removes stale metadata; it does not preserve local work or explain what happened.

## Keep the owner out of the weeds

The assistant owns discovery, interpretation, preservation planning, and cleanup coordination. Batch read-only inspection into one concise command when local filesystem access is required. Ask the owner for only the minimum local action that cannot be performed through available tools; interpret the result and drive the next step. Do not hand the owner a sequence of manual tests or make them maintain the worktree ledger.

## Related documents

- `AGENTS.md` — governing agent responsibilities and mandatory operating rules.
- `MACHINE.md` — stable Bucky filesystem locations.
