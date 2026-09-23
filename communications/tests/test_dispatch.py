def test_round_robin_cycles_fairly(cc):
    candidates = ["org_a", "org_b", "org_c"]
    picks = [cc.op_dispatch("job", candidates, "round_robin")["selected"][0] for _ in range(6)]
    assert picks == ["org_a", "org_b", "org_c", "org_a", "org_b", "org_c"]


def test_round_robin_state_is_per_dispatch_key(cc):
    cc.op_dispatch("job_x", ["a", "b"], "round_robin")  # advances job_x to index 0
    first_y = cc.op_dispatch("job_y", ["a", "b"], "round_robin")["selected"][0]
    # job_y is independent — starts fresh regardless of job_x's state
    assert first_y == "a"


def test_round_robin_persists_across_calls(cc):
    cc.op_dispatch("job", ["a", "b", "c"], "round_robin")
    cc.op_dispatch("job", ["a", "b", "c"], "round_robin")
    third = cc.op_dispatch("job", ["a", "b", "c"], "round_robin")
    assert third["selected"][0] == "c"


def test_random_picks_from_candidates(cc):
    for _ in range(20):
        result = cc.op_dispatch("job", ["a", "b", "c"], "random")
        assert result["selected"][0] in ("a", "b", "c")


def test_broadcast_returns_all_candidates(cc):
    result = cc.op_dispatch("job", ["a", "b", "c"], "broadcast")
    assert result["selected"] == ["a", "b", "c"]


def test_dispatch_empty_candidates_errors(cc):
    try:
        cc.op_dispatch("job", [], "round_robin")
        assert False
    except cc.CommError:
        pass


def test_dispatch_invalid_strategy_errors(cc):
    try:
        cc.op_dispatch("job", ["a"], "coinflip")
        assert False
    except cc.CommError:
        pass


def test_reset_dispatch_restarts_rotation(cc):
    cc.op_dispatch("job", ["a", "b"], "round_robin")  # -> a
    cc.op_dispatch("job", ["a", "b"], "round_robin")  # -> b
    cc.op_reset_dispatch("job")
    result = cc.op_dispatch("job", ["a", "b"], "round_robin")
    assert result["selected"][0] == "a"


def test_round_robin_handles_changing_candidate_list_gracefully(cc):
    """If candidates change between calls, the index still applies —
    documents actual behavior rather than pretending it doesn't happen."""
    cc.op_dispatch("job", ["a", "b", "c"], "round_robin")  # index 0 -> a
    result = cc.op_dispatch("job", ["x", "y"], "round_robin")  # index 1 -> y
    assert result["selected"][0] == "y"
