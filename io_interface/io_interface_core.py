"""Operational I/O routing plus the bounded Renaissance semantic handoff."""

import re
from urllib.parse import quote


class IOError_(Exception):
    pass


def _build_memory_recall(m):
    return f"/memory/recall?q={quote(m.group(1).strip())}&k=5", None


def _build_memory_add(m):
    return "/memory/add", {"text": m.group(1).strip(), "tags": ["from_io_interface"]}


def _build_memory_stats(m): return "/memory/stats", None
def _build_memory_promise(m): return "/memory/promises", {"text": m.group(1).strip()}
def _build_introspect_summary(m): return "/introspect/summary", None
def _build_introspect_ollama(m): return "/introspect/ollama", None
def _build_introspect_docker(m): return "/introspect/docker", None
def _build_orchestrator_status(m):\n    service = (m.group(1) or m.group(2)).strip()\n    return f"/orchestrator/services/{service}", None
def _build_orchestrator_restart(m): return f"/orchestrator/services/{m.group(1).strip()}/restart", None
def _build_orchestrator_stop(m): return f"/orchestrator/services/{m.group(1).strip()}/stop", None
def _build_orchestrator_start(m): return f"/orchestrator/services/{m.group(1).strip()}/start", None
def _build_reflection_status(m): return "/reflection/status", None
def _build_reflection_enable(m): return "/reflection/enable", None
def _build_reflection_disable(m): return "/reflection/disable", None
def _build_sandbox_python(m):
    return "/sandbox/jobs", {"language": "python", "files": {"main.py": m.group(1).strip()}, "command": "python main.py"}


CATALOG = [
    {"name": "memory_recall", "organ": "memory", "method": "GET", "pattern": re.compile(r"(?:what do you know about|recall|do you remember)\s+(.+)", re.I), "build": _build_memory_recall, "example": "what do you know about the deploy key"},
    {"name": "memory_add", "organ": "memory", "method": "POST", "pattern": re.compile(r"remember (?:that\s+)?(.+)", re.I), "build": _build_memory_add, "example": "remember that the registry runs on port 8000"},
    {"name": "memory_promise", "organ": "memory", "method": "POST", "pattern": re.compile(r"(?:remind me to|promise to)\s+(.+)", re.I), "build": _build_memory_promise, "example": "remind me to check the sandbox logs"},
    {"name": "memory_stats", "organ": "memory", "method": "GET", "pattern": re.compile(r"(?:memory stats|how much do you remember)", re.I), "build": _build_memory_stats, "example": "memory stats"},
    {"name": "introspect_summary", "organ": "introspection", "method": "GET", "pattern": re.compile(r"(?:system status|system summary|what.?s running|what does (?:this|the) machine look like)", re.I), "build": _build_introspect_summary, "example": "system status"},
    {"name": "introspect_ollama", "organ": "introspection", "method": "GET", "pattern": re.compile(r"(?:what|which) (?:ollama )?models(?: are installed)?", re.I), "build": _build_introspect_ollama, "example": "what models are installed"},
    {"name": "introspect_docker", "organ": "introspection", "method": "GET", "pattern": re.compile(r"(?:docker status|what containers|what.?s in docker)", re.I), "build": _build_introspect_docker, "example": "what containers are running"},
    {"name": "reflection_status", "organ": "reflection", "method": "GET", "pattern": re.compile(r"(?:reflection status|are you thinking)", re.I), "build": _build_reflection_status, "example": "reflection status"},
    {"name": "reflection_enable", "organ": "reflection", "method": "POST", "pattern": re.compile(r"(?:enable|turn on|start) reflect(?:ion|ing)", re.I), "build": _build_reflection_enable, "example": "enable reflection"},
    {"name": "reflection_disable", "organ": "reflection", "method": "POST", "pattern": re.compile(r"(?:disable|turn off|stop) reflect(?:ion|ing)", re.I), "build": _build_reflection_disable, "example": "disable reflection"},
    {"name": "orchestrator_restart", "organ": "orchestrator", "method": "POST", "pattern": re.compile(r"restart (?:the\s+)?(\w[\w.-]*)", re.I), "build": _build_orchestrator_restart, "example": "restart ollama"},
    {"name": "orchestrator_stop", "organ": "orchestrator", "method": "POST", "pattern": re.compile(r"stop (?:the\s+)?(\w[\w.-]*)", re.I), "build": _build_orchestrator_stop, "example": "stop oi-sandbox"},
    {"name": "orchestrator_start", "organ": "orchestrator", "method": "POST", "pattern": re.compile(r"start (?:the\s+)?(\w[\w.-]*)", re.I), "build": _build_orchestrator_start, "example": "start oi-sandbox"},
    {"name": "orchestrator_status", "organ": "orchestrator", "method": "GET", "pattern": re.compile(r"\b(?:is\s+(\w[\w.-]*)\s+running|status of\s+(\w[\w.-]*))\b", re.I), "build": _build_orchestrator_status, "example": "is ollama running"},
    {"name": "sandbox_run_python", "organ": "sandbox", "method": "POST", "pattern": re.compile(r"run this python(?: code)?:\s*(.+)", re.I | re.S), "build": _build_sandbox_python, "example": "run this python code: print(1+1)"},
]


def op_interpret(text: str, renaissance_handoff=None):
    if not text or not text.strip():
        raise IOError_("text must not be empty")
    text = text.strip()

    for entry in CATALOG:
        match = entry["pattern"].search(text)
        if match:
            path, body = entry["build"](match)
            return {"matched": True, "intent": entry["name"], "organ": entry["organ"],
                    "method": entry["method"], "path": path, "body": body}

    if renaissance_handoff is not None:
        result = renaissance_handoff(text)
        if result is not None:
            return result

    return {"matched": False, "message": "I don't recognize that request yet.",
            "examples": [entry["example"] for entry in CATALOG]}


def op_handle(text, evaluate_risk, execute_call, create_gated_goal, renaissance_handoff=None):
    interpretation = op_interpret(text, renaissance_handoff)

    if interpretation.get("disposition") in {"conversation", "clarify", "capability_request", "unsupported"}:
        return {"action_taken": False, "renaissance": interpretation}

    if not interpretation["matched"]:
        return {"action_taken": False, **interpretation}

    organ, method, path, body = interpretation["organ"], interpretation["method"], interpretation["path"], interpretation["body"]
    risk = evaluate_risk(organ, method, path, body)
    result_envelope = {
        "action_taken": False,
        "interpreted_as": {"intent": interpretation["intent"], "organ": organ, "method": method, "path": path, "body": body},
        "risk": risk,
    }

    if not risk.get("requires_human_approval", True):
        try:
            result_envelope["result"] = execute_call(organ, method, path, body)
            result_envelope["action_taken"] = True
        except Exception as e:
            result_envelope["error"] = str(e)
        return result_envelope

    result_envelope["needs_approval"] = True
    result_envelope["goal"] = create_gated_goal(text, organ, method, path, body)
    return result_envelope
