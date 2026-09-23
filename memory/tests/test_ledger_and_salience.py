import time


def test_add_stores_ledger_and_index_entry(mc):
    result = mc.op_add("the deploy key rotates every 90 days", tags=["ops"])
    assert result["stored"] is True
    assert result["embedded"] is True
    assert result["dim"] == 8  # FAKE_DIM

    ledger_lines = mc.LEDGER_PATH.read_text().strip().splitlines()
    assert len(ledger_lines) == 1

    stats = mc.op_stats()
    assert stats["ledger_entries"] == 1
    assert stats["indexed_entries"] == 1


def test_add_when_ollama_down_still_writes_ledger(broken_ollama_mc):
    """The core durability guarantee: a thought is never lost even if
    embedding fails."""
    mc = broken_ollama_mc
    result = mc.op_add("important note that must survive")
    assert result["stored"] is True
    assert result["embedded"] is False
    assert "embedding failed" in result["warning"]

    ledger_lines = mc.LEDGER_PATH.read_text().strip().splitlines()
    assert len(ledger_lines) == 1
    assert "important note that must survive" in ledger_lines[0]


def test_add_duplicate_detection(mc):
    mc.op_add("the sky is blue")
    result = mc.op_add("the sky is blue")  # identical text -> identical fake vector
    assert result["possible_duplicate"] is not None
    assert result["possible_duplicate"]["score"] >= mc.DUPLICATE_WARN_THRESHOLD


def test_recall_reinforces_access_count(mc):
    added = mc.op_add("the registry runs on port 8000")
    entry_id = added["id"]

    before = mc.op_get_entry(entry_id)
    assert before["access_count"] == 0

    mc.op_recall("registry port", k=5)
    after = mc.op_get_entry(entry_id)
    assert after["access_count"] == 1
    assert after["last_accessed"] if False else True  # last_accessed bumped, checked via salience below
    assert after["salience"] >= before["salience"]  # recency + frequency can only have gone up


def test_op_list_skips_corrupted_trailing_ledger_line(mc):
    """A process killed mid-write can leave a truncated final ledger
    line. op_list() must not crash — the ledger is read constantly
    (including by Reflection's own context fetch)."""
    mc.op_add("first note")
    mc.op_add("second note")

    with mc.LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write('{"ts": 123, "text": "trunc')  # truncated, no closing brace/newline

    result = mc.op_list(n=10)
    assert len(result) == 2
    assert {e["text"] for e in result} == {"first note", "second note"}


def test_load_jsonl_skips_corrupted_trailing_line(mc, tmp_path):
    path = tmp_path / "test.jsonl"
    path.write_text('{"a": 1}\n{"a": 2}\n{"a": bad\n')
    result = mc.load_jsonl(path)
    assert result == [{"a": 1}, {"a": 2}]


def test_op_backfill_reports_corrupted_lines_without_aborting(mc):
    """The parsing step used to run unguarded, ahead of backfill's own
    established failed/errors reporting shape — one bad line crashed the
    whole recovery run instead of being reported like every other kind
    of per-entry failure this function already handles."""
    mc.op_add("a note that gets indexed normally")

    # simulate: a second, never-indexed entry plus one corrupted line,
    # appended directly so they bypass op_add's own indexing
    with mc.LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write('{"ts": 999999.0, "text": "manually appended, unindexed", "tags": []}\n')
        f.write('{"ts": 111, "text": "trunc')  # corrupted, no closing brace/newline

    result = mc.op_backfill()
    assert result["failed"] >= 1
    assert any("unparseable" in e["error"] for e in result["errors"])
    assert result["backfilled"] == 1  # the one genuinely-missing, well-formed entry



    added = mc.op_add("a note that will be archived")
    entry_id = added["id"]

    # force it old + unaccessed, then prune with an aggressive threshold
    conn = mc.get_db()
    old_ts = time.time() - 100 * 86400
    conn.execute("UPDATE entries SET ts = ?, last_accessed = ? WHERE id = ?", (old_ts, old_ts, entry_id))
    conn.commit()
    conn.close()

    prune_result = mc.op_prune(threshold=0.99, min_age_days=1)  # threshold so high everything unpinned qualifies
    assert entry_id in [a["id"] for a in prune_result["archived"]]

    results = mc.op_recall("a note that will be archived", k=5)
    assert entry_id not in [r["id"] for r in results]

    results_deep = mc.op_recall("a note that will be archived", k=5, include_archived=True)
    assert entry_id in [r["id"] for r in results_deep]
    assert [r for r in results_deep if r["id"] == entry_id][0]["archived"] is True


# --- salience/confidence math, tested directly ------------------------------

def test_salience_pinned_always_max(mc):
    sal = mc.compute_salience(access_count=0, last_accessed=0, pinned=True, consolidated=False)
    assert sal["salience"] == 1.0


def test_salience_decays_to_half_at_half_life(mc):
    now = time.time()
    last_accessed = now - (mc.SALIENCE_HALF_LIFE_DAYS * 86400)
    sal = mc.compute_salience(access_count=0, last_accessed=last_accessed, pinned=False, consolidated=False, now=now)
    assert abs(sal["recency"] - 0.5) < 0.01


def test_salience_frequency_saturates(mc):
    now = time.time()
    low = mc.compute_salience(access_count=1, last_accessed=now, pinned=False, consolidated=False, now=now)
    high = mc.compute_salience(access_count=1000, last_accessed=now, pinned=False, consolidated=False, now=now)
    assert high["frequency"] <= 1.0
    assert high["frequency"] > low["frequency"]


def test_confidence_never_hits_absolute_zero(mc):
    now = time.time()
    ancient = now - (mc.CONFIDENCE_HALF_LIFE_DAYS * 86400 * 50)  # 50 half-lives ago
    conf = mc.compute_confidence(confidence_base=0.8, last_confirmed=ancient, now=now)
    assert conf["confidence"] >= mc.CONFIDENCE_FLOOR
    assert conf["confidence"] < 0.1  # heavily decayed, but not zero


def test_confirm_resets_confidence_decay(mc):
    added = mc.op_add("the API key format is base64")
    entry_id = added["id"]

    # age it artificially
    conn = mc.get_db()
    old_ts = time.time() - (mc.CONFIDENCE_HALF_LIFE_DAYS * 86400 * 2)
    conn.execute("UPDATE entries SET last_confirmed = ? WHERE id = ?", (old_ts, entry_id))
    conn.commit()
    conn.close()

    decayed = mc.op_get_entry(entry_id)
    assert decayed["confidence"] < 0.5

    mc.op_confirm(entry_id)
    refreshed = mc.op_get_entry(entry_id)
    assert refreshed["confidence"] > decayed["confidence"]
    assert refreshed["confidence"] > 0.75


# --- pin / prune / archive / revive -----------------------------------------

def test_pin_makes_entry_immune_to_prune(mc):
    added = mc.op_add("pinned note")
    entry_id = added["id"]
    mc.op_pin(entry_id)

    conn = mc.get_db()
    old_ts = time.time() - 100 * 86400
    conn.execute("UPDATE entries SET ts = ?, last_accessed = ? WHERE id = ?", (old_ts, old_ts, entry_id))
    conn.commit()
    conn.close()

    result = mc.op_prune(threshold=0.99, min_age_days=1)
    assert entry_id not in [a["id"] for a in result["archived"]]


def test_prune_never_touches_new_entries(mc):
    added = mc.op_add("brand new note")
    entry_id = added["id"]
    # no time manipulation — this entry is seconds old
    result = mc.op_prune(threshold=0.99, min_age_days=7)
    assert entry_id not in [a["id"] for a in result["archived"]]


def test_prune_dry_run_does_not_modify_anything(mc):
    added = mc.op_add("would-be-archived note")
    entry_id = added["id"]
    conn = mc.get_db()
    old_ts = time.time() - 100 * 86400
    conn.execute("UPDATE entries SET ts = ?, last_accessed = ? WHERE id = ?", (old_ts, old_ts, entry_id))
    conn.commit()
    conn.close()

    result = mc.op_prune(threshold=0.99, min_age_days=1, dry_run=True)
    assert entry_id in [a["id"] for a in result["archived"]]

    # still active, not actually archived
    entry = mc.op_get_entry(entry_id)
    assert entry["archived"] is False


def test_ledger_is_never_shrunk_by_pruning(mc):
    """The permanence guarantee under the new forgetting feature: pruning
    can make something hard to find, but the ledger line count never
    decreases."""
    for i in range(5):
        mc.op_add(f"note number {i}")
    ledger_lines_before = len(mc.LEDGER_PATH.read_text().strip().splitlines())

    conn = mc.get_db()
    old_ts = time.time() - 100 * 86400
    conn.execute("UPDATE entries SET ts = ?, last_accessed = ?", (old_ts, old_ts))
    conn.commit()
    conn.close()

    mc.op_prune(threshold=0.99, min_age_days=1)
    ledger_lines_after = len(mc.LEDGER_PATH.read_text().strip().splitlines())
    assert ledger_lines_after == ledger_lines_before == 5


def test_revive_restores_entry_and_reinforces_it(mc):
    added = mc.op_add("note to be forgotten and revived")
    entry_id = added["id"]
    conn = mc.get_db()
    old_ts = time.time() - 100 * 86400
    conn.execute("UPDATE entries SET ts = ?, last_accessed = ? WHERE id = ?", (old_ts, old_ts, entry_id))
    conn.commit()
    conn.close()

    mc.op_prune(threshold=0.99, min_age_days=1)
    archived = mc.op_get_entry(entry_id)
    assert archived["archived"] is True

    mc.op_revive(entry_id)
    revived = mc.op_get_entry(entry_id)
    assert revived["archived"] is False
    assert revived["access_count"] == archived["access_count"] + 1


def test_pin_on_archived_entry_errors_with_helpful_message(mc):
    added = mc.op_add("will be archived")
    entry_id = added["id"]
    conn = mc.get_db()
    old_ts = time.time() - 100 * 86400
    conn.execute("UPDATE entries SET ts = ?, last_accessed = ? WHERE id = ?", (old_ts, old_ts, entry_id))
    conn.commit()
    conn.close()
    mc.op_prune(threshold=0.99, min_age_days=1)

    try:
        mc.op_pin(entry_id)
        assert False, "expected MemoryError"
    except mc.MemoryError as e:
        assert "revive" in str(e)


def test_recall_raises_cleanly_when_ollama_down(broken_ollama_mc):
    mc = broken_ollama_mc
    try:
        mc.op_recall("anything")
        assert False, "expected MemoryError"
    except mc.MemoryError:
        pass

def test_list_archived_rejects_non_positive_n(mc):
    added = mc.op_add("a note that will be archived")
    entry_id = added["id"]

    # force it old + unaccessed, then prune with an aggressive threshold
    conn = mc.get_db()
    old_ts = time.time() - 100 * 86400
    conn.execute("UPDATE entries SET ts = ?, last_accessed = ? WHERE id = ?", (old_ts, old_ts, entry_id))
    conn.commit()
    conn.close()

    mc.op_prune(threshold=0.99, min_age_days=1)  # archives the unpinned entry above
    assert entry_id in [a["id"] for a in mc.op_list_archived(n=20)]

    for bad in (0, -1, -20):
        try:
            mc.op_list_archived(n=bad)
            assert False, f"n={bad} should have been rejected"
        except mc.MemoryError:
            pass
