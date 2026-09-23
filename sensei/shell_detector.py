"""
shell_detector.py — the first real detector in Sensei's Observe -> Detect
-> Nudge loop (Digital_Sensei.md's core loop, still marked "future work"
in this organ's own README until now).

Deliberately a pure function over a plain list of strings, same
"deterministic, not LLM-based, always inspectable" philosophy critic_core.py
uses for the same reason: a detector that sometimes flags a pattern and
sometimes doesn't for the identical input is worse than useless — it
erodes trust in every nudge that follows. This module knows nothing about
HTTP, Sensei's state files, or delivery; main.py's /sensei/detect/shell
endpoint is the only thing that wires it to the real op_nudge pipeline,
exactly the same separation reflection_core and sensei_core already keep
between detection/decision logic and the organs they end up talking to.

What it finds: a CONTIGUOUS block of N consecutive shell commands that
recurs, verbatim, at least min_repeats times within the given history.
This is deliberately narrower than "these commands often appear together
somewhere in my history" (much noisier, much harder to justify a nudge
for) — it is Digital_Sensei.md's own example verbatim: "repeated chain ->
alias/script".
"""
import hashlib

DEFAULT_CHAIN_LENGTHS = (4, 3, 2)  # longest first — see _drop_redundant_subchains
DEFAULT_MIN_REPEATS = 3


def _ngram_counts(commands, length):
    counts = {}
    for i in range(len(commands) - length + 1):
        chain = tuple(commands[i:i + length])
        counts[chain] = counts.get(chain, 0) + 1
    return counts


def _is_subchain(shorter, longer):
    """True if `shorter` appears as a contiguous run inside `longer`."""
    n, m = len(shorter), len(longer)
    if n > m:
        return False
    return any(longer[i:i + n] == shorter for i in range(m - n + 1))


def _drop_redundant_subchains(candidates):
    """candidates is already sorted longest-chain-first, highest-repeats-first.
    A shorter chain that's fully contained in an already-accepted longer
    chain is redundant noise (e.g. don't separately nudge about `[A, B]`
    once `[A, B, C]` repeating 3x has already been flagged) — drop it."""
    accepted = []
    for c in candidates:
        if any(_is_subchain(c["chain"], a["chain"]) for a in accepted):
            continue
        accepted.append(c)
    return accepted


def find_repeated_chains(commands, chain_lengths=DEFAULT_CHAIN_LENGTHS, min_repeats=DEFAULT_MIN_REPEATS):
    """commands: chronological list of str, oldest first, exactly as typed
    (already stripped of shell-specific noise like history line numbers —
    that's the watcher script's job, not this function's).

    Returns candidates sorted by (chain_length, repeats) descending, each:
        {"chain": (cmd, ...), "chain_length": int, "repeats": int}
    """
    if not commands:
        return []

    raw = []
    for length in chain_lengths:
        if length < 2 or length > len(commands):
            continue
        for chain, count in _ngram_counts(commands, length).items():
            if count >= min_repeats:
                raw.append({"chain": chain, "chain_length": length, "repeats": count})

    raw.sort(key=lambda c: (c["chain_length"], c["repeats"]), reverse=True)
    return _drop_redundant_subchains(raw)


def chain_key(chain):
    """Stable, compact identifier for a chain — used to remember 'already
    suggested this one' across calls without persisting arbitrarily long
    command text as the dict key itself."""
    joined = "\x1f".join(chain)  # unit separator: won't collide with real command text
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def format_chain_message(candidate):
    chain = candidate["chain"]
    repeats = candidate["repeats"]
    preview = " && ".join(chain)
    if len(preview) > 120:
        preview = preview[:117] + "..."
    return f"Ran `{preview}` {repeats} times — want an alias or script for that chain?"
