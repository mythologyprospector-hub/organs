def test_health_and_info(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    r = api_client.get("/info")
    assert "run_job" in r.json()["capabilities"]


def test_run_job_via_api(api_client):
    api_client.fake_runner.response = (0, "hello\n", "", False)
    r = api_client.post("/sandbox/jobs", json={
        "language": "python", "files": {"x.py": "print('hello')"}, "command": "python x.py",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["exit_code"] == 0
    assert body["stdout"] == "hello\n"
    assert body["network_enabled"] is False


def test_invalid_language_returns_error_envelope(api_client):
    r = api_client.post("/sandbox/jobs", json={
        "language": "cobol", "files": {"x": "1"}, "command": "run x",
    })
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "sandbox_error"


def test_path_traversal_returns_error_envelope(api_client):
    r = api_client.post("/sandbox/jobs", json={
        "language": "python", "files": {"../evil.py": "1"}, "command": "python evil.py",
    })
    assert r.status_code == 400
    assert "traversal" in r.json()["error"]["message"]


def test_languages_endpoint(api_client):
    r = api_client.get("/sandbox/languages")
    assert r.status_code == 200
    assert "python" in r.json()


def test_doctor_endpoint(api_client):
    api_client.fake_runner.response = (0, "Docker version 26.1.5", "", False)
    r = api_client.get("/sandbox/doctor")
    assert r.status_code == 200
    assert r.json()["docker_available"] is True
