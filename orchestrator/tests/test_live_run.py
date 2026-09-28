import pytest


def test_real_run_reports_docker_availability(oc):
    """Exercise the real subprocess path against an external dependency.

    Docker is optional on some development/CI hosts, so absence is a valid
    operational result. The important contract is that _run() reports the
    real state without an unhandled exception.
    """
    try:
        rc, stdout, stderr = oc._run(["docker", "--version"], timeout=5)
    except oc.OrchestratorError as exc:
        assert "command not found" in str(exc)
        return

    assert rc == 0
    assert stdout.startswith("Docker version ")
    assert stderr == ""
