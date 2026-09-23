def test_consolidate_creates_pending_proposal_from_similar_cluster(mc):
    # identical text -> identical fake vectors -> clusters together
    for _ in range(3):
        mc.op_add("the deploy key rotates every 90 days")

    result = mc.op_consolidate(threshold=0.80, min_witnesses=3)
    assert result["proposals_created"] == 1

    proposals = mc.op_list_proposals(status="pending")
    assert len(proposals) == 1
    assert proposals[0]["cluster_size"] == 3


def test_decide_proposal_accept_creates_fact(mc):
    for _ in range(3):
        mc.op_add("always back up before migration")
    mc.op_consolidate(threshold=0.80, min_witnesses=3)
    proposal = mc.op_list_proposals(status="pending")[0]

    mc.op_decide_proposal(proposal["id"], "accept")
    facts = mc.op_facts()
    assert len(facts) == 1
    assert facts[0]["source_ids"] == proposal["source_ids"]


def test_decide_proposal_skip_creates_no_fact(mc):
    for _ in range(3):
        mc.op_add("this cluster gets skipped")
    mc.op_consolidate(threshold=0.80, min_witnesses=3)
    proposal = mc.op_list_proposals(status="pending")[0]

    mc.op_decide_proposal(proposal["id"], "skip")
    assert mc.op_facts() == []


def test_decide_unknown_proposal_errors(mc):
    try:
        mc.op_decide_proposal("nonexistent", "accept")
        assert False
    except mc.MemoryError:
        pass


# --- Scars -------------------------------------------------------------

def test_propose_and_accept_scar_creates_active_scar(mc):
    proposal = mc.op_propose_scar(
        trigger_event="Google Trends API returned stale data",
        lesson="Never trust trend data older than 6 hours without freshness verification",
        confidence=0.95,
    )
    assert proposal["status"] == "pending"

    decided = mc.op_decide_scar(proposal["id"], "accept")
    assert decided["status"] == "accepted"
    assert "scar_id" in decided

    active = mc.op_list_scars(status="active")
    assert len(active) == 1
    assert active[0]["lesson"].startswith("Never trust trend data")
    assert active[0]["status"] == "active"


def test_reject_scar_proposal_creates_no_scar(mc):
    proposal = mc.op_propose_scar(trigger_event="a false alarm", lesson="this should not become canon")
    mc.op_decide_scar(proposal["id"], "reject")
    assert mc.op_list_scars(status="active") == []


def test_decide_scar_twice_errors(mc):
    proposal = mc.op_propose_scar(trigger_event="x", lesson="y")
    mc.op_decide_scar(proposal["id"], "accept")
    try:
        mc.op_decide_scar(proposal["id"], "accept")
        assert False, "expected MemoryError on already-decided proposal"
    except mc.MemoryError:
        pass


def test_supersede_marks_old_scar_superseded_but_keeps_it_readable(mc):
    p1 = mc.op_propose_scar(trigger_event="deploy key rotation confusion",
                             lesson="Rotate the deploy key every 90 days")
    d1 = mc.op_decide_scar(p1["id"], "accept")
    old_scar_id = d1["scar_id"]

    p2 = mc.op_propose_scar(trigger_event="policy actually changed",
                             lesson="Rotate the deploy key every 30 days",
                             supersedes=old_scar_id)
    d2 = mc.op_decide_scar(p2["id"], "accept")
    new_scar_id = d2["scar_id"]

    active = mc.op_list_scars(status="active")
    assert len(active) == 1
    assert active[0]["id"] == new_scar_id

    superseded = mc.op_list_scars(status="superseded")
    assert len(superseded) == 1
    assert superseded[0]["id"] == old_scar_id
    assert superseded[0]["superseded_by"] == new_scar_id
    # the old lesson is still readable, not deleted
    assert "90 days" in superseded[0]["lesson"]


def test_cannot_supersede_an_already_superseded_scar(mc):
    p1 = mc.op_propose_scar(trigger_event="a", lesson="v1")
    old_id = mc.op_decide_scar(p1["id"], "accept")["scar_id"]

    p2 = mc.op_propose_scar(trigger_event="b", lesson="v2", supersedes=old_id)
    mc.op_decide_scar(p2["id"], "accept")

    p3 = mc.op_propose_scar(trigger_event="c", lesson="v3 trying to supersede v1 again", supersedes=old_id)
    try:
        mc.op_decide_scar(p3["id"], "accept")
        assert False, "expected MemoryError: v1 is already superseded"
    except mc.MemoryError:
        pass


def test_supersede_nonexistent_scar_errors(mc):
    p = mc.op_propose_scar(trigger_event="a", lesson="b", supersedes=99999)
    try:
        mc.op_decide_scar(p["id"], "accept")
        assert False
    except mc.MemoryError:
        pass
