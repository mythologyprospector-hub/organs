def test_add_and_list_pending_promise(mc):
    p = mc.op_add_promise("remind the user about the deploy tomorrow", owner="system", condition="tomorrow")
    assert p["status"] == "pending"

    pending = mc.op_list_promises(status="pending")
    assert len(pending) == 1
    assert pending[0]["text"] == "remind the user about the deploy tomorrow"


def test_resolve_promise_fulfilled_removes_from_pending(mc):
    p = mc.op_add_promise("do the thing")
    mc.op_resolve_promise(p["id"], "fulfilled", note="done on time")

    assert mc.op_list_promises(status="pending") == []
    fulfilled = mc.op_list_promises(status="fulfilled")
    assert len(fulfilled) == 1
    assert fulfilled[0]["resolution_note"] == "done on time"


def test_resolve_promise_broken(mc):
    p = mc.op_add_promise("promise that will be broken")
    mc.op_resolve_promise(p["id"], "broken", note="ran out of time")
    broken = mc.op_list_promises(status="broken")
    assert len(broken) == 1


def test_resolve_already_resolved_promise_errors(mc):
    p = mc.op_add_promise("x")
    mc.op_resolve_promise(p["id"], "fulfilled")
    try:
        mc.op_resolve_promise(p["id"], "broken")
        assert False, "expected MemoryError"
    except mc.MemoryError:
        pass


def test_resolve_invalid_status_errors(mc):
    p = mc.op_add_promise("x")
    try:
        mc.op_resolve_promise(p["id"], "maybe")
        assert False
    except mc.MemoryError:
        pass


def test_resolve_nonexistent_promise_errors(mc):
    try:
        mc.op_resolve_promise(99999, "fulfilled")
        assert False
    except mc.MemoryError:
        pass


# --- Unknowable ----------------------------------------------------------

def test_add_unknowable_and_list(mc):
    u = mc.op_add_unknowable(
        description="there's an NDA-covered detail about the Q3 partnership",
        reason="encrypted / permission required",
        confidence_exists=0.9,
        owner_to_request="legal team",
    )
    assert u["status"] == "inaccessible"

    open_items = mc.op_list_unknowable(status="inaccessible")
    assert len(open_items) == 1
    assert open_items[0]["description"] == "there's an NDA-covered detail about the Q3 partnership"


def test_unknowable_never_stores_actual_content(mc):
    """Structural guarantee: the schema has no field for the hidden
    content itself — only description/reason/confidence metadata."""
    u = mc.op_add_unknowable(description="something exists", reason="forgotten")
    assert set(u.keys()) == {"id", "description", "reason", "confidence_exists", "owner_to_request", "status"}


def test_resolve_unknowable_links_to_real_entry(mc):
    entry = mc.op_add("the NDA detail turned out to be: vendor X was involved")
    u = mc.op_add_unknowable(description="mystery vendor", reason="was under NDA")

    mc.op_resolve_unknowable(u["id"], resolved_entry_id=entry["id"])

    assert mc.op_list_unknowable(status="inaccessible") == []
    resolved = mc.op_list_unknowable(status="resolved")
    assert len(resolved) == 1
    assert resolved[0]["resolved_entry_id"] == entry["id"]


def test_resolve_already_resolved_unknowable_errors(mc):
    u = mc.op_add_unknowable(description="x", reason="y")
    mc.op_resolve_unknowable(u["id"], resolved_entry_id=1)
    try:
        mc.op_resolve_unknowable(u["id"], resolved_entry_id=2)
        assert False
    except mc.MemoryError:
        pass


def test_add_unknowable_invalid_confidence_errors(mc):
    try:
        mc.op_add_unknowable(description="x", reason="y", confidence_exists=1.5)
        assert False
    except mc.MemoryError:
        pass
