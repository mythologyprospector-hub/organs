"""
sandbox_core.py — runs code in an ephemeral, isolated container, then
throws the whole thing away. This is the piece the future code forge
needs to actually EXECUTE what it writes — "run it for real, measure
coverage" from the forge pipeline has nowhere to happen without this.

The safety model here is deliberately different from Memory's
propose-then-a-human-decides pattern. That pattern exists because facts
and scars BECOME PERMANENT and trusted. Nothing here does — every job
gets a brand new container from a fixed base image, runs with no network
by default, hard memory/CPU/pid/time limits, and is destroyed
immediately after, success or failure. The safety property is
containment, not review. A bad job can waste its own container's
resources and nothing else — it can't touch Bucky, can't persist, can't
affect the next job.

SAFETY BOUNDARY, same discipline as Orchestrator's fixed service list:
  - Only a FIXED, pre-approved set of base images (see ALLOWED_LANGUAGES)
    — never an arbitrary image name from a request.
  - Network OFF by default. A caller can ask for it, but it's opt-in,
    never silent.
  - Every filename is sanitized against path traversal before being
    written into the job's workspace.
  - A hard, capped wall-clock timeout — nobody can request a runaway job.
  - The workspace directory is ALWAYS removed after the job, even if the
    run crashes or times out (try/finally, not "usually").

Same pattern as Orchestrator: every actual command goes through _run(),
the one seam tests replace with a fake — so job construction, filename
safety, and result parsing are all fully tested without a real Docker
daemon anywhere nearby. Docker execution itself needs live verification
on Bucky, same honest disclosure as Orchestrator's sudo path.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("SANDBOX_DEFAULT_TIMEOUT", "60"))
MAX_TIMEOUT_SECONDS = int(os.environ.get("SANDBOX_MAX_TIMEOUT", "300"))
DEFAULT_MEMORY = os.environ.get("SANDBOX_DEFAULT_MEMORY", "512m")
DEFAULT_CPUS = os.environ.get("SANDBOX_DEFAULT_CPUS", "1.0")
MAX_FILES = int(os.environ.get("SANDBOX_MAX_FILES", "50"))
MAX_TOTAL_BYTES = int(os.environ.get("SANDBOX_MAX_TOTAL_BYTES", str(2_000_000)))  # 2MB
WORKSPACE_ROOT = Path(os.environ.get("SANDBOX_WORKSPACE_ROOT", tempfile.gettempdir())) / "organ-sandbox-jobs"

# Fixed, pre-approved base images — the actual safety boundary, not a
# convenience default. Never accept an arbitrary image from a request.
ALLOWED_LANGUAGES = {
    "python": "python:3.11-slim",
    "node": "node:20-slim",
}

_COVERAGE_RE = re.compile(r"TOTAL.*?(\d+)%")


class SandboxError(Exception):
    pass


def _run(cmd: list[str], timeout: float):
    """The ONLY place a subprocess actually runs. Returns (returncode,
    stdout, stderr, timed_out: bool). Docker itself is asked to respect
    the job's timeout via --stop-timeout, but this is the hard backstop
    — if docker somehow doesn't return in time, we still don't hang the
    organ forever."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr, False
    except subprocess.TimeoutExpired:
        return -1, "", "job exceeded the hard timeout backstop", True
    except (FileNotFoundError, PermissionError) as e:
        # FileNotFoundError: docker isn't installed at all.
        # PermissionError: docker EXISTS on disk but isn't executable —
        # a real, distinct failure mode (a mounted binary without +x, a
        # restricted execution environment). Caught independently, this
        # was found by an external review running the suite in an
        # environment where `docker` exists but lacks the execute bit —
        # verified as a real gap here, not present in the environment
        # this was originally built in (which lacks docker outright),
        # which is exactly why it slipped through the first time. Both
        # mean the same thing to a caller: "docker isn't usable right
        # now," reported the same clean way either way.
        kind = "not found" if isinstance(e, FileNotFoundError) else "not executable (permission denied)"
        return 127, "", f"docker command {kind} — is Docker installed and runnable?", False


def _sanitize_filename(name: str) -> str:
    """Rejects path traversal, absolute paths, and '.' segments before
    anything ever touches disk. This runs BEFORE any file is written,
    not after.

    '.' segments matter here for a reason distinct from '..': pathlib
    silently collapses them away on join (Path('ws') / 'foo/.' ==
    Path('ws/foo')), and a filename of exactly '.' collapses all the
    way to the workspace directory itself — file_path.write_text()
    then raises IsADirectoryError, which isn't a SandboxError and so
    isn't caught by main.py's error wrapping, surfacing as an
    unhandled 500 instead of a clean rejection like every other
    malformed filename gets."""
    if not name or not name.strip():
        raise SandboxError("a file has an empty name")
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        raise SandboxError(f"filename {name!r} must be relative, not absolute")
    parts = normalized.split("/")
    if ".." in parts or "." in parts or any(p == "" for p in parts[:-1]):
        raise SandboxError(f"filename {name!r} contains path traversal — rejected")
    return normalized


def _validate_job(language: str, files: dict, timeout_seconds: int):
    if language not in ALLOWED_LANGUAGES:
        raise SandboxError(f"language must be one of {sorted(ALLOWED_LANGUAGES.keys())}, got {language!r}")
    if not files:
        raise SandboxError("a job needs at least one file")
    if len(files) > MAX_FILES:
        raise SandboxError(f"too many files ({len(files)}), max is {MAX_FILES}")
    total_bytes = sum(len(content.encode("utf-8")) for content in files.values())
    if total_bytes > MAX_TOTAL_BYTES:
        raise SandboxError(f"job is {total_bytes} bytes, max is {MAX_TOTAL_BYTES}")
    if timeout_seconds > MAX_TIMEOUT_SECONDS:
        raise SandboxError(f"timeout_seconds {timeout_seconds} exceeds the max of {MAX_TIMEOUT_SECONDS}")
    if timeout_seconds < 1:
        raise SandboxError("timeout_seconds must be at least 1")
    for name in files:
        _sanitize_filename(name)


def _build_docker_command(image: str, workspace: Path, command: str, timeout_seconds: int,
                           network: bool, memory: str, cpus: str, container_name: str) -> list[str]:
    cmd = [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", "bridge" if network else "none",
        "--memory", memory,
        "--cpus", cpus,
        "--pids-limit", "128",
        "--stop-timeout", str(timeout_seconds),
        "-v", f"{workspace}:/workspace:rw",
        "-w", "/workspace",
        image,
        "sh", "-c", command,
    ]
    return cmd


def op_run_job(language: str, files: dict, command: str, timeout_seconds: int = None,
               network: bool = False, memory: str = None, cpus: str = None):
    timeout_seconds = DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    memory = memory or DEFAULT_MEMORY
    cpus = cpus or DEFAULT_CPUS

    _validate_job(language, files, timeout_seconds)
    image = ALLOWED_LANGUAGES[language]

    job_id = uuid.uuid4().hex[:12]
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    workspace = WORKSPACE_ROOT / job_id

    try:
        workspace.mkdir(parents=True, exist_ok=False)
        for name, content in files.items():
            safe_name = _sanitize_filename(name)
            file_path = workspace / safe_name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        container_name = f"organ-sbx-{job_id}"
        docker_cmd = _build_docker_command(image, workspace, command, timeout_seconds, network, memory, cpus,
                                            container_name)

        start = time.time()
        # a little slack over the container's own timeout so docker gets
        # first chance to enforce --stop-timeout cleanly
        rc, stdout, stderr, timed_out = _run(docker_cmd, timeout=timeout_seconds + 15)
        duration = round(time.time() - start, 2)

        if timed_out:
            # The hard backstop fired: subprocess.run killed the `docker
            # run` CLI process itself before it could return, which means
            # `--rm` never got a chance to act on the container's exit —
            # the container can be left running in the daemon, invisible
            # to this process. `--name` makes it addressable, so reclaim
            # it explicitly. Best-effort: if docker is unreachable or the
            # container already ended on its own, this is a harmless no-op.
            _run(["docker", "rm", "-f", container_name], timeout=15)

        coverage_percent = None
        m = _COVERAGE_RE.search(stdout)
        if m:
            coverage_percent = int(m.group(1))

        return {
            "job_id": job_id, "language": language, "image": image, "command": command,
            "exit_code": rc, "stdout": stdout, "stderr": stderr, "timed_out": timed_out,
            "duration_seconds": duration, "coverage_percent": coverage_percent,
            "network_enabled": network, "file_count": len(files),
        }
    finally:
        # ALWAYS remove the workspace — success, failure, or timeout.
        # This is a safety property, not cleanup housekeeping.
        shutil.rmtree(workspace, ignore_errors=True)


def op_list_languages():
    return {lang: image for lang, image in ALLOWED_LANGUAGES.items()}


def op_doctor():
    rc, out, err, timed_out = _run(["docker", "--version"], timeout=5)
    return {
        "docker_available": rc == 0,
        "docker_version": out.strip() if rc == 0 else None,
        "workspace_root": str(WORKSPACE_ROOT),
        "workspace_root_writable": os.access(WORKSPACE_ROOT.parent, os.W_OK),
        "allowed_languages": list(ALLOWED_LANGUAGES.keys()),
        "max_timeout_seconds": MAX_TIMEOUT_SECONDS,
    }
