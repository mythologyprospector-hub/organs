"""
main.py — the Introspection organ.

Run it:
    pip install fastapi uvicorn --break-system-packages
    uvicorn main:app --host 127.0.0.1 --port 8005
"""
import os
import sys
from pathlib import Path

from fastapi import Query

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from organ_base import create_organ_app, OrganError  # noqa: E402
from organ_client import attach_to_registry  # noqa: E402
import introspection_core as ic  # noqa: E402

ORGAN_NAME = "introspection"
ORGAN_VERSION = "0.1.0"
SELF_BASE_URL = os.environ.get("INTROSPECT_BASE_URL", "http://localhost:8005")

CAPABILITIES = ["summary", "host", "cpu", "memory", "disk", "ollama", "docker", "dev_tools", "refresh"]

app = create_organ_app(
    name=ORGAN_NAME,
    version=ORGAN_VERSION,
    description="Introspection organ: the machine's live, queryable self-knowledge. "
                 "A deliberately scoped subset of DEEPSCAN_ROADMAP.md — host/cpu/"
                 "memory/disk, installed Ollama models, Docker state, and dev tool "
                 "presence. Not the full 13-phase atlas; built to be queried live, "
                 "not generated once and read.",
    capabilities=CAPABILITIES,
)

attach_to_registry(app, name=ORGAN_NAME, base_url=SELF_BASE_URL, version=ORGAN_VERSION, capabilities=CAPABILITIES)


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ic.IntrospectionError as e:
        raise OrganError(code="introspection_error", message=str(e), status_code=400)


@app.get("/introspect/summary")
def summary(force: bool = Query(False)):
    return _wrap(ic.op_summary, force)


@app.post("/introspect/refresh")
def refresh():
    return _wrap(ic.op_refresh)


@app.get("/introspect/host")
def host(force: bool = Query(False)):
    return _wrap(ic.op_get, "host", force)


@app.get("/introspect/cpu")
def cpu(force: bool = Query(False)):
    return _wrap(ic.op_get, "cpu", force)


@app.get("/introspect/memory")
def memory(force: bool = Query(False)):
    return _wrap(ic.op_get, "memory", force)


@app.get("/introspect/disk")
def disk(force: bool = Query(False)):
    return _wrap(ic.op_get, "disk", force)


@app.get("/introspect/ollama")
def ollama(force: bool = Query(False)):
    return _wrap(ic.op_get, "ollama", force)


@app.get("/introspect/docker")
def docker(force: bool = Query(False)):
    return _wrap(ic.op_get, "docker", force)


@app.get("/introspect/dev_tools")
def dev_tools(force: bool = Query(False)):
    return _wrap(ic.op_get, "dev_tools", force)
