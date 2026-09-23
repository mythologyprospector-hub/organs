import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import organs_tui as ui  # noqa: E402


class FakeWindow:
    """Just enough of curses.window to exercise the real draw_* functions
    without a real terminal: getmaxyx() for _safe_addstr's bounds check,
    addstr() recording what was written for assertions."""

    def __init__(self, height=40, width=100):
        self._height = height
        self._width = width
        self.lines = []

    def getmaxyx(self):
        return (self._height, self._width)

    def addstr(self, y, x, text, attr=0):
        self.lines.append((y, x, text))


HEALTHY_DATA = {
    "registry": {"organs": [
        {"name": "memory", "status": "alive", "last_heartbeat_age_seconds": 2.1, "version": "0.3.0"},
        {"name": "sandbox", "status": "alive", "last_heartbeat_age_seconds": 400, "version": "0.1.0"},
    ]},
    "memory": {"ledger_entries": 12, "indexed_entries": 12, "unembedded": 0, "archived_entries": 1,
               "pinned_entries": 2, "active_scars": 0, "pending_promises": 1, "open_unknowables": 0,
               "unresolved_relations": 0},
    "introspection": {
        "host": {"hostname": "mythos1", "kernel_name": "Linux", "kernel_release": "6.8.0"},
        "cpu": {"cores": 16, "load_1m": 0.42},
        "memory": {"used_gb": 8.2, "total_gb": 32.0},
    },
    "telemetry_stats": {"total_events": 3, "by_source": {"memory": 2, "sandbox": 1}, "avg_duration_ms": 42.5},
    "telemetry_recent": [
        {"timestamp": 1000.0, "source": "memory", "event_type": "request", "status": "completed"},
    ],
    "executive_goals": [{"status": "draft", "description": "a test goal"}],
    "orchestrator_services": [{"name": "ollama", "driver": "systemd_user", "status": "running", "detail": "active"}],
    "reflection_status": {"enabled": False, "interval_seconds": 300, "model": "phi4-mini:latest"},
    "sandbox_doctor": {"docker_available": True, "docker_version": "Docker version 24.0.0"},
    "bus_topics": [{"topic": "test", "event_count": 5}],
    "critic_rules": [{"rule": "one"}, {"rule": "two"}],
}

ALL_ERROR_DATA = {
    key: {"error": f"{key} unreachable"} for key in HEALTHY_DATA
}

EMPTY_DATA = {
    "registry": {"organs": []},
    "memory": {},
    "introspection": {"host": {}, "cpu": {}, "memory": {}},
    "telemetry_stats": {},
    "telemetry_recent": [],
    "executive_goals": [],
    "orchestrator_services": [],
    "reflection_status": {},
    "sandbox_doctor": {},
    "bus_topics": [],
    "critic_rules": [],
}


@pytest.mark.parametrize("draw_fn", ui.DRAW_FUNCS)
@pytest.mark.parametrize("dataset", [HEALTHY_DATA, ALL_ERROR_DATA, EMPTY_DATA],
                          ids=["healthy", "all_error", "empty"])
def test_every_panel_survives_every_data_shape(draw_fn, dataset):
    """The core resilience guarantee of the whole TUI: no combination of
    real, degraded, or empty data from any organ may ever raise while
    rendering — one organ being down must never take the terminal down
    with it."""
    win = FakeWindow()
    draw_fn(win, dataset)  # must not raise


def test_tab_bar_highlights_current_tab():
    win = FakeWindow()
    ui.draw_tab_bar(win, 2)
    rendered = " ".join(text for _, _, text in win.lines)
    assert "Sandbox" in rendered


def test_safe_addstr_never_raises_when_off_screen():
    win = FakeWindow(height=5, width=10)
    ui._safe_addstr(win, 100, 100, "way off screen")  # must not raise
    ui._safe_addstr(win, -1, -1, "negative coords")  # must not raise


def test_safe_addstr_truncates_to_window_width():
    win = FakeWindow(height=5, width=10)
    ui._safe_addstr(win, 0, 0, "this is way too long for a 10-wide window")
    assert len(win.lines[0][2]) <= 10


def test_safe_addstr_survives_curses_error(monkeypatch):
    class RaisingWindow(FakeWindow):
        def addstr(self, *a, **kw):
            raise curses_error_stub()

    def curses_error_stub():
        return Exception("simulated curses.error")

    win = RaisingWindow()
    # Patch the actual exception type _safe_addstr catches
    monkeypatch.setattr(ui.curses, "error", Exception)
    ui._safe_addstr(win, 0, 0, "text")  # must not raise even if addstr itself does


def test_sandbox_panel_reports_diagnostics():
    win = FakeWindow()
    ui.draw_sandbox(win, HEALTHY_DATA)
    rendered = " ".join(text for _, _, text in win.lines)
    assert "SANDBOX" in rendered
    assert "docker_available" in rendered
    assert "True" in rendered


def test_sandbox_panel_shows_no_diagnostic_message_when_empty():
    win = FakeWindow()
    ui.draw_sandbox(win, EMPTY_DATA)
    rendered = " ".join(text for _, _, text in win.lines)
    assert "no diagnostic data" in rendered


def test_telemetry_panel_explains_empty_state_honestly():
    """An empty recorder is a valid state. The panel should say that,
    not just show a blank list that looks broken."""
    win = FakeWindow()
    ui.draw_telemetry(win, EMPTY_DATA)
    rendered = " ".join(text for _, _, text in win.lines)
    assert "no events in the recorder" in rendered


# --- Input tab: the one interactive, side-effecting-capable panel ---

def _io_state(history=None, buffer=""):
    return {"buffer": buffer, "history": history or []}


def test_draw_input_survives_empty_history():
    win = FakeWindow()
    ui.draw_input(win, _io_state())  # must not raise


def test_draw_input_renders_typed_buffer():
    win = FakeWindow()
    ui.draw_input(win, _io_state(buffer="restart oll"))
    rendered = " ".join(text for _, _, text in win.lines)
    assert "restart oll" in rendered


def test_draw_input_renders_history_entries():
    win = FakeWindow()
    history = [{"text": "restart ollama", "dry_run": False,
                "display_lines": ["intent: restart_ollama -> orchestrator POST /orchestrator/restart",
                                   "risk: safe — executed"]}]
    ui.draw_input(win, _io_state(history=history))
    rendered = " ".join(text for _, _, text in win.lines)
    assert "restart ollama" in rendered
    assert "risk: safe — executed" in rendered


def test_draw_input_marks_dry_run_entries_differently():
    win = FakeWindow()
    history = [{"text": "restart ollama", "dry_run": True,
                "display_lines": ["intent: restart_ollama -> orchestrator POST /orchestrator/restart"]}]
    ui.draw_input(win, _io_state(history=history))
    marker_line = next(t for _, x, t in win.lines if x == 2 and "restart ollama" in t)
    assert marker_line.startswith("?")


def test_draw_input_survives_a_very_long_history():
    win = FakeWindow(height=15, width=80)  # small window on purpose
    history = [{"text": f"request {i}", "dry_run": False, "display_lines": ["line one", "line two"]}
               for i in range(50)]
    ui.draw_input(win, _io_state(history=history))  # must not raise, must not overflow silently


def test_draw_input_survives_all_data_shapes_including_errors():
    win = FakeWindow()
    history = [{"text": "broken request", "dry_run": False,
                "display_lines": _io_error_lines()}]
    ui.draw_input(win, _io_state(history=history))


def _io_error_lines():
    return ui._summarize_io_response({"error": "io_interface not currently registered"})


# --- _summarize_io_response: real response shapes, not invented ones ---

def test_summarize_response_handles_connection_error():
    lines = ui._summarize_io_response({"error": "connection refused"})
    assert any("connection refused" in line for line in lines)


def test_summarize_response_handles_unmatched_intent():
    response = {"matched": False, "message": "I don't recognize that request yet.",
                "examples": ["restart ollama", "memory stats"]}
    lines = ui._summarize_io_response(response)
    assert any("don't recognize" in line for line in lines)
    assert any("restart ollama" in line for line in lines)


def test_summarize_response_handles_executed_action():
    response = {
        "action_taken": True,
        "interpreted_as": {"intent": "memory_stats", "organ": "memory", "method": "GET", "path": "/memory/stats"},
        "risk": {"risk_tier": "safe", "requires_human_approval": False},
        "result": {"ledger_entries": 12},
    }
    lines = ui._summarize_io_response(response)
    joined = " ".join(lines)
    assert "memory_stats" in joined
    assert "executed" in joined
    assert "ledger_entries" in joined


def test_summarize_response_handles_gated_goal_creation():
    response = {
        "action_taken": False,
        "interpreted_as": {"intent": "restart_service", "organ": "orchestrator", "method": "POST", "path": "/orchestrator/restart"},
        "risk": {"risk_tier": "high_risk", "requires_human_approval": True},
        "result": {"id": "goal-abc123"},
    }
    lines = ui._summarize_io_response(response)
    joined = " ".join(lines)
    assert "needs approval" in joined
    assert "goal-abc123" in joined


def test_summarize_response_handles_execution_failure():
    response = {
        "action_taken": False,
        "interpreted_as": {"intent": "restart_service", "organ": "orchestrator", "method": "POST", "path": "/orchestrator/restart"},
        "risk": {"risk_tier": "safe", "requires_human_approval": False},
        "error": "orchestrator unreachable",
    }
    lines = ui._summarize_io_response(response)
    assert any("FAILED" in line and "orchestrator unreachable" in line for line in lines)


def test_summarize_response_handles_dry_run_interpret():
    response = {"matched": True, "intent": "memory_stats", "organ": "memory", "method": "GET",
                "path": "/memory/stats", "body": {}}
    lines = ui._summarize_io_response(response)
    joined = " ".join(lines)
    assert "memory_stats" in joined
    assert "memory" in joined


def test_tests_panel_survives_empty_runner_state():
    class Runner:
        def snapshot(self):
            return {"running": False, "label": "", "started": None,
                    "finished": None, "returncode": None, "lines": []}
    win = FakeWindow()
    ui.draw_tests(win, {"runner": Runner(), "suites": ["memory", "tui"], "selected": 0})
    rendered = " ".join(t for _, _, t in win.lines)
    assert "TEST CENTER" in rendered
    assert "memory" in rendered


def test_tests_panel_shows_failed_runner_output():
    class Runner:
        def snapshot(self):
            return {"running": False, "label": "tui", "started": 1,
                    "finished": 2, "returncode": 1,
                    "lines": ["2 failed in 0.1s"]}
    win = FakeWindow()
    ui.draw_tests(win, {"runner": Runner(), "suites": ["tui"], "selected": 0})
    rendered = " ".join(t for _, _, t in win.lines)
    assert "FAIL (exit 1)" in rendered
    assert "2 failed" in rendered


def test_diagnostics_panel_renders_real_check_results():
    win = FakeWindow()
    ui.draw_diagnostics(win, {"checks": [
        {"organ": "memory", "label": "health", "ok": True, "result": {"status": "ok"}},
        {"organ": "sandbox", "label": "doctor", "ok": False, "result": {"error": "docker unavailable"}},
    ]})
    rendered = " ".join(t for _, _, t in win.lines)
    assert "memory" in rendered and "OK" in rendered
    assert "sandbox" in rendered and "DOWN" in rendered
    assert "docker unavailable" in rendered


def test_tab_bar_puts_controls_on_separate_row():
    win = FakeWindow(width=90)
    ui.draw_tab_bar(win, ui.TESTS_TAB_INDEX)
    assert any(y == 1 and "Enter" in text for y, _, text in win.lines)


def test_tests_panel_uses_two_pane_layout_on_wide_terminal():
    class Runner:
        def snapshot(self):
            return {"running": False, "label": "tui", "started": 1,
                    "finished": 2, "returncode": 0,
                    "lines": ["72 passed in 0.10s"],
                    "summary": {"passed": 72, "duration": 0.10}}
    win = FakeWindow(width=140)
    ui.draw_tests(win, {"runner": Runner(), "suites": ["memory", "tui"], "selected": 1})
    rendered = " ".join(t for _, _, t in win.lines)
    assert "RESULT / OUTPUT" in rendered
    assert "72 passed" in rendered
    assert "completed successfully" in rendered


SAMPLE_GOALS = [
    {"id": "goal1", "description": "restart ollama", "status": "blocked", "steps": [
        {"id": "step1", "organ": "orchestrator", "method": "POST", "path": "/orchestrator/services/ollama/restart",
         "body": None, "description": "restart ollama service", "risk_tier": "high_risk",
         "risk_reasoning": "service restart", "status": "pending_approval"},
        {"id": "step2", "organ": "memory", "method": "GET", "path": "/memory/stats",
         "body": None, "description": "check memory stats", "risk_tier": "safe",
         "risk_reasoning": "read-only", "status": "succeeded"},
    ]},
    {"id": "goal2", "description": "a script that prints hello world", "status": "blocked", "steps": [
        {"id": "step3", "organ": "sandbox", "method": "POST", "path": "/sandbox/jobs",
         "body": {"spec": "prints hello world"}, "description": "generate script", "risk_tier": "high_risk",
         "risk_reasoning": "code generation", "status": "pending_approval"},
    ]},
]


def test_pending_steps_flattens_across_goals_and_skips_non_pending():
    pending = ui._pending_steps(SAMPLE_GOALS)
    assert len(pending) == 2  # step2 (succeeded) excluded
    assert {p["step_id"] for p in pending} == {"step1", "step3"}
    assert pending[0]["goal_id"] == "goal1"
    assert pending[0]["organ"] == "orchestrator"
    assert pending[1]["goal_id"] == "goal2"


def test_pending_steps_handles_unreachable_executive_cleanly():
    assert ui._pending_steps({"error": "executive not currently registered"}) == []


def test_executable_goals_only_includes_ready_or_executing():
    goals = SAMPLE_GOALS + [
        {"id": "goal3", "description": "done thing", "status": "completed", "steps": []},
        {"id": "goal4", "description": "blocked thing", "status": "blocked", "steps": []},
        {"id": "goal5", "description": "run me", "status": "ready", "steps": []},
    ]
    executable = ui._executable_goals(goals)
    assert {g["goal_id"] for g in executable} == {"goal5"}
    assert executable[0]["kind"] == "goal"


def test_queue_items_combines_pending_steps_and_executable_goals():
    goals = SAMPLE_GOALS + [{"id": "goal5", "description": "run me", "status": "ready", "steps": []}]
    items = ui._queue_items(goals)
    # pending steps first, then executable goals
    assert [i["kind"] for i in items] == ["step", "step", "goal"]


def test_draw_executive_shows_pending_queue_and_keybindings():
    win = FakeWindow()
    exec_state = {"items": [], "selected": 0, "mode": "browse", "reason_buffer": "", "message": None}
    ui.draw_executive(win, {"executive_goals": SAMPLE_GOALS}, exec_state)
    rendered = " ".join(t for _, _, t in win.lines)
    assert "approve" in rendered and "reject" in rendered and "execute" in rendered
    assert "orchestrator" in rendered
    assert "sandbox" in rendered
    assert exec_state["items"] == ui._queue_items(SAMPLE_GOALS)


def test_draw_executive_shows_ready_goal_in_queue():
    win = FakeWindow()
    goals = SAMPLE_GOALS + [{"id": "goal5", "description": "run this ready goal", "status": "ready", "steps": []}]
    exec_state = {"items": [], "selected": 2, "mode": "browse", "reason_buffer": "", "message": None}
    ui.draw_executive(win, {"executive_goals": goals}, exec_state)
    rendered = " ".join(t for _, _, t in win.lines)
    assert "READY TO RUN" in rendered
    assert "run this ready goal" in rendered


def test_draw_executive_shows_empty_state_when_nothing_pending():
    win = FakeWindow()
    exec_state = {"items": [], "selected": 0, "mode": "browse", "reason_buffer": "", "message": None}
    ui.draw_executive(win, {"executive_goals": []}, exec_state)
    rendered = " ".join(t for _, _, t in win.lines)
    assert "nothing pending" in rendered


def test_draw_executive_shows_confirm_prompt_before_approving():
    win = FakeWindow()
    exec_state = {"items": [], "selected": 0, "mode": "confirm_approve", "reason_buffer": "", "message": None}
    ui.draw_executive(win, {"executive_goals": SAMPLE_GOALS}, exec_state)
    rendered = " ".join(t for _, _, t in win.lines)
    assert "approve" in rendered and "[y]es" in rendered


def test_draw_executive_shows_confirm_prompt_before_executing():
    win = FakeWindow()
    goals = [{"id": "goal5", "description": "run this ready goal", "status": "ready", "steps": []}]
    exec_state = {"items": [], "selected": 0, "mode": "confirm_execute", "reason_buffer": "", "message": None}
    ui.draw_executive(win, {"executive_goals": goals}, exec_state)
    rendered = " ".join(t for _, _, t in win.lines)
    assert "run this ready goal" in rendered and "[y]es" in rendered


def test_draw_executive_shows_reason_prompt_before_rejecting():
    win = FakeWindow()
    exec_state = {"items": [], "selected": 0, "mode": "reject_reason", "reason_buffer": "too risky",
                   "message": None}
    ui.draw_executive(win, {"executive_goals": SAMPLE_GOALS}, exec_state)
    rendered = " ".join(t for _, _, t in win.lines)
    assert "reject reason" in rendered
    assert "too risky" in rendered
