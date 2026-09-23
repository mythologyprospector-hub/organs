"""
main.py — the Communications organ.

Run it:
    pip install fastapi uvicorn --break-system-packages
    uvicorn main:app --host 127.0.0.1 --port 8002
"""
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import Query
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from organ_base import create_organ_app, HealthCheck, OrganError  # noqa: E402
from organ_client import attach_to_registry  # noqa: E402
import comm_core as cc  # noqa: E402

ORGAN_NAME = "communications"
ORGAN_VERSION = "0.1.0"
SELF_BASE_URL = os.environ.get("COMM_BASE_URL", "http://localhost:8002")

CAPABILITIES = ["publish", "peek", "consume", "topics", "consumers", "reset_consumer", "dispatch",
                "reset_dispatch", "doctor"]


def _db_check():
    return cc.check_db()


app = create_organ_app(
    name=ORGAN_NAME,
    version=ORGAN_VERSION,
    description="Communications organ: pub/sub event bus (broadcast semantics, "
                "per-consumer cursors) plus dispatch (round-robin/random/broadcast "
                "routing among candidate organs).",
    capabilities=CAPABILITIES,
    health_checks=[HealthCheck("bus_db", _db_check)],
)

attach_to_registry(app, name=ORGAN_NAME, base_url=SELF_BASE_URL, version=ORGAN_VERSION, capabilities=CAPABILITIES)


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except cc.CommError as e:
        raise OrganError(code="comm_error", message=str(e), status_code=400)


class PublishRequest(BaseModel):
    event_type: str
    payload: dict = Field(default_factory=dict)
    publisher: str


class ConsumeRequest(BaseModel):
    consumer: str
    topics: list[str]
    limit: int = 50


class ResetConsumerRequest(BaseModel):
    to_id: int = 0


class DispatchRequest(BaseModel):
    dispatch_key: str
    candidates: list[str]
    strategy: str = "round_robin"


@app.post("/bus/topics/{topic}/publish")
def publish(topic: str, req: PublishRequest):
    return _wrap(cc.op_publish, topic, req.event_type, req.payload, req.publisher)


@app.get("/bus/topics")
def list_topics():
    return _wrap(cc.op_list_topics)


@app.get("/bus/topics/{topic}/events")
def peek(topic: str, since_id: int = Query(0), limit: int = Query(50, ge=1, le=500)):
    return _wrap(cc.op_peek, topic, since_id, limit)


@app.get("/bus/consume")
def consume(consumer: str = Query(...), topics: str = Query(..., description="comma-separated"),
            limit: int = Query(50, ge=1, le=500)):
    topic_list = [t.strip() for t in topics.split(",") if t.strip()]
    return _wrap(cc.op_consume, consumer, topic_list, limit)


@app.get("/bus/consumers")
def list_consumers():
    return _wrap(cc.op_list_consumers)


@app.post("/bus/consumers/{consumer}/topics/{topic}/reset")
def reset_consumer(consumer: str, topic: str, req: ResetConsumerRequest):
    return _wrap(cc.op_reset_consumer, consumer, topic, req.to_id)


@app.post("/bus/dispatch")
def dispatch(req: DispatchRequest):
    return _wrap(cc.op_dispatch, req.dispatch_key, req.candidates, req.strategy)


@app.post("/bus/dispatch/{dispatch_key}/reset")
def reset_dispatch(dispatch_key: str):
    return _wrap(cc.op_reset_dispatch, dispatch_key)


@app.get("/bus/doctor")
def doctor():
    return _wrap(cc.op_doctor)
