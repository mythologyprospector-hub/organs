def test_disabled_by_default(rc):
    """The whole safety story starts here — a fresh install must never
    mutter without being explicitly told to."""
    state = rc.load_state()
    assert state["enabled"] is False


def test_enable_and_disable(rc):
    rc.op_enable()
    assert rc.load_state()["enabled"] is True
    rc.op_disable()
    assert rc.load_state()["enabled"] is False


def test_tick_respects_disabled_toggle_by_default(rc):
    """The unforced path — what the background loop actually calls —
    must refuse to run at all while disabled."""
    calls = {"fetch": 0, "generate": 0, "write": 0}

    def fetch(n, c):
        calls["fetch"] += 1
        return "some context"

    def generate(prompt):
        calls["generate"] += 1
        return "a thought"

    def write(text):
        calls["write"] += 1
        return {"stored": True}

    result = rc.op_tick(fetch, generate, write, force=False)
    assert result["ran"] is False
    assert calls == {"fetch": 0, "generate": 0, "write": 0}


def test_force_tick_runs_even_while_disabled(rc):
    def fetch(n, c):
        return "some context"

    def generate(prompt):
        return "a thought"

    def write(text):
        return {"stored": True, "id": 1}

    result = rc.op_tick(fetch, generate, write, force=True)
    assert result["ran"] is True
    assert result["success"] is True
    assert result["thought"] == "a thought"


def test_tick_runs_when_enabled_without_force(rc):
    rc.op_enable()

    def fetch(n, c):
        return "context"

    def generate(prompt):
        return "thought"

    def write(text):
        return {"ok": True}

    result = rc.op_tick(fetch, generate, write, force=False)
    assert result["ran"] is True
    assert result["success"] is True


def test_empty_context_skips_without_calling_model(rc):
    calls = {"generate": 0}

    def fetch(n, c):
        return ""  # nothing to reflect on

    def generate(prompt):
        calls["generate"] += 1
        return "shouldn't happen"

    def write(text):
        return {}

    result = rc.op_tick(fetch, generate, write, force=True)
    assert result["success"] is True
    assert result.get("skipped") is True
    assert calls["generate"] == 0


def test_empty_thought_skips_without_writing(rc):
    calls = {"write": 0}

    def fetch(n, c):
        return "context"

    def generate(prompt):
        return "   "  # model returned nothing useful

    def write(text):
        calls["write"] += 1
        return {}

    result = rc.op_tick(fetch, generate, write, force=True)
    assert result["success"] is True
    assert result.get("skipped") is True
    assert calls["write"] == 0


def test_fetch_context_failure_does_not_crash_and_is_recorded(rc):
    def fetch(n, c):
        raise RuntimeError("memory unreachable")

    def generate(prompt):
        return "unreachable"

    def write(text):
        return {}

    result = rc.op_tick(fetch, generate, write, force=True)
    assert result["success"] is False
    assert result["stage"] == "fetch_context"
    assert "memory unreachable" in result["error"]


def test_generate_failure_does_not_crash_and_is_recorded(rc):
    def fetch(n, c):
        return "context"

    def generate(prompt):
        raise RuntimeError("ollama down")

    def write(text):
        return {}

    result = rc.op_tick(fetch, generate, write, force=True)
    assert result["success"] is False
    assert result["stage"] == "generate"


def test_write_failure_does_not_crash_and_is_recorded(rc):
    def fetch(n, c):
        return "context"

    def generate(prompt):
        return "a real thought"

    def write(text):
        raise RuntimeError("memory rejected the write")

    result = rc.op_tick(fetch, generate, write, force=True)
    assert result["success"] is False
    assert result["stage"] == "write"
    assert result["thought"] == "a real thought"  # not lost, just not stored


def test_history_records_every_tick_newest_first(rc):
    def fetch(n, c):
        return "context"

    def generate(prompt):
        return "thought"

    def write(text):
        return {}

    rc.op_tick(fetch, generate, write, force=True)
    rc.op_tick(fetch, generate, write, force=True)
    rc.op_tick(fetch, generate, write, force=True)

    history = rc.load_history(n=10)
    assert len(history) == 3
    assert history[0]["ts"] >= history[1]["ts"] >= history[2]["ts"]


def test_load_history_skips_corrupted_trailing_line(rc):
    """A process killed mid-write (kill -9, disk full, power loss) can
    leave a truncated final line in the append-only history file. That
    must not take down load_history() — or op_get_status(), which calls
    it internally and would otherwise go down with it."""
    def fetch(n, c):
        return "context"

    def generate(prompt):
        return "thought"

    def write(text):
        return {}

    rc.op_tick(fetch, generate, write, force=True)
    rc.op_tick(fetch, generate, write, force=True)

    with rc.HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write('{"ran": true, "succ')  # truncated, no trailing newline

    history = rc.load_history(n=10)
    assert len(history) == 2  # the two good entries, corrupted one silently skipped

    status = rc.op_get_status()  # must not raise
    assert status["run_count"] == 3  # line count is unaffected, only parsing is defensive


def test_status_reports_last_run(rc):
    def fetch(n, c):
        return "context"

    def generate(prompt):
        return "thought"

    def write(text):
        return {}

    rc.op_tick(fetch, generate, write, force=True)
    status = rc.op_get_status()
    assert status["last_run_success"] is True
    assert status["run_count"] == 1


def test_configure_rejects_dangerously_short_interval(rc):
    try:
        rc.op_configure(interval_seconds=1)
        assert False
    except rc.ReflectionError:
        pass


def test_configure_updates_model_and_interval(rc):
    rc.op_configure(interval_seconds=600, model="llama3.1:8b")
    state = rc.load_state()
    assert state["interval_seconds"] == 600
    assert state["model"] == "llama3.1:8b"


def test_malformed_state_file_recovers_to_defaults(rc):
    rc.STATE_PATH.write_text("{not valid json")
    state = rc.load_state()
    assert state["enabled"] is False  # recovered safely, still off


def test_older_state_file_missing_keys_gets_backfilled(rc):
    import json
    rc.STATE_PATH.write_text(json.dumps({"enabled": True}))  # simulate an old/partial state file
    state = rc.load_state()
    assert state["enabled"] is True  # existing value preserved
    assert "interval_seconds" in state  # missing keys filled in from defaults
