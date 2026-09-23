import json


def test_first_run_creates_default_config(oc):
    assert not oc.CONFIG_PATH.exists()
    services = oc.load_services()
    assert oc.CONFIG_PATH.exists()
    assert "ollama" in services
    assert "open-webui" in services
    assert "oi-sandbox" in services


def test_empty_existing_file_gets_defaults_too(oc):
    """The exact bug this is a regression test for: an empty file (e.g.
    from opening it in an editor before it was ever created) must be
    treated the same as a missing one, not left empty forever."""
    oc.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    oc.CONFIG_PATH.write_text("")
    assert oc.CONFIG_PATH.stat().st_size == 0

    services = oc.load_services()
    assert oc.CONFIG_PATH.stat().st_size > 0
    assert "ollama" in services


def test_nonempty_existing_config_is_never_overwritten(oc):
    """The other half of the guarantee: ensure_config() must NOT clobber
    a real, user-edited config just because it differs from defaults."""
    import json
    custom = {"myservice": {"driver": "docker", "container": "custom", "always_on": True, "description": "mine"}}
    oc.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    oc.CONFIG_PATH.write_text(json.dumps(custom))

    services = oc.load_services()
    assert services == custom
    assert "ollama" not in services


def test_unknown_service_errors_with_helpful_list(oc):
    try:
        oc.get_service_def("nonexistent")
        assert False
    except oc.OrchestratorError as e:
        assert "ollama" in str(e)  # lists known services


def test_invalid_driver_in_config_errors(oc, tmp_path):
    oc.CONFIG_PATH.write_text(json.dumps({"weird": {"driver": "telepathy"}}))
    try:
        oc.get_service_def("weird")
        assert False
    except oc.OrchestratorError:
        pass


def test_malformed_json_config_errors_cleanly(oc):
    oc.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    oc.CONFIG_PATH.write_text("{not valid json")
    try:
        oc.load_services()
        assert False
    except oc.OrchestratorError as e:
        assert "not valid JSON" in str(e)


# --- driver status parsing -------------------------------------------------

def test_systemd_system_status_running(oc, fake_runner):
    fake_runner.responses[("systemctl", "is-active", "ollama.service")] = (0, "active", "")
    result = oc.check_status("ollama")
    assert result["status"] == "running"
    assert result["driver"] == "systemd_system"


def test_systemd_system_status_stopped(oc, fake_runner):
    fake_runner.responses[("systemctl", "is-active", "ollama.service")] = (3, "inactive", "")
    result = oc.check_status("ollama")
    assert result["status"] == "stopped"


def test_docker_status_running(oc, fake_runner):
    fake_runner.responses[("docker", "inspect", "-f", "{{.State.Running}}", "open-webui")] = (0, "true", "")
    result = oc.check_status("open-webui")
    assert result["status"] == "running"


def test_docker_status_stopped(oc, fake_runner):
    fake_runner.responses[("docker", "inspect", "-f", "{{.State.Running}}", "open-webui")] = (0, "false", "")
    result = oc.check_status("open-webui")
    assert result["status"] == "stopped"


def test_docker_status_not_found(oc, fake_runner):
    fake_runner.responses[("docker", "inspect", "-f", "{{.State.Running}}", "REPLACE_ME_oi_container_name")] = (
        1, "", "Error: No such object: REPLACE_ME_oi_container_name",
    )
    result = oc.check_status("oi-sandbox")
    assert result["status"] == "not_found"


def test_always_on_flag_carried_through(oc, fake_runner):
    fake_runner.default = (0, "active", "")
    ollama = oc.check_status("ollama")
    oi = oc.check_status("oi-sandbox")
    assert ollama["always_on"] is True
    assert oi["always_on"] is False


def test_command_not_found_raises_orchestrator_error(oc, monkeypatch):
    def _raise(cmd, timeout=10):
        raise FileNotFoundError()
    monkeypatch.setattr(oc.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    try:
        oc._run(["nonexistent_binary"])
        assert False
    except oc.OrchestratorError as e:
        assert "not found" in str(e)


def test_command_not_executable_raises_orchestrator_error(oc, monkeypatch):
    """A binary that exists on disk but lacks the execute bit raises
    PermissionError, not FileNotFoundError — a distinct, real failure
    mode that must not slip through as an unhandled exception."""
    monkeypatch.setattr(oc.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
    try:
        oc._run(["unexecutable_binary"])
        assert False
    except oc.OrchestratorError as e:
        assert "permission denied" in str(e)


def test_command_timeout_raises_orchestrator_error(oc, monkeypatch):
    import subprocess as sp

    def _raise(*a, **k):
        raise sp.TimeoutExpired(cmd="x", timeout=1)
    monkeypatch.setattr(oc.subprocess, "run", _raise)
    try:
        oc._run(["sleep", "100"], timeout=1)
        assert False
    except oc.OrchestratorError as e:
        assert "timed out" in str(e)


def test_op_list_returns_every_configured_service(oc, fake_runner):
    fake_runner.default = (0, "active", "")
    fake_runner.responses[("docker", "inspect", "-f", "{{.State.Running}}", "open-webui")] = (0, "true", "")
    fake_runner.responses[("docker", "inspect", "-f", "{{.State.Running}}", "REPLACE_ME_oi_container_name")] = (0, "false", "")
    result = oc.op_list()
    names = {r["name"] for r in result}
    assert names == {"ollama", "open-webui", "oi-sandbox"}


def test_doctor_reports_config_state(oc):
    result = oc.op_doctor()
    assert result["service_count"] == 3
    assert result["config_readable"] is True
