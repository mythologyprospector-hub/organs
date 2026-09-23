import os

import pytest


# --- the safety boundary: fixed images only ---------------------------

def test_only_allowed_languages_accepted(sc, fake_runner):
    try:
        sc.op_run_job("ruby", {"x.rb": "puts 1"}, "ruby x.rb")
        assert False, "expected SandboxError for a language not in the allowlist"
    except sc.SandboxError as e:
        assert "python" in str(e)  # lists what IS allowed


def test_allowed_languages_map_to_specific_pinned_images(sc):
    langs = sc.op_list_languages()
    assert langs["python"] == "python:3.11-slim"
    assert langs["node"] == "node:20-slim"


# --- path traversal ------------------------------------------------------

def test_path_traversal_rejected(sc, fake_runner):
    try:
        sc.op_run_job("python", {"../../etc/passwd": "malicious"}, "cat ../../etc/passwd")
        assert False, "expected SandboxError for path traversal"
    except sc.SandboxError as e:
        assert "traversal" in str(e)


def test_absolute_path_rejected(sc, fake_runner):
    try:
        sc.op_run_job("python", {"/etc/passwd": "malicious"}, "cat /etc/passwd")
        assert False, "expected SandboxError for an absolute path"
    except sc.SandboxError as e:
        assert "absolute" in str(e)


def test_bare_dot_filename_rejected(sc, fake_runner):
    """A filename of exactly '.' collapses via pathlib join to the
    workspace directory itself, not a file inside it — write_text()
    would then raise IsADirectoryError, which main.py's error wrapping
    doesn't catch (it only catches SandboxError), surfacing as an
    unhandled 500 instead of a clean rejection. Must be caught here,
    same as '..' and absolute paths are."""
    try:
        sc.op_run_job("python", {".": "malicious"}, "ls")
        assert False, "expected SandboxError for a bare '.' filename"
    except sc.SandboxError as e:
        assert "traversal" in str(e)


def test_dot_segment_within_path_rejected(sc, fake_runner):
    """'foo/.' collapses to 'foo' on join — same class of surprise as
    the bare '.' case, just nested."""
    try:
        sc.op_run_job("python", {"foo/.": "malicious"}, "ls")
        assert False, "expected SandboxError for a '.' path segment"
    except sc.SandboxError as e:
        assert "traversal" in str(e)


def test_nested_relative_paths_are_fine(sc, fake_runner):
    """Legitimate multi-file projects need subdirectories — only
    traversal/absolute paths should be rejected, not nesting itself."""
    result = sc.op_run_job("python", {"src/main.py": "print(1)", "tests/test_main.py": "def test_x(): pass"},
                            "python src/main.py")
    assert result["exit_code"] == 0  # fake runner default returns 0


# --- network off by default -----------------------------------------------

def test_network_disabled_by_default(sc, fake_runner):
    sc.op_run_job("python", {"x.py": "print(1)"}, "python x.py")
    docker_cmd = fake_runner.calls[0][0]
    assert "--network" in docker_cmd
    idx = docker_cmd.index("--network")
    assert docker_cmd[idx + 1] == "none"


def test_network_enabled_only_when_explicitly_requested(sc, fake_runner):
    sc.op_run_job("python", {"x.py": "print(1)"}, "python x.py", network=True)
    docker_cmd = fake_runner.calls[0][0]
    idx = docker_cmd.index("--network")
    assert docker_cmd[idx + 1] == "bridge"


# --- resource limits -------------------------------------------------------

def test_default_memory_and_cpu_limits_applied(sc, fake_runner):
    sc.op_run_job("python", {"x.py": "print(1)"}, "python x.py")
    docker_cmd = fake_runner.calls[0][0]
    assert "--memory" in docker_cmd
    assert "--cpus" in docker_cmd
    assert "--pids-limit" in docker_cmd


def test_custom_memory_and_cpu_limits_respected(sc, fake_runner):
    sc.op_run_job("python", {"x.py": "print(1)"}, "python x.py", memory="1g", cpus="2.0")
    docker_cmd = fake_runner.calls[0][0]
    mem_idx = docker_cmd.index("--memory")
    assert docker_cmd[mem_idx + 1] == "1g"
    cpu_idx = docker_cmd.index("--cpus")
    assert docker_cmd[cpu_idx + 1] == "2.0"


def test_timeout_exceeding_max_rejected(sc, fake_runner):
    try:
        sc.op_run_job("python", {"x.py": "1"}, "python x.py", timeout_seconds=sc.MAX_TIMEOUT_SECONDS + 1)
        assert False
    except sc.SandboxError as e:
        assert "exceeds the max" in str(e)


def test_timeout_below_one_rejected(sc, fake_runner):
    try:
        sc.op_run_job("python", {"x.py": "1"}, "python x.py", timeout_seconds=0)
        assert False
    except sc.SandboxError:
        pass


def test_too_many_files_rejected(sc, fake_runner):
    files = {f"file_{i}.py": "x" for i in range(sc.MAX_FILES + 1)}
    try:
        sc.op_run_job("python", files, "python file_0.py")
        assert False
    except sc.SandboxError as e:
        assert "too many files" in str(e)


def test_oversized_job_rejected(sc, fake_runner):
    big_content = "x" * (sc.MAX_TOTAL_BYTES + 1)
    try:
        sc.op_run_job("python", {"big.py": big_content}, "python big.py")
        assert False
    except sc.SandboxError as e:
        assert "max is" in str(e)


def test_empty_files_rejected(sc, fake_runner):
    try:
        sc.op_run_job("python", {}, "python x.py")
        assert False
    except sc.SandboxError:
        pass


# --- workspace lifecycle: real filesystem, no docker needed --------------

def test_workspace_created_with_real_files(sc, fake_runner):
    """Files genuinely get written to disk before the (faked) docker
    call — this part doesn't need real Docker to verify."""
    captured_workspace = {}

    def capturing_runner(cmd, timeout):
        # the workspace path is the arg right after "-v", formatted as "<path>:/workspace:rw"
        v_idx = cmd.index("-v")
        vol_arg = cmd[v_idx + 1]
        workspace_path = vol_arg.split(":")[0]
        captured_workspace["path"] = workspace_path
        assert os.path.exists(os.path.join(workspace_path, "x.py"))
        with open(os.path.join(workspace_path, "x.py")) as f:
            assert f.read() == "print('hello')"
        return (0, "", "", False)

    import sandbox_core as scmod
    scmod._run = capturing_runner
    sc.op_run_job("python", {"x.py": "print('hello')"}, "python x.py")

    # workspace must be gone after the job completes
    assert not os.path.exists(captured_workspace["path"])


def test_workspace_cleaned_up_even_on_docker_failure(sc):
    captured = {}

    def failing_runner(cmd, timeout):
        v_idx = cmd.index("-v")
        captured["path"] = cmd[v_idx + 1].split(":")[0]
        return (1, "", "container crashed", False)

    import sandbox_core as scmod
    scmod._run = failing_runner
    result = sc.op_run_job("python", {"x.py": "1"}, "python x.py")
    assert result["exit_code"] == 1
    assert not os.path.exists(captured["path"])  # cleaned up despite failure


def test_workspace_cleaned_up_on_timeout(sc):
    captured = {}
    calls = []

    def timeout_runner(cmd, timeout):
        calls.append(cmd)
        if "-v" in cmd:
            v_idx = cmd.index("-v")
            captured["path"] = cmd[v_idx + 1].split(":")[0]
            return (-1, "", "job exceeded the hard timeout backstop", True)
        # the backstop-triggered cleanup call (docker rm -f <container>)
        return (0, "", "", False)

    import sandbox_core as scmod
    scmod._run = timeout_runner
    result = sc.op_run_job("python", {"x.py": "while True: pass"}, "python x.py")
    assert result["timed_out"] is True
    assert not os.path.exists(captured["path"])


def test_orphaned_container_reclaimed_when_backstop_fires(sc):
    """The hard backstop killing the docker CLI means --rm never runs —
    the container can be left alive in the daemon. Sandbox must reclaim
    it explicitly by name rather than trusting --rm alone."""
    calls = []

    def timeout_runner(cmd, timeout):
        calls.append(cmd)
        if cmd[:2] == ["docker", "run"]:
            return (-1, "", "job exceeded the hard timeout backstop", True)
        return (0, "", "", False)

    import sandbox_core as scmod
    scmod._run = timeout_runner
    result = sc.op_run_job("python", {"x.py": "while True: pass"}, "python x.py")
    assert result["timed_out"] is True

    run_cmd = calls[0]
    name_idx = run_cmd.index("--name")
    container_name = run_cmd[name_idx + 1]

    cleanup_calls = [c for c in calls if c[:3] == ["docker", "rm", "-f"]]
    assert len(cleanup_calls) == 1
    assert cleanup_calls[0][3] == container_name


def test_no_cleanup_call_when_job_completes_normally(sc, fake_runner):
    sc.op_run_job("python", {"x.py": "print(1)"}, "python x.py")
    rm_calls = [c for c in fake_runner.calls if c[0][:3] == ("docker", "rm", "-f")]
    assert rm_calls == []


def test_nested_directories_created_correctly(sc):
    captured = {}

    def capturing_runner(cmd, timeout):
        v_idx = cmd.index("-v")
        workspace_path = cmd[v_idx + 1].split(":")[0]
        captured["path"] = workspace_path
        assert os.path.exists(os.path.join(workspace_path, "src", "main.py"))
        return (0, "", "", False)

    import sandbox_core as scmod
    scmod._run = capturing_runner
    sc.op_run_job("python", {"src/main.py": "print(1)"}, "python src/main.py")


# --- coverage parsing ------------------------------------------------------

def test_coverage_percent_extracted_from_pytest_output(sc, fake_runner):
    fake_runner.response = (0, (
        "Name         Stmts   Miss  Cover\n"
        "-------------------------------\n"
        "app.py          40      6    85%\n"
        "-------------------------------\n"
        "TOTAL           40      6    85%\n"
        "5 passed in 0.42s\n"
    ), "", False)
    result = sc.op_run_job("python", {"app.py": "x=1"}, "pytest --cov=app")
    assert result["coverage_percent"] == 85


def test_coverage_percent_none_when_absent(sc, fake_runner):
    fake_runner.response = (0, "5 passed in 0.42s\n", "", False)
    result = sc.op_run_job("python", {"app.py": "x=1"}, "pytest")
    assert result["coverage_percent"] is None


# --- doctor / not-installed reporting ---------------------------------------

def test_doctor_reports_docker_unavailable_cleanly(sc, fake_runner):
    fake_runner.response = (127, "", "command not found", False)
    result = sc.op_doctor()
    assert result["docker_available"] is False


def test_real_run_reports_missing_docker_without_raising(sc):
    """Regression test for a real bug: the first version RAISED when
    docker wasn't installed instead of returning a clean result, and the
    mocked test for this exact scenario didn't catch it because the fake
    never exercised the real FileNotFoundError path. This calls the
    REAL _run() (no monkeypatching), against whatever this environment
    actually has.

    Deliberately does NOT assume docker is entirely absent here — an
    earlier version of this test hardcoded "not found" and would have
    failed in any environment where a `docker` file exists but isn't
    executable (PermissionError, not FileNotFoundError), which is
    precisely the second real gap this same file's other test
    (test_permission_error_caught_same_as_missing_docker) exists to
    cover. Asserting one specific failure text here would make this test
    itself an example of exactly the "mock doesn't match reality" lesson
    documented in DEV_NOTES.md — a caught-live-once irony worth not
    repeating.

    Second pass, same lesson: this also used to hardcode rc == 127,
    which assumed every environment this ever runs in has no working
    Docker at all — true on the machine this organ was originally built
    on, false on any box where Sandbox is actually meant to run real
    jobs (Docker installed and working, as caught live on mythos1). What
    actually matters, and all this asserts now: _run() never raises, and
    its return shape is internally consistent with whichever real state
    Docker is in here — working (rc 0) or not (rc 127, with a message
    saying why)."""
    rc, out, err, timed_out = sc._run(["docker", "--version"], timeout=5)
    assert timed_out is False
    if rc == 0:
        # Docker is actually installed and working in this environment.
        assert err == ""
    else:
        assert rc == 127
        assert ("not found" in err) or ("not executable" in err) or ("permission" in err.lower())

    # and op_doctor built on top of it must agree with the same reality
    result = sc.op_doctor()
    assert result["docker_available"] == (rc == 0)


def test_permission_error_caught_same_as_missing_docker(sc, monkeypatch):
    """A second real gap, caught by an external review: FileNotFoundError
    isn't the only way 'docker isn't usable' shows up. If the binary
    EXISTS but isn't executable (a mounted file without +x, a locked-down
    environment), subprocess.run raises PermissionError instead — a
    genuinely different exception the original version didn't catch,
    which would have crashed the request instead of reporting cleanly.
    This wasn't reproducible in the environment this organ was originally
    built in (no docker at all -> only FileNotFoundError ever fires
    there), which is exactly why it slipped through the first pass."""
    def raise_permission_error(*a, **k):
        raise PermissionError("[Errno 13] Permission denied: 'docker'")

    monkeypatch.setattr(sc.subprocess, "run", raise_permission_error)
    rc, out, err, timed_out = sc._run(["docker", "--version"], timeout=5)
    assert rc == 127
    assert "not executable" in err or "permission" in err.lower()
    assert timed_out is False

    result = sc.op_doctor()
    assert result["docker_available"] is False
