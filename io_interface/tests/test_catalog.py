def test_memory_recall_matches(ioc):
    r = ioc.op_interpret("what do you know about the deploy key")
    assert r["matched"] is True
    assert r["intent"] == "memory_recall"
    assert r["organ"] == "memory"
    assert r["method"] == "GET"
    assert "deploy%20key" in r["path"] or "deploy+key" in r["path"] or "deploy key" in r["path"]


def test_memory_add_matches(ioc):
    r = ioc.op_interpret("remember that the registry runs on port 8000")
    assert r["matched"] is True
    assert r["intent"] == "memory_add"
    assert r["method"] == "POST"
    assert r["body"]["text"] == "the registry runs on port 8000"


def test_memory_promise_matches(ioc):
    r = ioc.op_interpret("remind me to check the sandbox logs")
    assert r["matched"] is True
    assert r["intent"] == "memory_promise"
    assert r["body"]["text"] == "check the sandbox logs"


def test_memory_stats_matches(ioc):
    r = ioc.op_interpret("memory stats")
    assert r["intent"] == "memory_stats"
    assert r["method"] == "GET"


def test_introspect_summary_matches(ioc):
    r = ioc.op_interpret("system status")
    assert r["intent"] == "introspect_summary"


def test_introspect_ollama_matches(ioc):
    r = ioc.op_interpret("what models are installed")
    assert r["intent"] == "introspect_ollama"


def test_introspect_docker_matches(ioc):
    r = ioc.op_interpret("what containers are running")
    assert r["intent"] == "introspect_docker"


def test_orchestrator_restart_matches(ioc):
    r = ioc.op_interpret("restart ollama")
    assert r["intent"] == "orchestrator_restart"
    assert r["organ"] == "orchestrator"
    assert r["path"] == "/orchestrator/services/ollama/restart"


def test_orchestrator_stop_matches(ioc):
    r = ioc.op_interpret("stop oi-sandbox")
    assert r["intent"] == "orchestrator_stop"
    assert r["path"] == "/orchestrator/services/oi-sandbox/stop"


def test_orchestrator_start_matches(ioc):
    r = ioc.op_interpret("start oi-sandbox")
    assert r["intent"] == "orchestrator_start"


def test_orchestrator_status_matches(ioc):
    r = ioc.op_interpret("is ollama running")
    assert r["intent"] == "orchestrator_status"
    assert r["path"] == "/orchestrator/services/ollama"


def test_reflection_status_matches(ioc):
    r = ioc.op_interpret("reflection status")
    assert r["intent"] == "reflection_status"


def test_reflection_enable_matches(ioc):
    r = ioc.op_interpret("enable reflection")
    assert r["intent"] == "reflection_enable"


def test_reflection_disable_matches(ioc):
    r = ioc.op_interpret("disable reflection")
    assert r["intent"] == "reflection_disable"


def test_reflection_enable_via_start_phrasing_not_swallowed_by_orchestrator(ioc):
    """Regression test: reflection_enable's own pattern accepts 'start
    reflecting' as valid phrasing, but the generic orchestrator_start
    pattern ('start <word>') used to come first in the catalog and won
    the match instead — routing it to a nonexistent orchestrator service
    named 'reflecting' rather than actually enabling reflection."""
    r = ioc.op_interpret("start reflecting")
    assert r["intent"] == "reflection_enable"
    assert r["organ"] == "reflection"


def test_reflection_disable_via_stop_phrasing_not_swallowed_by_orchestrator(ioc):
    r = ioc.op_interpret("stop reflecting")
    assert r["intent"] == "reflection_disable"
    assert r["organ"] == "reflection"


def test_sandbox_python_matches(ioc):
    r = ioc.op_interpret("run this python code: print(1+1)")
    assert r["intent"] == "sandbox_run_python"
    assert r["body"]["files"]["main.py"] == "print(1+1)"
    assert r["body"]["language"] == "python"


def test_unmatched_text_returns_clarification_not_a_guess(ioc):
    """The most important test in this file: when nothing matches, it
    must say so plainly and show examples — never guess at an action."""
    r = ioc.op_interpret("blorbo the fribbet quantumly")
    assert r["matched"] is False
    assert "examples" in r
    assert len(r["examples"]) == len(ioc.CATALOG)


def test_empty_text_errors(ioc):
    try:
        ioc.op_interpret("")
        assert False
    except ioc.IOError_:
        pass


def test_restart_takes_priority_over_status_pattern_for_ambiguous_text(ioc):
    """'restart ollama' should never accidentally match the 'is X
    running' status pattern instead — catalog order matters, and this
    locks in that restart wins for its own phrasing."""
    r = ioc.op_interpret("restart ollama")
    assert r["intent"] == "orchestrator_restart"


def test_status_pattern_does_not_falsely_match_inside_other_words(ioc):
    """Regression test for a real bug: the orchestrator_status pattern's
    'is' alternative had no word boundary, so 'run th_IS_ python code'
    matched 'is python' as a status check on a service named 'python'.
    Locking in the fix: 'is' embedded inside another word (no boundary)
    must never trigger this — 'is' as its own standalone word still
    correctly can, that's legitimate matching, not the bug."""
    r = ioc.op_interpret("run this python code: print(1+1)")
    assert r["intent"] != "orchestrator_status"
    assert r["intent"] == "sandbox_run_python"

    # "is" embedded with no word boundary on either side — must NOT match
    for text in ["history shows something", "consistent behavior happens"]:
        r = ioc.op_interpret(text)
        assert r["matched"] is False or r["intent"] != "orchestrator_status"

