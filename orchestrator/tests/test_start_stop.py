def test_start_already_running_is_a_noop(oc, fake_runner):
    fake_runner.responses[("systemctl", "is-active", "ollama.service")] = (0, "active", "")
    result = oc.op_start("ollama")
    assert result["success"] is True
    assert result["detail"] == "already running"
    # never actually called `systemctl start` since it was already up
    assert ("systemctl", "start", "ollama.service") not in [tuple(c) for c in fake_runner.calls]


def test_start_stopped_service_calls_start_then_rechecks(oc, fake_runner):
    import json
    oc.CONFIG_PATH.write_text(json.dumps({
        "myapp": {"driver": "systemd_user", "unit": "some.service", "always_on": True, "description": "test"}
    }))

    state = {"started": False}

    def stateful(cmd, timeout=10):
        fake_runner.calls.append(cmd)
        if tuple(cmd) == ("systemctl", "--user", "start", "some.service"):
            state["started"] = True
            return (0, "", "")
        if tuple(cmd) == ("systemctl", "--user", "is-active", "some.service"):
            return (0, "active", "") if state["started"] else (3, "inactive", "")
        return (1, "", "unscripted")

    import orchestrator_core as ocmod
    orig = ocmod._run
    ocmod._run = stateful
    try:
        result = oc.op_start("myapp")
    finally:
        ocmod._run = orig

    assert result["success"] is True
    assert result["status"] == "running"


def test_stop_already_stopped_is_a_noop(oc, fake_runner):
    fake_runner.responses[("systemctl", "is-active", "ollama.service")] = (3, "inactive", "")
    result = oc.op_stop("ollama")
    assert result["success"] is True
    assert result["detail"] == "already stopped"
    assert ("systemctl", "stop", "ollama.service") not in [tuple(c) for c in fake_runner.calls]


def test_stop_not_found_docker_container_is_a_noop(oc, fake_runner):
    fake_runner.responses[("docker", "inspect", "-f", "{{.State.Running}}", "REPLACE_ME_oi_container_name")] = (
        1, "", "Error: No such object",
    )
    result = oc.op_stop("oi-sandbox")
    assert result["success"] is True
    assert result["status"] == "not_found"


def test_systemd_system_start_without_nopasswd_fails_clearly(oc, fake_runner):
    fake_runner.responses[("systemctl", "is-active", "ollama.service")] = (3, "inactive", "")
    fake_runner.responses[("sudo", "-n", "systemctl", "start", "ollama.service")] = (
        1, "", "sudo: a password is required",
    )
    result = oc.op_start("ollama")
    assert result["success"] is False
    assert "NOPASSWD" in result["detail"] or "passwordless" in result["detail"]
    assert "sudo systemctl start ollama.service" in result["detail"]


def test_docker_start_success(oc, fake_runner):
    fake_runner.responses[("docker", "inspect", "-f", "{{.State.Running}}", "open-webui")] = (0, "false", "")

    call_count = {"n": 0}

    def responder(cmd, timeout=10):
        fake_runner.calls.append(cmd)
        if tuple(cmd) == ("docker", "start", "open-webui"):
            call_count["n"] += 1
            return (0, "open-webui", "")
        if tuple(cmd) == ("docker", "inspect", "-f", "{{.State.Running}}", "open-webui"):
            return (0, "true", "") if call_count["n"] > 0 else (0, "false", "")
        return (1, "", "unscripted")

    import orchestrator_core as ocmod
    orig = ocmod._run
    ocmod._run = responder
    try:
        result = oc.op_start("open-webui")
    finally:
        ocmod._run = orig

    assert result["success"] is True
    assert result["status"] == "running"


def test_restart_stops_then_starts(oc, fake_runner):
    state = {"running": True}

    def responder(cmd, timeout=10):
        fake_runner.calls.append(cmd)
        if tuple(cmd) == ("systemctl", "is-active", "ollama.service"):
            return (0, "active", "") if state["running"] else (3, "inactive", "")
        if tuple(cmd) == ("sudo", "-n", "systemctl", "stop", "ollama.service"):
            state["running"] = False
            return (0, "", "")
        if tuple(cmd) == ("sudo", "-n", "systemctl", "start", "ollama.service"):
            state["running"] = True
            return (0, "", "")
        return (1, "", "unscripted")

    import orchestrator_core as ocmod
    orig = ocmod._run
    ocmod._run = responder
    try:
        result = oc.op_restart("ollama")
    finally:
        ocmod._run = orig

    assert result["success"] is True
    assert result["status"] == "running"
    calls_as_tuples = [tuple(c) for c in fake_runner.calls]
    assert ("sudo", "-n", "systemctl", "stop", "ollama.service") in calls_as_tuples
    assert ("sudo", "-n", "systemctl", "start", "ollama.service") in calls_as_tuples
