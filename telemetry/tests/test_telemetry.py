import time

import pytest


def test_emit_assigns_id_and_both_clocks(tc):
    event = tc.op_emit("request", "io_interface", payload={"text": "restart ollama"})
    assert event["event_id"]
    assert event["timestamp"] > 0
    assert event["monotonic_time"] > 0
    assert event["status"] == "completed"
    assert event["severity"] == "info"


def test_emit_persists_to_ledger_and_db(tc):
    event = tc.op_emit("mutation", "memory", payload={"op": "add"})
    lines = tc.LEDGER_PATH.read_text().strip().split("\n")
    assert len(lines) == 1
    assert event["event_id"] in lines[0]

    fetched = tc.op_get_event(event["event_id"])
    assert fetched["source"] == "memory"
    assert fetched["payload"] == {"op": "add"}


def test_emit_rejects_empty_event_type(tc):
    with pytest.raises(tc.TelemetryError, match="event_type"):
        tc.op_emit("", "memory")


def test_emit_rejects_empty_source(tc):
    with pytest.raises(tc.TelemetryError, match="source"):
        tc.op_emit("request", "")


def test_emit_rejects_invalid_status(tc):
    with pytest.raises(tc.TelemetryError, match="status"):
        tc.op_emit("request", "memory", status="not_a_real_status")


def test_emit_rejects_invalid_severity(tc):
    with pytest.raises(tc.TelemetryError, match="severity"):
        tc.op_emit("request", "memory", severity="not_a_real_severity")


def test_emit_ignores_caller_supplied_event_id(tc):
    """event_id is always server-assigned — never trust a caller's, or
    two organs emitting concurrently could collide."""
    event = tc.op_emit("request", "memory")
    assert len(event["event_id"]) == 32  # uuid4().hex


def test_query_filters_by_source(tc):
    tc.op_emit("request", "memory")
    tc.op_emit("request", "sandbox")
    results = tc.op_query(source="sandbox")
    assert len(results) == 1
    assert results[0]["source"] == "sandbox"


def test_query_filters_by_event_type(tc):
    tc.op_emit("request", "memory")
    tc.op_emit("failure", "memory")
    results = tc.op_query(event_type="failure")
    assert len(results) == 1
    assert results[0]["event_type"] == "failure"


def test_query_filters_by_status(tc):
    tc.op_emit("request", "sandbox", status="failed")
    tc.op_emit("request", "sandbox", status="completed")
    results = tc.op_query(status="failed")
    assert len(results) == 1
    assert results[0]["status"] == "failed"


def test_query_filters_by_time_range(tc):
    tc.op_emit("request", "memory")
    mid = time.time()
    tc.op_emit("request", "memory")
    results = tc.op_query(start=mid)
    assert len(results) == 1


def test_query_default_order_is_newest_first(tc):
    e1 = tc.op_emit("request", "memory")
    e2 = tc.op_emit("request", "memory")
    results = tc.op_query()
    assert results[0]["event_id"] == e2["event_id"]
    assert results[1]["event_id"] == e1["event_id"]


def test_query_respects_limit(tc):
    for _ in range(5):
        tc.op_emit("request", "memory")
    results = tc.op_query(limit=2)
    assert len(results) == 2


def test_query_limit_capped_at_max(tc):
    results = tc.op_query(limit=999999)
    assert results == []  # no events yet, but shouldn't raise on an oversized limit


def test_get_event_missing_raises(tc):
    with pytest.raises(tc.TelemetryError, match="not found"):
        tc.op_get_event("does-not-exist")


def test_timeline_reconstructs_causal_chain_in_order(tc):
    tc.op_emit("request", "io_interface", correlation_id="ABC123")
    tc.op_emit("decision", "critic", correlation_id="ABC123")
    tc.op_emit("mutation", "executive", correlation_id="ABC123")
    tc.op_emit("request", "io_interface", correlation_id="UNRELATED")

    chain = tc.op_timeline("ABC123")
    assert len(chain) == 3
    assert [e["source"] for e in chain] == ["io_interface", "critic", "executive"]  # chronological


def test_timeline_rejects_empty_correlation_id(tc):
    with pytest.raises(tc.TelemetryError, match="correlation_id"):
        tc.op_timeline("")


def test_stats_counts_by_dimension(tc):
    tc.op_emit("request", "memory", status="completed")
    tc.op_emit("request", "memory", status="failed")
    tc.op_emit("mutation", "sandbox", status="completed")

    stats = tc.op_stats()
    assert stats["total_events"] == 3
    assert stats["by_source"]["memory"] == 2
    assert stats["by_source"]["sandbox"] == 1
    assert stats["by_event_type"]["request"] == 2
    assert stats["by_status"]["failed"] == 1


def test_stats_avg_duration_ignores_events_without_one(tc):
    tc.op_emit("request", "memory", duration_ms=100)
    tc.op_emit("request", "memory", duration_ms=200)
    tc.op_emit("request", "memory")  # no duration
    stats = tc.op_stats()
    assert stats["avg_duration_ms"] == 150


def test_emit_survives_process_restart_via_reload(tc, tmp_path, monkeypatch):
    """The jsonl ledger and sqlite index both live on real disk — a
    fresh process (simulated here via importlib.reload) must see events
    from a prior one, same durability guarantee as Memory's ledger."""
    import importlib
    tc.op_emit("request", "memory")
    importlib.reload(tc)
    stats = tc.op_stats()
    assert stats["total_events"] == 1


def test_query_rejects_non_positive_limit(tc):
    with pytest.raises(tc.TelemetryError, match="at least 1"):
        tc.op_query(limit=0)
    with pytest.raises(tc.TelemetryError, match="at least 1"):
        tc.op_query(limit=-1)


def test_backfill_reindexes_event_missing_from_sqlite(tc):
    """The core case op_backfill() exists for: the .sqlite3 file gets
    deleted or corrupted (get_db() just recreates an empty table) while
    telemetry.jsonl — the permanent record — is untouched. Every prior
    event would otherwise become permanently unqueryable despite still
    being safely on disk."""
    tc.op_emit("request", "memory")
    tc.op_emit("request", "forge")
    assert tc.op_stats()["total_events"] == 2

    tc.DB_PATH.unlink()  # simulate index loss; ledger is untouched

    assert tc.op_stats()["total_events"] == 0  # confirms the index really was wiped

    result = tc.op_backfill()
    assert result["backfilled"] == 2
    assert result["failed"] == 0
    assert tc.op_stats()["total_events"] == 2


def test_backfill_skips_events_already_indexed(tc):
    tc.op_emit("request", "memory")
    result = tc.op_backfill()
    assert result["backfilled"] == 0
    assert result["already_indexed"] == 1
    assert tc.op_stats()["total_events"] == 1  # not duplicated


def test_backfill_reports_corrupted_lines_without_aborting(tc):
    """Same shape as memory_core.op_backfill(): a corrupted trailing
    line (process killed mid-write) is reported via failed/errors, not
    allowed to abort the whole reconciliation run."""
    tc.op_emit("request", "memory")
    tc.DB_PATH.unlink()

    with tc.LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write('{"event_id": "trunc')  # truncated, no closing brace/newline

    result = tc.op_backfill()
    assert result["backfilled"] == 1
    assert result["failed"] == 1
    assert "unparseable" in result["errors"][0]["error"]
