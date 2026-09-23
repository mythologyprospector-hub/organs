"""
main.py — the Critic organ.

Run it:
    pip install fastapi uvicorn --break-system-packages
    uvicorn main:app --host 127.0.0.1 --port 8007

Stateless — every call is independent, nothing persists. Call it with
what you're ABOUT to do; it never sees what already happened.
"""
import os
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from organ_base import create_organ_app, OrganError  # noqa: E402
from organ_client import attach_to_registry  # noqa: E402
import critic_core as cc  # noqa: E402

ORGAN_NAME = "critic"
ORGAN_VERSION = "0.1.0"
SELF_BASE_URL = os.environ.get("CRITIC_BASE_URL", "http://localhost:8007")

CAPABILITIES = ["evaluate", "rules"]

app = create_organ_app(
    name=ORGAN_NAME,
    version=ORGAN_VERSION,
    description="Critic organ: deterministic risk classification for a "
                 "proposed action, BEFORE it runs. No LLM — a fixed rule "
                 "set, fails closed (unrecognized actions default to "
                 "high_risk). Can recommend; can never itself authorize "
                 "anything risky.",
    capabilities=CAPABILITIES,
)

attach_to_registry(app, name=ORGAN_NAME, base_url=SELF_BASE_URL, version=ORGAN_VERSION, capabilities=CAPABILITIES)


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except cc.CriticError as e:
        raise OrganError(code="critic_error", message=str(e), status_code=400)


class EvaluateRequest(BaseModel):
    organ: str
    method: str
    path: str
    body: Optional[dict] = None


@app.post("/critic/evaluate")
def evaluate(req: EvaluateRequest):
    return _wrap(cc.evaluate, req.organ, req.method, req.path, req.body)


@app.get("/critic/rules")
def rules():
    return cc.list_rules()
