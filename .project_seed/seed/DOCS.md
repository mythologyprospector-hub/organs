# Document Standard

This file is part of the universal Project Seed.

It defines how documents in any repository are shaped, and how the repository presents itself publicly, so that every project reads the same way. It says nothing about what any project contains.

A project may add document rules of its own. It may not quietly loosen these. If a project needs an exception, it records the exception in its own governing documentation.

## Format

- Markdown (`.md`), UTF-8, Unix line endings.
- No trailing whitespace.
- One blank line between sections.

## Naming

Use uppercase filenames for top-level governing documents whose names are established concepts, such as `README.md`, `AGENTS.md`, `CANON.md`, `ARCHITECTURE.md`, and `ROADMAP.md`. Use a document only if the project actually needs it.

Use scoped lowercase paths, such as `docs/`, for supporting material.

One document per purpose. Update the canonical file instead of creating a copy. Never create names such as `*_new_final.md`.

## Header

Every governing document begins with a title and three status lines:

```markdown
# Title

**Status:** Proposed | Canonical | Deprecated | Superseded
**Governs:** one line saying what this covers and what outranks it
**Last verified:** YYYY-MM-DD
```

`Last verified` means someone checked the document against the actual state of the project on that date. It does not mean the file was last edited.

`README.md` is exempt. It may begin with an optional banner image, then a title and a one-line tagline.

## Structure

- One H1 per document.
- H2 for major sections, H3 for subsections. Never skip a level.
- Lead with what matters: what it is, why it matters, what comes next.
- Preferred order: Purpose, Boundary, Body, Non-claims or open questions, Related documents.

## Status language

Use these terms precisely:

- **Proposed** — suggested, not adopted.
- **Canonical** — currently governing.
- **Implemented** — exists in code or practice.
- **Verified** — demonstrated by a test, check, or result.
- **Deprecated** — kept for history, no longer preferred.
- **Superseded** — replaced by a newer recorded decision.

Keep intended, implemented, demonstrated, and possible separate. Never call something complete because it exists. A claim of completion links to its evidence.

## Style

- Plain language, short sentences, minimal jargon.
- Explain a thing once and link to it elsewhere.
- Use repository-relative links.
- Use backticks for filenames, paths, commands, identifiers, and configuration keys.
- Use fenced code blocks, with a language tag, for multi-line examples.
- Use tables only for real comparisons.
- No decorative emoji. Bold sparingly.

## Drift controls

- Current status lives in one place. Other documents link to it and do not restate it.
- A change that alters behavior updates its documents in the same commit.
- Numbered items, such as principles or decisions, are unique and sequential.
- A document must not promise a capability the project cannot yet demonstrate.
- If two documents disagree, do not silently pick one. Resolve the conflict in the document that governs the topic.

## Before committing a document

- Is this the right source of truth, and does another document already say it?
- Does it agree with the project's governing documents?
- Does it use any undefined term?
- Does it separate fact, interpretation, proposal, and unknown?
- Does it avoid promising anything unimplemented?

## Social preview image

Every public repository hosted on GitHub has a social preview image. A repository is not considered launch-ready without one.

Requirements, per GitHub's documentation at the time of writing (verify against GitHub's current documentation if in doubt):

- **Format:** PNG, JPG, or GIF.
- **File size:** under 1 MB.
- **Resolution:** 1280 × 640 pixels (2:1) for best display. 640 × 320 pixels is the minimum recommended.
- **Background:** solid is recommended. PNG transparency is supported, but renders differently on light and dark backgrounds.

Keep the source image in the repository, for example under `assets/`, so it can be uploaded again.

The image cannot be applied by committing a file. GitHub documents only one way to set it: **Settings → Social preview → Edit → Upload an image**. The human performs that step.

The assistant therefore prepares the image, checks it against the requirements above, and gives the human the upload instruction. The assistant does not report the image as applied, or the repository as launch-ready, until the human confirms the upload.

GitHub shares the image only from a public repository. A private repository can hold an image only if one was uploaded before.

## Guiding rule

> **Sharp documentation is not decoration. It is drift control.**
