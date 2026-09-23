def test_get_is_always_safe(cc):
    for path in ["/memory/recall", "/memory/stats", "/introspect/summary", "/anything/at/all"]:
        result = cc.evaluate("memory", "GET", path)
        assert result["risk_tier"] == "safe"
        assert result["requires_human_approval"] is False


def test_unrecognized_action_fails_closed_to_high_risk(cc):
    """The single most important test in this file: anything not
    explicitly on the allowlist must default to the RISKIEST tier, not
    the safest. The allowlist has to affirmatively cover something —
    absence of a match is never treated as permission."""
    result = cc.evaluate("some_future_organ", "POST", "/some/totally/unrecognized/endpoint")
    assert result["risk_tier"] == "high_risk"
    assert result["requires_human_approval"] is True
    assert result["rule_matched"] is False


def test_memory_add_is_reversible(cc):
    result = cc.evaluate("memory", "POST", "/memory/add", {"text": "a note"})
    assert result["risk_tier"] == "reversible"
    assert result["requires_human_approval"] is False


def test_communications_publish_is_reversible(cc):
    result = cc.evaluate("communications", "POST", "/bus/topics/x/publish", {})
    assert result["risk_tier"] == "reversible"


def test_sensei_mode_toggle_is_reversible_not_gated(cc):
    """The whole point of Sensei's mute button is that it's instant —
    if this endpoint fell through to the fail-closed default it would
    require an Executive approval round-trip just to go quiet."""
    result = cc.evaluate("sensei", "POST", "/sensei/mode", {"mode": "ready"})
    assert result["risk_tier"] == "reversible"
    assert result["requires_human_approval"] is False


def test_sensei_nudge_and_respond_are_reversible(cc):
    for path, body in [
        ("/sensei/nudge", {"kind": "shell", "message": "x", "source": "shell_watcher"}),
        ("/sensei/respond", {"nudge_ts": 1.0, "accepted": True}),
    ]:
        result = cc.evaluate("sensei", "POST", path, body)
        assert result["risk_tier"] == "reversible"
        assert result["requires_human_approval"] is False


def test_sandbox_job_network_off_is_safe(cc):
    result = cc.evaluate("sandbox", "POST", "/sandbox/jobs", {"language": "python", "network": False})
    assert result["risk_tier"] == "safe"
    assert result["requires_human_approval"] is False


def test_sandbox_job_network_on_is_caution(cc):
    """The exact case worth being careful about: the SAME endpoint
    changes risk tier based on request content, not just the path."""
    result = cc.evaluate("sandbox", "POST", "/sandbox/jobs", {"language": "python", "network": True})
    assert result["risk_tier"] == "caution"
    assert result["requires_human_approval"] is True


def test_sandbox_job_missing_network_field_defaults_safe(cc):
    """network defaults to False when absent, matching Sandbox's own
    API default — the two organs must agree on what "default" means."""
    result = cc.evaluate("sandbox", "POST", "/sandbox/jobs", {"language": "python"})
    assert result["risk_tier"] == "safe"


def test_fact_decide_is_caution(cc):
    result = cc.evaluate("memory", "POST", "/memory/proposals/abc123/decide", {"decision": "accept"})
    assert result["risk_tier"] == "caution"
    assert result["requires_human_approval"] is True


def test_scar_decide_is_caution(cc):
    result = cc.evaluate("memory", "POST", "/memory/scars/proposals/abc123/decide", {"decision": "accept"})
    assert result["risk_tier"] == "caution"


def test_promise_resolve_is_caution(cc):
    result = cc.evaluate("memory", "POST", "/memory/promises/1/resolve", {"status": "fulfilled"})
    assert result["risk_tier"] == "caution"


def test_relation_resolve_is_caution(cc):
    result = cc.evaluate("memory", "POST", "/memory/relations/1/resolve", {"resolved_which": "a"})
    assert result["risk_tier"] == "caution"


def test_orchestrator_start_stop_restart_is_high_risk(cc):
    for action in ("start", "stop", "restart"):
        result = cc.evaluate("orchestrator", "POST", f"/orchestrator/services/ollama/{action}")
        assert result["risk_tier"] == "high_risk"
        assert result["requires_human_approval"] is True


def test_delete_is_always_high_risk(cc):
    result = cc.evaluate("memory", "DELETE", "/memory/entries/1")
    assert result["risk_tier"] == "high_risk"


def test_only_safe_and_reversible_skip_human_approval(cc):
    """Structural guarantee: caution and high_risk NEVER auto-proceed,
    regardless of which specific rule matched."""
    for tier_result in [
        cc.evaluate("x", "GET", "/anything"),
        cc.evaluate("memory", "POST", "/memory/add", {}),
    ]:
        assert tier_result["requires_human_approval"] is False

    for tier_result in [
        cc.evaluate("memory", "POST", "/memory/promises/1/resolve", {}),
        cc.evaluate("orchestrator", "POST", "/orchestrator/services/x/stop"),
        cc.evaluate("unknown", "POST", "/nonsense"),
    ]:
        assert tier_result["requires_human_approval"] is True


def test_missing_required_fields_errors(cc):
    try:
        cc.evaluate("", "GET", "/x")
        assert False
    except cc.CriticError:
        pass


def test_list_rules_is_transparent(cc):
    rules = cc.list_rules()
    assert len(rules) > 0
    assert all("tier" in r and "reasoning" in r for r in rules)


def test_memory_revive_is_caution(cc):
    """Symmetric with pin — reverses an archive decision, same
    structural-findability category, not a lower tier just because
    it's the 'undo' direction."""
    result = cc.evaluate("memory", "POST", "/memory/entries/42/revive")
    assert result["risk_tier"] == "caution"


def test_memory_unpin_is_caution_not_default_delete_high_risk(cc):
    """A DELETE that undoes an already-caution-tier pin should stay at
    that same tier — not fall into the generic 'DELETE .* = high_risk'
    default just because of the HTTP verb."""
    result = cc.evaluate("memory", "DELETE", "/memory/entries/42/pin")
    assert result["risk_tier"] == "caution"
    assert result["rule_matched"] is True


def test_memory_proposal_creation_steps_are_reversible_not_the_decide_step(cc):
    """consolidate/scars-propose/promises/unknowable/relations all
    create a PROPOSAL or tracked record — the actual permanence is a
    separate .../decide or .../resolve call that's already gated.
    Gating the creation step too would be redundant, not safer."""
    for path in ["/memory/consolidate", "/memory/scars/propose", "/memory/promises",
                 "/memory/unknowable", "/memory/relations"]:
        result = cc.evaluate("memory", "POST", path, {})
        assert result["risk_tier"] == "reversible", f"{path} should be reversible"


def test_introspect_refresh_is_safe(cc):
    result = cc.evaluate("introspection", "POST", "/introspect/refresh")
    assert result["risk_tier"] == "safe"


def test_telemetry_backfill_is_caution(cc):
    """Same tier as memory's own backfill — reconciling an index
    against a permanent ledger is the same semantic action regardless
    of which organ's ledger it is."""
    result = cc.evaluate("telemetry", "POST", "/telemetry/backfill")
    assert result["risk_tier"] == "caution"


def test_every_communications_mutating_endpoint_matches_a_real_rule(cc):
    """Regression test for a real bug: Critic's own rule for
    Communications was written against a path prefix (/communications/)
    that doesn't match Communications' actual routes (/bus/). The rule
    never matched anything real, and the bug slipped through because
    the ORIGINAL test for it used the same wrong path — testing that
    the rule matched itself, not that it matched anything Communications
    actually exposes. Harmless while Critic's classification was purely
    advisory; became a real system-wide bug the moment the shared risk
    gate started actually enforcing it (see shared/organ_base.py) — it
    would have silently rejected every bus publish/dispatch/reset call
    from every organ. This walks every one of Communications' real
    mutating endpoints and confirms each one hits an explicit rule,
    not the high_risk default-deny fallthrough."""
    real_mutating_paths = [
        "/bus/topics/some-topic/publish",
        "/bus/consumers/some-consumer/topics/some-topic/reset",
        "/bus/dispatch",
        "/bus/dispatch/some-key/reset",
    ]
    for path in real_mutating_paths:
        result = cc.evaluate("communications", "POST", path, {})
        assert result["rule_matched"] is True, f"{path} fell through to the high_risk default"
        assert result["risk_tier"] == "reversible"
