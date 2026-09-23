def test_relates_to_is_auto_resolved(mc):
    e1 = mc.op_add("the memory organ lives in /srv/organs/memory")
    e2 = mc.op_add("the registry organ lives in /srv/organs/registry")

    rel = mc.op_add_relation(e1["id"], "entry", e2["id"], "entry", "relates_to", note="both organs")
    assert rel["status"] == "resolved"


def test_contradicts_starts_unresolved(mc):
    e1 = mc.op_add("the deploy key rotates every 90 days")
    e2 = mc.op_add("the deploy key rotates every 30 days")

    rel = mc.op_add_relation(e1["id"], "entry", e2["id"], "entry", "contradicts")
    assert rel["status"] == "unresolved"

    unresolved = mc.op_list_relations(status="unresolved")
    assert len(unresolved) == 1
    assert unresolved[0]["relation_type"] == "contradicts"


def test_resolve_contradiction(mc):
    e1 = mc.op_add("claim A")
    e2 = mc.op_add("claim B")
    rel = mc.op_add_relation(e1["id"], "entry", e2["id"], "entry", "contradicts")

    mc.op_resolve_relation(rel["id"], resolved_which="b", note="B is the newer policy")

    resolved = mc.op_list_relations(status="resolved", relation_type="contradicts")
    assert len(resolved) == 1
    assert resolved[0]["resolved_which"] == "b"
    assert resolved[0]["resolution_note"] == "B is the newer policy"


def test_resolve_already_resolved_relation_errors(mc):
    e1 = mc.op_add("a")
    e2 = mc.op_add("b")
    rel = mc.op_add_relation(e1["id"], "entry", e2["id"], "entry", "contradicts")
    mc.op_resolve_relation(rel["id"], "a")
    try:
        mc.op_resolve_relation(rel["id"], "b")
        assert False
    except mc.MemoryError:
        pass


def test_invalid_relation_type_errors(mc):
    try:
        mc.op_add_relation(1, "entry", 2, "entry", "loves")
        assert False
    except mc.MemoryError:
        pass


def test_invalid_record_type_errors(mc):
    try:
        mc.op_add_relation(1, "spaceship", 2, "entry", "relates_to")
        assert False
    except mc.MemoryError:
        pass


def test_invalid_resolved_which_errors(mc):
    e1 = mc.op_add("a")
    e2 = mc.op_add("b")
    rel = mc.op_add_relation(e1["id"], "entry", e2["id"], "entry", "contradicts")
    try:
        mc.op_resolve_relation(rel["id"], "banana")
        assert False
    except mc.MemoryError:
        pass


def test_relations_can_link_across_record_types(mc):
    """A scar can contradict a fact, a promise can relate to an entry —
    the edge table doesn't care what kind of thing is on either side."""
    entry = mc.op_add("entry text")
    scar_proposal = mc.op_propose_scar(trigger_event="x", lesson="y")
    scar_id = mc.op_decide_scar(scar_proposal["id"], "accept")["scar_id"]

    rel = mc.op_add_relation(entry["id"], "entry", scar_id, "scar", "caused_by", note="this entry led to this scar")
    assert rel["type_a"] == "entry"
    assert rel["type_b"] == "scar"
    assert rel["status"] == "resolved"  # caused_by isn't a contested relation type
