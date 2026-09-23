"""
critic_core.py — evaluates a PROPOSED action before it runs, never after.

Deliberately deterministic, not LLM-based. A rule engine can't be talked
into approving something by clever phrasing, doesn't degrade under load,
and its reasoning is always inspectable. This is "don't build moon-shot
cognition when a small deterministic organ will accomplish the job,"
applied to the single place in the whole system where getting it wrong
matters most.

Fails closed: anything not explicitly recognized as safe or reversible
defaults to high_risk and requires human approval. An unrecognized organ,
an unrecognized endpoint pattern, or an unrecognized request shape is
treated as risky BY DEFAULT — the allowlist has to affirmatively cover
something for it to skip human review, never the other way around.

Four tiers:
    safe        — read-only, or execution that's already isolated
                  (Sandbox jobs, network off)
    reversible  — a normal write with no special permanence
                  (Memory /add, Communications /publish)
    caution     — something becoming CANON — a decide/resolve/accept
                  call that makes a fact/scar/promise/relation permanent
    high_risk   — touches real OS-level state (Orchestrator start/stop/
                  restart), or a Sandbox job with network enabled

Only "safe" and "reversible" can auto-proceed. "caution" and "high_risk"
ALWAYS require a human decision — Critic can recommend, it can never
itself authorize something risky.
"""
import re

RISK_TIERS = ("safe", "reversible", "caution", "high_risk")

# Order matters: first matching rule wins. Fail-closed means the LAST
# rule is always "anything else -> high_risk".
_RULES = [
    # (method, path_regex, condition_fn_or_None, tier, reasoning)
    ("GET", r".*", None, "safe", "read-only request"),

    ("POST", r"^/memory/add$", None, "reversible", "a new ledger entry — never overwrites anything"),
    ("POST", r"^/memory/entries/\d+/confirm$", None, "reversible", "resets a confidence decay clock, doesn't change content"),
    ("POST", r"^/bus/.*", None, "reversible", "bus publish/consume — no permanent state outside the bus itself"),
    ("POST", r"^/sandbox/jobs$",
     lambda body: not (body or {}).get("network", False),
     "safe", "isolated, ephemeral, network-off sandbox job"),
    ("POST", r"^/sandbox/jobs$",
     lambda body: (body or {}).get("network", False) is True,
     "caution", "sandbox job with network enabled — isolation is weaker with network on"),
    ("POST", r"^/reflection/(enable|disable|configure)$", None, "reversible", "toggles a setting, reversible at any time"),
    ("POST", r"^/reflection/tick$", None, "reversible", "one manual reflection cycle, writes a low-confidence entry"),

    # Sensei's mode toggle is the whole point of the "instant mute" design —
    # if this fell through to the fail-closed default it would require an
    # Executive approval round-trip just to go quiet, which defeats it
    # entirely. Same reasoning as reflection's enable/disable above: purely
    # local, ephemeral, and trivially reversible.
    ("POST", r"^/sensei/mode$", None, "reversible", "toggles Sensei's watching/ready mode, reversible at any time"),
    ("POST", r"^/sensei/nudge$", None, "reversible", "records a candidate nudge and decides delivery vs. suppression — no permanent state"),
    ("POST", r"^/sensei/detect/shell$", None, "reversible", "runs stateless chain detection and routes any candidate through the same nudge gate — same tier as calling /sensei/nudge directly"),
    ("POST", r"^/sensei/detect/editor$", None, "reversible", "runs stateless undo-storm detection and routes any candidate through the same nudge gate — same tier as /sensei/detect/shell"),
    ("POST", r"^/sensei/respond$", None, "reversible", "records accept/reject of a nudge, writes a low-confidence memory entry — same tier as reflection tick"),

    ("POST", r"^/memory/proposals/[^/]+/decide$", None, "caution", "accepting this makes a fact canon"),
    ("POST", r"^/memory/scars/proposals/[^/]+/decide$", None, "caution", "accepting this makes a scar permanent, possibly superseding another"),
    ("POST", r"^/memory/promises/\d+/resolve$", None, "caution", "closes out a tracked commitment permanently"),
    ("POST", r"^/memory/unknowable/\d+/resolve$", None, "caution", "marks something permanently resolved"),
    ("POST", r"^/memory/relations/\d+/resolve$", None, "caution", "settles a contradiction — a canon decision about what's true"),
    ("POST", r"^/memory/(entries/\d+/pin|prune|backfill)$", None, "caution", "changes what's findable at a structural level"),
    ("POST", r"^/memory/entries/\d+/revive$", None, "caution", "reverses an archive decision — same structural-findability category as pin"),
    ("DELETE", r"^/memory/entries/\d+/pin$", None, "caution", "unpin — the reverse of pin, same tier as the action it undoes, not the DELETE-default"),

    # These create a PROPOSAL or a tracked record, not a canon decision —
    # the actual permanence happens at the separate .../decide or
    # .../resolve call above, which is already gated. Gating the
    # proposal/creation step too would be redundant, not more careful.
    ("POST", r"^/memory/consolidate$", None, "reversible", "creates fact proposals only — deciding them is the gated step"),
    ("POST", r"^/memory/scars/propose$", None, "reversible", "creates a scar proposal only — deciding it is the gated step"),
    ("POST", r"^/memory/promises$", None, "reversible", "creates a tracked commitment — resolving it permanently is the gated step"),
    ("POST", r"^/memory/unknowable$", None, "reversible", "creates a tracked placeholder — resolving it permanently is the gated step"),
    ("POST", r"^/memory/relations$", None, "reversible", "creates a tracked relation — resolving it permanently is the gated step"),

    ("POST", r"^/introspect/refresh$", None, "safe", "re-runs read-only collectors (docker ps, ollama list, etc.) — no state changes"),
    ("POST", r"^/telemetry/backfill$", None, "caution", "reconciles the queryable index against the permanent ledger — same tier as memory's own backfill, which does the analogous job"),

    ("POST", r"^/orchestrator/services/[^/]+/(start|stop|restart)$", None, "high_risk", "touches a real OS-level service"),
    ("DELETE", r".*", None, "high_risk", "deletion of any kind — default deny"),
]


class CriticError(Exception):
    pass


def evaluate(organ: str, method: str, path: str, body: dict = None):
    if not organ or not method or not path:
        raise CriticError("organ, method, and path are all required")
    method = method.upper()

    for rule_method, pattern, condition, tier, reasoning in _RULES:
        if rule_method != method:
            continue
        if not re.match(pattern, path):
            continue
        if condition is not None and not condition(body):
            continue
        return _result(organ, method, path, tier, reasoning, matched=True)

    # fail closed — nothing matched, treat as the riskiest category
    return _result(organ, method, path, "high_risk",
                    "no rule recognized this organ/endpoint — failing closed, unknown actions default to risky",
                    matched=False)


def _result(organ, method, path, tier, reasoning, matched):
    return {
        "organ": organ, "method": method, "path": path,
        "risk_tier": tier,
        "requires_human_approval": tier in ("caution", "high_risk"),
        "reasoning": reasoning,
        "rule_matched": matched,
    }


def list_rules():
    """For transparency — anyone should be able to see the actual rule
    set, not just trust that it exists."""
    return [
        {"method": m, "path_pattern": p, "has_condition": c is not None, "tier": t, "reasoning": r}
        for (m, p, c, t, r) in _RULES
    ]
