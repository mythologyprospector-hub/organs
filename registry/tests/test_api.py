def test_health_and_info(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json()["organ"] == "registry"

    r = api_client.get("/info")
    assert "register" in r.json()["capabilities"]


def test_register_via_api(api_client):
    r = api_client.post("/registry/register", json={
        "name": "memory", "base_url": "http://localhost:8001", "version": "0.3.0", "capabilities": ["add"],
    })
    assert r.status_code == 200
    assert r.json()["status"] == "alive"


def test_register_defaults_version_and_capabilities(api_client):
    r = api_client.post("/registry/register", json={"name": "memory", "base_url": "http://localhost:8001"})
    assert r.status_code == 200
    assert r.json()["version"] == "0.0.0"
    assert r.json()["capabilities"] == []


def test_list_organs_via_api(api_client):
    api_client.post("/registry/register", json={"name": "memory", "base_url": "http://localhost:8001"})
    api_client.post("/registry/register", json={"name": "critic", "base_url": "http://localhost:8007"})

    r = api_client.get("/registry/organs")
    assert r.status_code == 200
    names = {o["name"] for o in r.json()}
    assert names == {"memory", "critic"}


def test_list_organs_include_stale_query_param(api_client):
    api_client.post("/registry/register", json={"name": "memory", "base_url": "http://localhost:8001"})

    import main
    main.rc._organs["memory"]["last_heartbeat"] -= 999

    r = api_client.get("/registry/organs", params={"include_stale": "false"})
    assert r.json() == []

    r = api_client.get("/registry/organs", params={"include_stale": "true"})
    assert len(r.json()) == 1


def test_get_organ_via_api(api_client):
    api_client.post("/registry/register", json={"name": "memory", "base_url": "http://localhost:8001"})
    r = api_client.get("/registry/organs/memory")
    assert r.status_code == 200
    assert r.json()["name"] == "memory"


def test_get_unknown_organ_returns_404_error_envelope(api_client):
    r = api_client.get("/registry/organs/nonexistent")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_deregister_via_api(api_client):
    api_client.post("/registry/register", json={"name": "memory", "base_url": "http://localhost:8001"})
    r = api_client.delete("/registry/organs/memory")
    assert r.status_code == 200
    assert r.json()["deregistered"] == "memory"

    r = api_client.get("/registry/organs/memory")
    assert r.status_code == 404


def test_deregister_unknown_organ_returns_404_error_envelope(api_client):
    r = api_client.delete("/registry/organs/nonexistent")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_reregistering_via_api_preserves_first_registered(api_client):
    first = api_client.post("/registry/register", json={"name": "memory", "base_url": "http://localhost:8001"}).json()
    second = api_client.post("/registry/register", json={"name": "memory", "base_url": "http://localhost:8001", "version": "0.4.0"}).json()
    assert second["first_registered"] == first["first_registered"]
    assert second["version"] == "0.4.0"
