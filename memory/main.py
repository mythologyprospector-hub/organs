"""
main.py — the Memory organ, full model.

Run it:
    pip install fastapi uvicorn --break-system-packages
    uvicorn main:app --host 127.0.0.1 --port 8001
"""
import json as _json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import Query
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from organ_base import create_organ_app, HealthCheck, OrganError, correlation_headers  # noqa: E402
from organ_client import attach_to_registry, discover, RegistryError  # noqa: E402
import memory_core as mc  # noqa: E402

ORGAN_NAME = "memory"
ORGAN_VERSION = "0.3.0"
SELF_BASE_URL = os.environ.get("MEMORY_BASE_URL", "http://localhost:8001")

CAPABILITIES = [
    "add", "recall", "confirm", "list", "stats", "backfill",
    "consolidate", "proposals", "decide", "facts",
    "pin", "unpin", "prune", "archive", "revive",
    "scars", "promises", "unknowable", "relations", "doctor",
]


def _ollama_check():
    return mc.ping_ollama()


app = create_organ_app(
    name=ORGAN_NAME,
    version=ORGAN_VERSION,
    description="Memory organ: ledger with provenance/confidence, salience-based "
                 "forgetting, consolidated facts, scars (permanent behavioral "
                 "mutations), promises, unknowable placeholders, and relations "
                 "(including contradictions).",
    capabilities=CAPABILITIES,
    health_checks=[HealthCheck("ollama", _ollama_check)],
)

attach_to_registry(app, name=ORGAN_NAME, base_url=SELF_BASE_URL, version=ORGAN_VERSION, capabilities=CAPABILITIES)


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except mc.MemoryError as e:
        raise OrganError(code="memory_error", message=str(e), status_code=502 if "reach Ollama" in str(e) else 400)


def _publish_event(topic: str, event_type: str, payload: dict):
    """Fire-and-forget onto the Communications bus. Never raises, never
    blocks a Memory operation on the bus being reachable — a request that
    already succeeded locally shouldn't fail just because nobody's
    listening for it right now. Discovery goes through the registry, same
    as any other organ finding Communications; nothing here hardcodes a
    port."""
    try:
        comm_url = discover("communications")
    except RegistryError:
        return
    try:
        req = urllib.request.Request(
            f"{comm_url}/bus/topics/{topic}/publish",
            data=_json.dumps({"event_type": event_type, "payload": payload, "publisher": "memory"}).encode("utf-8"),
            headers=correlation_headers({"Content-Type": "application/json"}),
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2.0)
    except (urllib.error.URLError, urllib.error.HTTPError):
        pass


# ---------------------------------------------------------------------------
# request models
# ---------------------------------------------------------------------------

class AddRequest(BaseModel):
    text: str
    tags: list[str] = Field(default_factory=list)
    provenance: str = "unspecified"
    witness: str = "direct"
    confidence: float = 0.8
    owner: str = "user"
    may_reveal: bool = True
    may_modify: bool = True
    may_delete: bool = True


class ConsolidateRequest(BaseModel):
    threshold: float = 0.80
    min_witnesses: int = 3


class DecideRequest(BaseModel):
    decision: str


class PruneRequest(BaseModel):
    threshold: Optional[float] = None
    min_age_days: Optional[float] = None
    dry_run: bool = False


class ReviveRequest(BaseModel):
    pass


class ScarProposeRequest(BaseModel):
    trigger_event: str
    lesson: str
    confidence: float = 0.9
    source_ids: list[int] = Field(default_factory=list)
    supersedes: Optional[int] = None


class ScarDecideRequest(BaseModel):
    decision: str  # accept | reject


class PromiseRequest(BaseModel):
    text: str
    owner: str = "system"
    condition: Optional[str] = None


class PromiseResolveRequest(BaseModel):
    status: str  # fulfilled | broken | cancelled
    note: Optional[str] = None


class UnknowableRequest(BaseModel):
    description: str
    reason: str
    confidence_exists: float = 0.8
    owner_to_request: Optional[str] = None


class UnknowableResolveRequest(BaseModel):
    resolved_entry_id: int


class RelationRequest(BaseModel):
    id_a: int
    type_a: str
    id_b: int
    type_b: str
    relation_type: str
    note: Optional[str] = None


class RelationResolveRequest(BaseModel):
    resolved_which: str  # a | b | both_true_different_conditions | neither
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# entries / recall / salience
# ---------------------------------------------------------------------------

@app.post("/memory/add")
def add(req: AddRequest):
    return _wrap(mc.op_add, req.text, req.tags, req.provenance, req.witness, req.confidence,
                 req.owner, req.may_reveal, req.may_modify, req.may_delete)


@app.get("/memory/recall")
def recall(q: str = Query(...), k: int = Query(5, ge=1, le=50),
           include_archived: bool = Query(False),
           sim_weight: Optional[float] = Query(None), sal_weight: Optional[float] = Query(None)):
    return _wrap(mc.op_recall, q, k, include_archived, sim_weight, sal_weight)


@app.post("/memory/entries/{entry_id}/confirm")
def confirm(entry_id: int):
    return _wrap(mc.op_confirm, entry_id)


@app.get("/memory/entries/{entry_id}")
def get_entry(entry_id: int):
    return _wrap(mc.op_get_entry, entry_id)


@app.post("/memory/entries/{entry_id}/pin")
def pin(entry_id: int):
    return _wrap(mc.op_pin, entry_id)


@app.delete("/memory/entries/{entry_id}/pin")
def unpin(entry_id: int):
    return _wrap(mc.op_unpin, entry_id)


@app.get("/memory/list")
def list_entries(n: int = Query(20, ge=1, le=1000)):
    return _wrap(mc.op_list, n)


@app.get("/memory/stats")
def stats():
    return _wrap(mc.op_stats)


@app.post("/memory/backfill")
def backfill():
    return _wrap(mc.op_backfill)


@app.post("/memory/prune")
def prune(req: PruneRequest):
    return _wrap(mc.op_prune, req.threshold, req.min_age_days, req.dry_run)


@app.get("/memory/archived")
def list_archived(n: int = Query(20, ge=1, le=1000)):
    return _wrap(mc.op_list_archived, n)


@app.post("/memory/entries/{entry_id}/revive")
def revive(entry_id: int, req: ReviveRequest = ReviveRequest()):
    return _wrap(mc.op_revive, entry_id)


@app.get("/memory/doctor")
def doctor():
    return _wrap(mc.op_doctor)


# ---------------------------------------------------------------------------
# facts (consolidation)
# ---------------------------------------------------------------------------

@app.post("/memory/consolidate")
def consolidate(req: ConsolidateRequest):
    return _wrap(mc.op_consolidate, req.threshold, req.min_witnesses)


@app.get("/memory/proposals")
def list_proposals(status: Optional[str] = Query("pending")):
    return _wrap(mc.op_list_proposals, status)


@app.post("/memory/proposals/{proposal_id}/decide")
def decide_proposal(proposal_id: str, req: DecideRequest):
    result = _wrap(mc.op_decide_proposal, proposal_id, req.decision)
    if result["status"] == "accepted":
        _publish_event("memory.facts", "fact_added", {
            "fact": result["proposed_fact"], "source_ids": result["source_ids"],
        })
    return result


@app.get("/memory/facts")
def facts(n: int = Query(20, ge=1, le=1000)):
    return _wrap(mc.op_facts, n)


# ---------------------------------------------------------------------------
# scars
# ---------------------------------------------------------------------------

@app.post("/memory/scars/propose")
def propose_scar(req: ScarProposeRequest):
    return _wrap(mc.op_propose_scar, req.trigger_event, req.lesson, req.confidence, req.source_ids, req.supersedes)


@app.get("/memory/scars/proposals")
def list_scar_proposals(status: Optional[str] = Query("pending")):
    return _wrap(mc.op_list_scar_proposals, status)


@app.post("/memory/scars/proposals/{proposal_id}/decide")
def decide_scar(proposal_id: str, req: ScarDecideRequest):
    result = _wrap(mc.op_decide_scar, proposal_id, req.decision)
    if result["status"] == "accepted":
        event_type = "scar_superseded" if result.get("supersedes") else "scar_added"
        _publish_event("memory.scars", event_type, {
            "scar_id": result["scar_id"], "lesson": result["lesson"], "supersedes": result.get("supersedes"),
        })
    return result


@app.get("/memory/scars")
def list_scars(status: Optional[str] = Query("active")):
    return _wrap(mc.op_list_scars, status)


# ---------------------------------------------------------------------------
# promises
# ---------------------------------------------------------------------------

@app.post("/memory/promises")
def add_promise(req: PromiseRequest):
    return _wrap(mc.op_add_promise, req.text, req.owner, req.condition)


@app.get("/memory/promises")
def list_promises(status: Optional[str] = Query("pending")):
    return _wrap(mc.op_list_promises, status)


@app.post("/memory/promises/{promise_id}/resolve")
def resolve_promise(promise_id: int, req: PromiseResolveRequest):
    result = _wrap(mc.op_resolve_promise, promise_id, req.status, req.note)
    _publish_event("memory.promises", "promise_resolved", {
        "promise_id": promise_id, "status": result["status"], "note": result.get("resolution_note"),
    })
    return result


# ---------------------------------------------------------------------------
# unknowable
# ---------------------------------------------------------------------------

@app.post("/memory/unknowable")
def add_unknowable(req: UnknowableRequest):
    return _wrap(mc.op_add_unknowable, req.description, req.reason, req.confidence_exists, req.owner_to_request)


@app.get("/memory/unknowable")
def list_unknowable(status: Optional[str] = Query("inaccessible")):
    return _wrap(mc.op_list_unknowable, status)


@app.post("/memory/unknowable/{unknowable_id}/resolve")
def resolve_unknowable(unknowable_id: int, req: UnknowableResolveRequest):
    result = _wrap(mc.op_resolve_unknowable, unknowable_id, req.resolved_entry_id)
    _publish_event("memory.unknowable", "unknowable_resolved", {
        "unknowable_id": unknowable_id, "resolved_entry_id": req.resolved_entry_id,
    })
    return result


# ---------------------------------------------------------------------------
# relations
# ---------------------------------------------------------------------------

@app.post("/memory/relations")
def add_relation(req: RelationRequest):
    return _wrap(mc.op_add_relation, req.id_a, req.type_a, req.id_b, req.type_b, req.relation_type, req.note)


@app.get("/memory/relations")
def list_relations(status: Optional[str] = Query(None), relation_type: Optional[str] = Query(None)):
    return _wrap(mc.op_list_relations, status, relation_type)


@app.post("/memory/relations/{relation_id}/resolve")
def resolve_relation(relation_id: int, req: RelationResolveRequest):
    result = _wrap(mc.op_resolve_relation, relation_id, req.resolved_which, req.note)
    _publish_event("memory.relations", "relation_resolved", {
        "relation_id": relation_id, "resolved_which": result["resolved_which"], "note": result.get("resolution_note"),
    })
    return result
