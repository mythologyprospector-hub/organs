"""
io_interface_core.py — the real front door: a person types something,
this figures out which organ should handle it and routes there, instead
of them knowing which curl command to run.

DELIBERATE SCOPE: this is pattern matching against a fixed, curated
catalog of known intents — NOT an LLM freely interpreting arbitrary
requests into arbitrary API calls. Same reasoning as Critic: an 8B local
model guessing at API calls from natural language is exactly the
"moon-shot cognition" this system's own principle says to avoid instead
of a small deterministic organ. This is that deterministic organ.

Nothing here bypasses the safety architecture already built:
    1. Interpret text -> a single proposed action (organ/method/path/body)
    2. Ask the REAL Critic to classify it — same gate everything else uses
    3. safe/reversible -> execute directly, always show what was done
    4. caution/high_risk -> create a real Executive goal instead of
       running it, so a human decides — no shortcut around approval just
       because the request arrived as a sentence instead of a curl call

If nothing in the catalog matches, this says so plainly and shows what
it DOES understand — it never guesses at an action it isn't confident
about. Silence or a wrong guess are both worse than "I don't know how to
do that yet."
"""
import re
from urllib.parse import quote


class IOError_(Exception):
    """Named to avoid shadowing the builtin IOError."""
    pass


# ---------------------------------------------------------------------------
# the catalog — ordered, first match wins, same shape as Critic's rule table
# ---------------------------------------------------------------------------

def _build_memory_recall(m):
    q = m.group(1).strip()
    return f"/memory/recall?q={quote(q)}&k=5", None


def _build_memory_add(m):
    text = m.group(1).strip()
    return "/memory/add", {"text": text, "tags": ["from_io_interface"]}


def _build_memory_stats(m):
    return "/memory/stats", None


def _build_memory_promise(m):
    text = m.group(1).strip()
    return "/memory/promises", {"text": text}


def _build_introspect_summary(m):
    return "/introspect/summary", None


def _build_introspect_ollama(m):
    return "/introspect/ollama", None


def _build_introspect_docker(m):
    return "/introspect/docker", None


def _build_orchestrator_status(m):
    name = m.group(1).strip()
    return f"/orchestrator/services/{name}", None


def _build_orchestrator_restart(m):
    name = m.group(1).strip()
    return f"/orchestrator/services/{name}/restart", None


def _build_orchestrator_stop(m):
    name = m.group(1).strip()
    return f"/orchestrator/services/{name}/stop", None


def _build_orchestrator_start(m):
    name = m.group(1).strip()
    return f"/orchestrator/services/{name}/start", None


def _build_reflection_status(m):
    return "/reflection/status", None


def _build_reflection_enable(m):
    return "/reflection/enable", None


def _build_reflection_disable(m):
    return "/reflection/disable", None


def _build_sandbox_python(m):
    code = m.group(1).strip()
    return "/sandbox/jobs", {"language": "python", "files": {"main.py": code}, "command": "python main.py"}


_FORGE_LANGUAGE_EXT = {"python": "py", "node": "js"}


def _build_forge_build(m):
    filename_hint = m.group(2)
    spec = m.group(3).strip().rstrip(".")

    # deliberately narrow: Sandbox only knows "python" and "node" (see
    # sandbox_core.ALLOWED_LANGUAGES) — anything this doesn't recognize
    # falls back to python rather than passing through an arbitrary
    # word Forge/Sandbox wouldn't understand later if this build is
    # ever extended with a test step
    text_lower = m.string.lower()
    language = "node" if re.search(r"\b(?:node|javascript|js)\b", text_lower) else "python"
    ext = _FORGE_LANGUAGE_EXT[language]

    if filename_hint:
        filename = filename_hint if "." in filename_hint else f"{filename_hint}.{ext}"
    else:
        filename = f"main.{ext}"

    return "/forge/build", {"spec": spec, "language": language, "filename": filename}


CATALOG = [
    {"name": "memory_recall", "organ": "memory", "method": "GET",
     "pattern": re.compile(r"(?:what do you know about|recall|do you remember)\s+(.+)", re.I),
     "build": _build_memory_recall,
     "example": "what do you know about the deploy key"},

    {"name": "memory_add", "organ": "memory", "method": "POST",
     "pattern": re.compile(r"remember (?:that\s+)?(.+)", re.I),
     "build": _build_memory_add,
     "example": "remember that the registry runs on port 8000"},

    {"name": "memory_promise", "organ": "memory", "method": "POST",
     "pattern": re.compile(r"(?:remind me to|promise to)\s+(.+)", re.I),
     "build": _build_memory_promise,
     "example": "remind me to check the sandbox logs"},

    {"name": "memory_stats", "organ": "memory", "method": "GET",
     "pattern": re.compile(r"(?:memory stats|how much do you remember)", re.I),
     "build": _build_memory_stats,
     "example": "memory stats"},

    {"name": "introspect_summary", "organ": "introspection", "method": "GET",
     "pattern": re.compile(r"(?:system status|system summary|what.?s running|what does (?:this|the) machine look like)", re.I),
     "build": _build_introspect_summary,
     "example": "system status"},

    {"name": "introspect_ollama", "organ": "introspection", "method": "GET",
     "pattern": re.compile(r"(?:what|which) (?:ollama )?models(?: are installed)?", re.I),
     "build": _build_introspect_ollama,
     "example": "what models are installed"},

    {"name": "introspect_docker", "organ": "introspection", "method": "GET",
     "pattern": re.compile(r"(?:docker status|what containers|what.?s in docker)", re.I),
     "build": _build_introspect_docker,
     "example": "what containers are running"},

    {"name": "reflection_status", "organ": "reflection", "method": "GET",
     "pattern": re.compile(r"(?:reflection status|are you thinking)", re.I),
     "build": _build_reflection_status,
     "example": "reflection status"},

    {"name": "reflection_enable", "organ": "reflection", "method": "POST",
     "pattern": re.compile(r"(?:enable|turn on|start) reflect(?:ion|ing)", re.I),
     "build": _build_reflection_enable,
     "example": "enable reflection"},

    {"name": "reflection_disable", "organ": "reflection", "method": "POST",
     "pattern": re.compile(r"(?:disable|turn off|stop) reflect(?:ion|ing)", re.I),
     "build": _build_reflection_disable,
     "example": "disable reflection"},

    # Reflection's own start/stop phrasing ("start reflecting", "stop
    # reflecting") must be matched BEFORE the generic orchestrator
    # start/stop patterns below — otherwise "start reflecting" is
    # swallowed by orchestrator_start as a request to start a service
    # literally named "reflecting", which doesn't exist.
    {"name": "orchestrator_restart", "organ": "orchestrator", "method": "POST",
     "pattern": re.compile(r"restart (?:the\s+)?(\w[\w.-]*)", re.I),
     "build": _build_orchestrator_restart,
     "example": "restart ollama"},

    {"name": "orchestrator_stop", "organ": "orchestrator", "method": "POST",
     "pattern": re.compile(r"stop (?:the\s+)?(\w[\w.-]*)", re.I),
     "build": _build_orchestrator_stop,
     "example": "stop oi-sandbox"},

    {"name": "orchestrator_start", "organ": "orchestrator", "method": "POST",
     "pattern": re.compile(r"start (?:the\s+)?(\w[\w.-]*)", re.I),
     "build": _build_orchestrator_start,
     "example": "start oi-sandbox"},

    {"name": "orchestrator_status", "organ": "orchestrator", "method": "GET",
     "pattern": re.compile(r"\b(?:is|status of)\s+(\w[\w.-]*)(?:\s+running)?", re.I),
     "build": _build_orchestrator_status,
     "example": "is ollama running"},

    {"name": "forge_build", "organ": "forge", "method": "POST",
     "pattern": re.compile(
         r"(?:(?:build|write|make|create)\s+)?(?:me\s+)?an?\s+(?:\w+\s+)?(script|function|program)"
         r"(?:\s+(?:called|named)\s+(\S+))?\s+(?:that|to|which)\s+(.+)", re.I),
     "build": _build_forge_build,
     "example": "a script that prints hello world"},

    {"name": "sandbox_run_python", "organ": "sandbox", "method": "POST",
     "pattern": re.compile(r"run this python(?: code)?:\s*(.+)", re.I | re.S),
     "build": _build_sandbox_python,
     "example": "run this python code: print(1+1)"},
]


def op_interpret(text: str):
    if not text or not text.strip():
        raise IOError_("text must not be empty")
    text = text.strip()

    for entry in CATALOG:
        m = entry["pattern"].search(text)
        if m:
            path, body = entry["build"](m)
            return {
                "matched": True, "intent": entry["name"], "organ": entry["organ"],
                "method": entry["method"], "path": path, "body": body,
            }

    return {
        "matched": False,
        "message": "I don't recognize that request yet.",
        "examples": [entry["example"] for entry in CATALOG],
    }


def op_handle(text: str, evaluate_risk, execute_call, create_gated_goal):
    """The three real actions are injected — evaluate_risk calls the
    real Critic, execute_call makes the real target-organ call,
    create_gated_goal creates a real Executive goal for anything Critic
    flags. Tests inject fakes for all three so the routing/gating logic
    itself is fully covered without a real network."""
    interpretation = op_interpret(text)
    if not interpretation["matched"]:
        return {"action_taken": False, **interpretation}

    organ, method, path, body = interpretation["organ"], interpretation["method"], interpretation["path"], interpretation["body"]
    risk = evaluate_risk(organ, method, path, body)

    result_envelope = {
        "action_taken": False,
        "interpreted_as": {"intent": interpretation["intent"], "organ": organ, "method": method, "path": path, "body": body},
        "risk": risk,
    }

    if not risk.get("requires_human_approval", True):  # fail closed if malformed
        try:
            result = execute_call(organ, method, path, body)
            result_envelope["action_taken"] = True
            result_envelope["result"] = result
        except Exception as e:
            result_envelope["error"] = str(e)
        return result_envelope

    goal = create_gated_goal(text, organ, method, path, body)
    result_envelope["needs_approval"] = True
    result_envelope["goal"] = goal
    return result_envelope
