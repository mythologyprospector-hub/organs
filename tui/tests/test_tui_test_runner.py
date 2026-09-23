import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tui_test_runner as tr  # noqa: E402


def test_available_suites_reflects_checkout():
    suites = tr.available_suites()
    assert "tui" in suites
    assert "memory" in suites
    assert "registry" in suites


def test_runner_rejects_second_run_while_first_is_active(monkeypatch):
    runner = tr.TestRunner()
    runner.running = True
    assert runner.start_all() is False


def test_parse_pytest_summary_uses_real_terminal_summary():
    summary = tr.parse_pytest_summary([
        "==================== test session starts ====================",
        "12 passed, 2 skipped in 1.37s",
    ])
    assert summary == {"passed": 12, "skipped": 2, "duration": 1.37}


def test_parse_pytest_summary_aggregates_isolated_full_suite_sections():
    summary = tr.parse_pytest_summary([
        "--- registry ---",
        "29 passed in 0.47s",
        "  29 passed in 0.47s",
        "--- memory ---",
        "66 passed, 40 warnings in 2.19s",
        "  66 passed, 40 warnings in 2.19s",
    ])
    # The runner prints each section's summary twice; the parser retains the
    # last summary per section rather than double-counting it.
    assert summary["passed"] == 95
    assert summary["warnings"] == 40
    assert summary["duration"] == 2.66
