"""
orchestrator_core.py — manages OS-level dependencies (Ollama, Open WebUI,
the OI sandbox), NOT organs themselves. That's a deliberate boundary:

    Registry organ     -> tracks ORGANS (who's alive, discoverable by name)
    Orchestrator organ -> tracks SERVICES organs depend on (is Ollama up)

Different layer, different failure mode: an organ dying is "restart the
process," a dependency being down is "the thing underneath the organs
isn't there yet."

SAFETY BOUNDARY, not an implementation detail: services are a FIXED,
PRE-DEFINED set loaded from services.json. There is no API surface that
accepts an arbitrary command, container name, or unit name from a
request — every operation is "start/stop/status THIS service, by name,
from the list I already know about." That's what keeps an organ that can
touch the OS from being a remote-command-execution hole.

Drivers, one per kind of thing a service can be:
    systemd_user   — systemctl --user (no sudo — this process's own scope)
    systemd_system — systemctl (status is readable without sudo; start/
                     stop needs `sudo -n`, which fails FAST and CLEARLY
                     if passwordless sudo isn't configured, rather than
                     hanging a request waiting on a password prompt that
                     will never come)
    docker         — docker inspect / start / stop

Every driver call goes through _run(), the one place that actually
shells out — tests replace it with a fake, so all the dispatch/parsing/
validation logic here is fully covered without a real systemd or docker
daemon anywhere nearby.
"""
import json
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("ORCH_CONFIG_PATH", str(HERE / "services.json"))).expanduser()

VALID_DRIVERS = {"systemd_user", "systemd_system", "docker"}
DEFAULT_TIMEOUT = 10


class OrchestratorError(Exception):
    """Raised on any failure the API layer should turn into an OrganError."""


def _run(cmd: list[str], timeout: float = DEFAULT_TIMEOUT):
    """The ONLY place a subprocess actually runs. Returns (returncode,
    stdout, stderr). Never raises for a normal command failure (non-zero
    exit is a valid, expected result to report) — only raises
    OrchestratorError for things like the binary not existing or a
    timeout, which are operational problems, not "service is stopped."
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired as e:
        raise OrchestratorError(f"command timed out after {timeout}s: {' '.join(cmd)}") from e
    except FileNotFoundError as e:
        raise OrchestratorError(f"command not found: {cmd[0]} (is it installed / on PATH?)") from e
    except PermissionError as e:
        # Distinct from FileNotFoundError: the binary exists on disk but
        # isn't executable (missing +x, a restricted execution
        # environment). Same operational-problem category as "not
        # found" — both mean the command genuinely couldn't run.
        raise OrchestratorError(f"command not executable (permission denied): {cmd[0]}") from e


# ---------------------------------------------------------------------------
# service registry (fixed, config-driven — see module docstring)
# ---------------------------------------------------------------------------

DEFAULT_SERVICES = {
    "ollama": {
        "driver": "systemd_system", "unit": "ollama.service",
        "always_on": True, "description": "Local LLM inference (Ollama)",
    },
    "open-webui": {
        "driver": "docker", "container": "open-webui",
        "always_on": True, "description": "Chat UI (Open WebUI, in Docker)",
    },
    "oi-sandbox": {
        "driver": "docker", "container": "REPLACE_ME_oi_container_name",
        "always_on": False, "description": "OI agent sandbox — on-demand, fine to be stopped by default",
    },
}


def ensure_config():
    needs_defaults = not CONFIG_PATH.exists() or CONFIG_PATH.stat().st_size == 0
    if needs_defaults:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(DEFAULT_SERVICES, indent=2))


def load_services():
    ensure_config()
    try:
        return json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError as e:
        raise OrchestratorError(f"services.json is not valid JSON: {e}") from e


def get_service_def(name: str):
    services = load_services()
    if name not in services:
        raise OrchestratorError(f"no service named {name!r} in {CONFIG_PATH} — known: {sorted(services.keys())}")
    svc = services[name]
    if svc.get("driver") not in VALID_DRIVERS:
        raise OrchestratorError(f"service {name!r} has invalid driver {svc.get('driver')!r}")
    return svc


# ---------------------------------------------------------------------------
# drivers — each returns a normalized status: running | stopped | not_found | error
# ---------------------------------------------------------------------------

def _status_systemd_user(unit: str):
    rc, out, err = _run(["systemctl", "--user", "is-active", unit])
    if out == "active":
        return "running", out
    if out in ("inactive", "failed"):
        return "stopped", out
    return "error", (out or err)


def _status_systemd_system(unit: str):
    rc, out, err = _run(["systemctl", "is-active", unit])
    if out == "active":
        return "running", out
    if out in ("inactive", "failed"):
        return "stopped", out
    return "error", (out or err)


def _status_docker(container: str):
    rc, out, err = _run(["docker", "inspect", "-f", "{{.State.Running}}", container])
    if rc != 0:
        if "No such object" in err or "No such container" in err:
            return "not_found", f"no container named {container!r}"
        return "error", err
    return ("running", out) if out == "true" else ("stopped", out)


def check_status(name: str, svc: dict = None):
    svc = svc or get_service_def(name)
    driver = svc["driver"]
    if driver == "systemd_user":
        state, detail = _status_systemd_user(svc["unit"])
    elif driver == "systemd_system":
        state, detail = _status_systemd_system(svc["unit"])
    elif driver == "docker":
        state, detail = _status_docker(svc["container"])
    else:
        state, detail = "error", f"unknown driver {driver!r}"

    return {
        "name": name, "driver": driver, "always_on": svc.get("always_on", False),
        "description": svc.get("description", ""), "status": state, "detail": detail,
        "checked_ts": time.time(),
    }


def _start_systemd_user(unit: str):
    rc, out, err = _run(["systemctl", "--user", "start", unit])
    return rc == 0, (err or out or "started")


def _start_systemd_system(unit: str):
    rc, out, err = _run(["sudo", "-n", "systemctl", "start", unit])
    if rc != 0 and ("password" in err.lower() or "a password is required" in err.lower()):
        return False, (
            "start requires sudo, and passwordless sudo isn't configured for this command. "
            "Add a scoped NOPASSWD rule (see README) or start it manually: "
            f"sudo systemctl start {unit}"
        )
    return rc == 0, (err or out or "started")


def _start_docker(container: str):
    rc, out, err = _run(["docker", "start", container])
    return rc == 0, (err or out or "started")


def op_start(name: str):
    svc = get_service_def(name)
    current = check_status(name, svc)
    if current["status"] == "running":
        return {"name": name, "action": "start", "success": True, "detail": "already running", "status": "running"}

    driver = svc["driver"]
    if driver == "systemd_user":
        ok, detail = _start_systemd_user(svc["unit"])
    elif driver == "systemd_system":
        ok, detail = _start_systemd_system(svc["unit"])
    elif driver == "docker":
        ok, detail = _start_docker(svc["container"])
    else:
        ok, detail = False, f"unknown driver {driver!r}"

    new_status = check_status(name, svc)["status"] if ok else current["status"]
    return {"name": name, "action": "start", "success": ok, "detail": detail, "status": new_status}


def _stop_systemd_user(unit: str):
    rc, out, err = _run(["systemctl", "--user", "stop", unit])
    return rc == 0, (err or out or "stopped")


def _stop_systemd_system(unit: str):
    rc, out, err = _run(["sudo", "-n", "systemctl", "stop", unit])
    if rc != 0 and ("password" in err.lower() or "a password is required" in err.lower()):
        return False, (
            "stop requires sudo, and passwordless sudo isn't configured for this command. "
            "Add a scoped NOPASSWD rule (see README) or stop it manually: "
            f"sudo systemctl stop {unit}"
        )
    return rc == 0, (err or out or "stopped")


def _stop_docker(container: str):
    rc, out, err = _run(["docker", "stop", container])
    return rc == 0, (err or out or "stopped")


def op_stop(name: str):
    svc = get_service_def(name)
    current = check_status(name, svc)
    if current["status"] == "stopped":
        return {"name": name, "action": "stop", "success": True, "detail": "already stopped", "status": "stopped"}
    if current["status"] == "not_found":
        return {"name": name, "action": "stop", "success": True, "detail": "not found (nothing to stop)", "status": "not_found"}

    driver = svc["driver"]
    if driver == "systemd_user":
        ok, detail = _stop_systemd_user(svc["unit"])
    elif driver == "systemd_system":
        ok, detail = _stop_systemd_system(svc["unit"])
    elif driver == "docker":
        ok, detail = _stop_docker(svc["container"])
    else:
        ok, detail = False, f"unknown driver {driver!r}"

    new_status = check_status(name, svc)["status"] if ok else current["status"]
    return {"name": name, "action": "stop", "success": ok, "detail": detail, "status": new_status}


def op_restart(name: str):
    stop_result = op_stop(name)
    if not stop_result["success"] and stop_result["status"] not in ("stopped", "not_found"):
        return {"name": name, "action": "restart", "success": False,
                "detail": f"stop failed: {stop_result['detail']}", "status": stop_result["status"]}
    return op_start(name)


def op_list():
    services = load_services()
    return [check_status(name, svc) for name, svc in sorted(services.items())]


def op_get(name: str):
    return check_status(name)


def op_doctor():
    ensure_config()
    services = load_services()
    return {
        "config_path": str(CONFIG_PATH),
        "config_readable": CONFIG_PATH.exists(),
        "service_count": len(services),
        "services": list(services.keys()),
    }
