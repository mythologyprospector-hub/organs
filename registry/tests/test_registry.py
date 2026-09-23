import json
import time


def test_register_creates_new_entry(rc):
    record = rc.register("memory", "http://localhost:8001", "0.3.0", ["add", "recall"])
    assert record["name"] == "memory"
    assert record["base_url"] == "http://localhost:8001"
    assert record["status"] == "alive"
    assert record["last_heartbeat_age_seconds"] < 1.0


def test_register_preserves_first_registered_across_reregistration(rc):
    """The heartbeat-via-upsert design's most important invariant: calling
    register() again must update last_heartbeat but NEVER move
    first_registered forward — otherwise "how long has this organ existed"
    would reset every single heartbeat."""
    first = rc.register("memory", "http://localhost:8001", "0.3.0", [])
    time.sleep(0.05)
    second = rc.register("memory", "http://localhost:8001", "0.3.0", [])

    assert second["first_registered"] == first["first_registered"]
    assert second["last_heartbeat"] > first["last_heartbeat"]


def test_register_updates_capabilities_and_version_on_reregistration(rc):
    """A re-registration should also pick up genuinely new info (e.g. an
    organ that restarted with a new version) — it's an upsert, not just
    a heartbeat ping that ignores the rest of the payload."""
    rc.register("memory", "http://localhost:8001", "0.2.0", ["add"])
    updated = rc.register("memory", "http://localhost:8001", "0.3.0", ["add", "recall", "scars"])
    assert updated["version"] == "0.3.0"
    assert updated["capabilities"] == ["add", "recall", "scars"]


def test_register_two_different_organs_are_independent(rc):
    rc.register("memory", "http://localhost:8001", "0.3.0", [])
    rc.register("critic", "http://localhost:8007", "0.1.0", [])

    all_organs = rc.list_all()
    names = {o["name"] for o in all_organs}
    assert names == {"memory", "critic"}


def test_get_unknown_organ_returns_none(rc):
    assert rc.get("nonexistent") is None


def test_get_known_organ_returns_full_record_with_status(rc):
    rc.register("memory", "http://localhost:8001", "0.3.0", ["add"])
    record = rc.get("memory")
    assert record["name"] == "memory"
    assert record["status"] == "alive"
    assert "last_heartbeat_age_seconds" in record


def test_deregister_existing_returns_true_and_removes_it(rc):
    rc.register("memory", "http://localhost:8001", "0.3.0", [])
    assert rc.deregister("memory") is True
    assert rc.get("memory") is None


def test_deregister_nonexistent_returns_false(rc):
    assert rc.deregister("nonexistent") is False


def test_list_all_sorted_by_name(rc):
    rc.register("sandbox", "http://localhost:8006", "0.1.0", [])
    rc.register("critic", "http://localhost:8007", "0.1.0", [])
    rc.register("memory", "http://localhost:8001", "0.3.0", [])

    names = [o["name"] for o in rc.list_all()]
    assert names == ["critic", "memory", "sandbox"]


def test_list_all_include_stale_true_by_default(rc):
    rc.register("memory", "http://localhost:8001", "0.3.0", [])
    # force it stale by rewinding its heartbeat directly
    rc._organs["memory"]["last_heartbeat"] = time.time() - 999
    all_organs = rc.list_all()
    assert len(all_organs) == 1
    assert all_organs[0]["status"] == "stale"


def test_list_all_include_stale_false_filters_it_out(rc):
    rc.register("memory", "http://localhost:8001", "0.3.0", [])
    rc.register("critic", "http://localhost:8007", "0.1.0", [])
    rc._organs["memory"]["last_heartbeat"] = time.time() - 999  # stale

    alive_only = rc.list_all(include_stale=False)
    names = [o["name"] for o in alive_only]
    assert names == ["critic"]


# --- staleness timing — CANON.md Section 1, item 4 ------------------------

def test_freshly_registered_organ_is_alive(rc):
    rc.register("memory", "http://localhost:8001", "0.3.0", [])
    assert rc.get("memory")["status"] == "alive"


def test_organ_past_stale_after_seconds_is_stale(rc):
    rc.register("memory", "http://localhost:8001", "0.3.0", [])
    rc._organs["memory"]["last_heartbeat"] = time.time() - (rc.STALE_AFTER_SECONDS + 5)
    assert rc.get("memory")["status"] == "stale"


def test_staleness_boundary_just_inside_threshold_is_still_alive(rc):
    """age <= STALE_AFTER_SECONDS is 'alive' — confirms the boundary
    leans toward alive, not stale. Deliberately NOT testing the exact
    boundary (age == STALE_AFTER_SECONDS precisely): `get()` calls
    time.time() itself, fractionally later than this test's own
    `now = time.time()`, so real wall-clock time always advances a hair
    between setup and assertion — an "exactly at the boundary" test
    would be inherently flaky, failing on timing noise rather than on
    anything the code actually got wrong. Landing safely inside the
    alive side (half a second of margin) tests the real guarantee
    without depending on sub-millisecond timing precision."""
    rc._organs = {}
    now = time.time()
    rc._organs["memory"] = {
        "name": "memory", "base_url": "http://localhost:8001", "version": "0.3.0",
        "capabilities": [], "first_registered": now, "last_heartbeat": now - rc.STALE_AFTER_SECONDS + 0.5,
    }
    assert rc.get("memory")["status"] == "alive"


def test_staleness_one_second_past_threshold_is_stale(rc):
    rc._organs = {}
    now = time.time()
    rc._organs["memory"] = {
        "name": "memory", "base_url": "http://localhost:8001", "version": "0.3.0",
        "capabilities": [], "first_registered": now, "last_heartbeat": now - rc.STALE_AFTER_SECONDS - 1,
    }
    assert rc.get("memory")["status"] == "stale"


# --- crash/shutdown parity — CANON.md Section 1, item 4 --------------------

def test_crash_and_clean_shutdown_are_indistinguishable(rc):
    """The core non-negotiable: there is no separate 'this organ crashed'
    state. An organ that just stops heartbeating (crash) and one that
    was cleanly deregistered look completely different in the registry
    (gone vs. aging-into-stale) — but there's no THIRD state that
    specifically means 'crashed' as opposed to 'just hasn't checked in
    yet'. This test proves that: simulate a crash (heartbeat just stops
    coming) and confirm the ONLY signal is the same staleness mechanism
    every other case uses — no special crash flag, no different code path."""
    rc.register("memory", "http://localhost:8001", "0.3.0", [])
    # simulate a crash: nothing calls deregister, nothing calls register
    # again — time just passes
    rc._organs["memory"]["last_heartbeat"] = time.time() - (rc.STALE_AFTER_SECONDS + 5)

    record = rc.get("memory")
    assert record is not None  # still present, unlike a deregistered organ
    assert record["status"] == "stale"  # same status a slow heartbeat would show
    assert "crashed" not in json.dumps(record).lower()  # no special crash state exists


# --- snapshot persistence ---------------------------------------------------

def test_snapshot_persists_across_a_simulated_restart(rc, tmp_path, monkeypatch):
    """Registering writes to disk; reloading the module (simulating a
    process restart against the SAME data dir) must pick the organ back
    up, still marked with its original first_registered."""
    rc.register("memory", "http://localhost:8001", "0.3.0", ["add"])
    original_first_registered = rc.get("memory")["first_registered"]

    import importlib
    importlib.reload(rc)  # re-runs the eager snapshot load, same REGISTRY_DATA_DIR

    record = rc.get("memory")
    assert record is not None
    assert record["first_registered"] == original_first_registered


def test_corrupt_snapshot_file_does_not_crash_on_load(rc):
    rc.SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rc.SNAPSHOT_PATH.write_text("{not valid json at all")

    import importlib
    importlib.reload(rc)  # must not raise

    assert rc.list_all() == []  # starts clean rather than crashing


def test_snapshot_file_contains_valid_json_after_register(rc):
    rc.register("memory", "http://localhost:8001", "0.3.0", [])
    raw = rc.SNAPSHOT_PATH.read_text()
    parsed = json.loads(raw)  # must not raise
    assert "memory" in parsed
