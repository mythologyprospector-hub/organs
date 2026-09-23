"""Test execution support for the TUI.

This module deliberately does not invent a second test runner.  The full-suite
button invokes the repository's existing run_all_tests.sh exactly as a human
would from the project root.  Individual suite runs invoke the same
``python3 -m pytest tests/`` command used by that script, in that suite's own
working directory, preserving the repository's subprocess-isolation rule.

Runs happen in a background thread so a long test run never freezes curses.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import threading
import time

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
RUN_ALL = REPO_ROOT / "run_all_tests.sh"


def available_suites() -> list[str]:
    """Return the actual test-bearing directories present in this checkout.

    No organ list is duplicated here: the filesystem is the source of truth
    for what the TUI can offer as an individual local test suite.
    """
    suites = []
    for child in sorted(REPO_ROOT.iterdir(), key=lambda p: p.name):
        if child.is_dir() and (child / "tests").is_dir():
            suites.append(child.name)
    return suites


def _parse_summary_line(line: str) -> dict:
    result = {}
    patterns = {
        "passed": r"\b(\d+)\s+passed\b",
        "failed": r"\b(\d+)\s+failed\b",
        "errors": r"\b(\d+)\s+errors?\b",
        "skipped": r"\b(\d+)\s+skipped\b",
        "warnings": r"\b(\d+)\s+warnings?\b",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, line)
        if match:
            result[key] = int(match.group(1))
    duration = re.search(r"\bin\s+([0-9]+(?:\.[0-9]+)?)s\b", line)
    if duration:
        result["duration"] = float(duration.group(1))
    return result


def parse_pytest_summary(lines: list[str]) -> dict:
    """Extract facts pytest printed, without pretending to know progress.

    For a single-suite run this uses its terminal summary.  For the repository
    aggregate runner, the script prints one summary after each isolated
    subprocess; those summaries are aggregated by section.
    """
    section_summaries = []
    in_section = False
    current = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("--- ") and stripped.endswith(" ---"):
            if current:
                section_summaries.append(current)
            current = None
            in_section = True
            continue
        if in_section and re.search(r"\b\d+\s+(?:passed|failed|errors?|skipped)\b", stripped) and " in " in stripped:
            parsed = _parse_summary_line(stripped)
            if parsed:
                current = parsed
        elif not section_summaries and re.search(r"\b\d+\s+(?:passed|failed|errors?|skipped)\b", stripped) and " in " in stripped:
            parsed = _parse_summary_line(stripped)
            if parsed:
                current = parsed
    if current:
        section_summaries.append(current)

    # Aggregate runner: each section contributes one final summary.
    if len(section_summaries) > 1:
        result = {}
        for key in ("passed", "failed", "errors", "skipped", "warnings"):
            values = [s[key] for s in section_summaries if key in s]
            if values:
                result[key] = sum(values)
        durations = [s["duration"] for s in section_summaries if "duration" in s]
        if durations:
            result["duration"] = sum(durations)
        return result

    return section_summaries[0] if section_summaries else {}


class TestRunner:
    """One-at-a-time background test runner with captured output."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._process = None
        self.running = False
        self.label = ""
        self.started = None
        self.finished = None
        self.returncode = None
        self.lines: list[str] = []
        self.summary: dict = {}

    def start_all(self) -> bool:
        return self._start("full suite", [str(RUN_ALL)], REPO_ROOT)

    def start_suite(self, suite: str) -> bool:
        if suite not in available_suites():
            return False
        return self._start(
            suite,
            ["python3", "-m", "pytest", "tests/", "-q"],
            REPO_ROOT / suite,
        )

    def _start(self, label: str, command: list[str], cwd: Path) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.label = label
            self.started = time.time()
            self.finished = None
            self.returncode = None
            self.summary = {}
            self.lines = ["$ " + " ".join(command)]

        self._thread = threading.Thread(
            target=self._run, args=(command, cwd), daemon=True,
        )
        self._thread.start()
        return True

    def _run(self, command: list[str], cwd: Path):
        env = os.environ.copy()
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            with self._lock:
                self._process = process

            assert process.stdout is not None
            for line in process.stdout:
                with self._lock:
                    self.lines.append(line.rstrip("\n"))
            rc = process.wait()
        except Exception as exc:
            rc = 127
            with self._lock:
                self.lines.append(f"runner error: {exc}")
        finally:
            with self._lock:
                self.returncode = rc
                self.finished = time.time()
                self.summary = parse_pytest_summary(self.lines)
                self.running = False
                self._process = None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "label": self.label,
                "started": self.started,
                "finished": self.finished,
                "returncode": self.returncode,
                "lines": list(self.lines),
                "summary": dict(self.summary),
            }
