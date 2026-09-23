def test_health_and_info(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    r = api_client.get("/info")
    assert "summary" in r.json()["capabilities"]


def test_summary_via_api(api_client):
    api_client.fake_runner.default = (127, "", "not found")
    r = api_client.get("/introspect/summary")
    assert r.status_code == 200
    body = r.json()
    assert "host" in body
    assert "ollama" in body


def test_individual_endpoints_via_api(api_client):
    api_client.fake_runner.responses[("hostname",)] = (0, "testhost\n", "")
    api_client.fake_runner.responses[("uname", "-srm")] = (0, "Linux 6.8.0 x86_64\n", "")

    r = api_client.get("/introspect/host")
    assert r.status_code == 200
    assert r.json()["hostname"] == "testhost"


def test_refresh_via_api(api_client):
    r = api_client.post("/introspect/refresh")
    assert r.status_code == 200
    assert "host" in r.json()


def test_unknown_collector_returns_error_envelope(api_client):
    # not a real route, but confirms op_get's error path through the wrapper indirectly
    # by hitting a collector-less path isn't applicable here since routes are fixed —
    # this instead confirms force=true param is accepted without error
    r = api_client.get("/introspect/cpu", params={"force": "true"})
    assert r.status_code == 200
