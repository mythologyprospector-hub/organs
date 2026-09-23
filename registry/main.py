"""
main.py — the Registry organ.

This is the one fixed address in the whole system. Every other organ
registers itself here on startup and re-registers on an interval
(organ_client.py handles that automatically). Anything that wants to talk
to another organ asks the registry first — "where is memory right now" —
instead of a hardcoded port baked into its own code.

Run it:
    pip install fastapi uvicorn --break-system-packages
    uvicorn main:app --host 127.0.0.1 --port 8000

    (port 8000 is the convention — every organ_client defaults to looking
    for the registry here unless ORGAN_REGISTRY_URL says otherwise)
"""
import sys
from pathlib import Path

from fastapi import Query
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from organ_base import create_organ_app, OrganError  # noqa: E402
import registry_core as rc  # noqa: E402

app = create_organ_app(
    name="registry",
    version="0.1.0",
    description="The organ directory. Every organ registers here on startup "
                 "and heartbeats on an interval; this is how organs find "
                 "each other instead of hardcoding addresses.",
    capabilities=["register", "list", "lookup", "deregister"],
    # /registry/register is called by every organ's heartbeat every
    # ~10s — gating it would mean no organ could announce itself if
    # Critic were ever briefly unreachable at boot, cascading into
    # discover() failing system-wide (a genuine bootstrapping
    # circularity, not just an inconvenience). Deregistration is NOT
    # exempted — that's a real, consequential action Critic already
    # classifies via its DELETE-default rule.
    risk_gate_exempt_paths={"/registry/register"},
)


class RegisterRequest(BaseModel):
    name: str
    base_url: str
    version: str = "0.0.0"
    capabilities: list[str] = Field(default_factory=list)


@app.post("/registry/register")
def register(req: RegisterRequest):
    return rc.register(req.name, req.base_url, req.version, req.capabilities)


@app.get("/registry/organs")
def list_organs(include_stale: bool = Query(True)):
    return rc.list_all(include_stale=include_stale)


@app.get("/registry/organs/{name}")
def get_organ(name: str):
    record = rc.get(name)
    if record is None:
        raise OrganError(code="not_found", message=f"no organ registered as {name!r}", status_code=404)
    return record


@app.delete("/registry/organs/{name}")
def deregister_organ(name: str):
    if not rc.deregister(name):
        raise OrganError(code="not_found", message=f"no organ registered as {name!r}", status_code=404)
    return {"deregistered": name}
