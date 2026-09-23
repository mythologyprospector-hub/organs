"""
introspection_core.py — the machine's live self-knowledge, scoped on purpose.

DEEPSCAN_ROADMAP.md sketched 13 phases (CPU, storage, GPU, OS, dev
ecosystem, project intelligence, AI ecosystem, containers, user
environment, security surface, storage forensics, health report,
knowledge graph). Building all of that now would repeat the exact
mistake GOAL.md's first draft made — impressive on paper, never
finished. This ships the subset that's actually load-bearing for what
exists TODAY:

    host        — OS, kernel, arch, uptime
    cpu         — model, core count, load average
    memory      — total/used/free
    disk        — real filesystems and their usage
    ollama      — installed models (every organ's shared dependency)
    docker      — containers and images (Orchestrator's territory, but
                  reported here as fact, not managed)
    dev_tools   — what's actually installed and runnable (git, node,
                  rustc, python, etc.) — this is the piece the future
                  code forge will genuinely depend on, not a nice-to-have

Everything else from the roadmap (GPU details, security surface, storage
forensics, the full knowledge graph) is deliberately NOT built. This is
a live-queryable replacement for a one-time report, not the whole atlas.

Same pattern as Orchestrator: every actual command goes through _run(),
the one seam tests replace with fake output — so all the PARSING logic
here is fully covered without needing a real machine, while live
verification proves the parsers hold up against real command output.
"""
import os
import re
import subprocess
import time
from pathlib import Path

DEFAULT_TIMEOUT = 8
CACHE_TTL_SECONDS = float(os.environ.get("INTROSPECT_CACHE_TTL", "30"))

DEV_TOOLS = {
    "git": ["git", "--version"],
    "python3": ["python3", "--version"],
    "pip3": ["pip3", "--version"],
    "node": ["node", "--version"],
    "npm": ["npm", "--version"],
    "rustc": ["rustc", "--version"],
    "cargo": ["cargo", "--version"],
    "gcc": ["gcc", "--version"],
    "docker": ["docker", "--version"],
    "ollama": ["ollama", "--version"],
}

_cache = {}  # {collector_name: (result, fetched_ts)}


class IntrospectionError(Exception):
    pass


def _run(cmd: list[str], timeout: float = DEFAULT_TIMEOUT):
    """The only place a subprocess actually runs. Returns (returncode,
    stdout, stderr). Never raises for a command that just fails or isn't
    installed — that's a normal, expected result to report, not an
    operational error.

    Uses the actual POSIX shell convention for the two failure codes
    below (127 = command not found, 126 = found but not executable)
    rather than collapsing both into 127 the way sandbox_core's _run()
    does. That collapse is fine for Sandbox, which only needs "docker
    usable or not" as a single fact — but every caller here
    (collect_ollama, collect_docker, collect_dev_tools) branches
    specifically on rc == 127 to mean "not installed," and this organ's
    entire purpose is accurately reporting installed vs. executable as
    two DIFFERENT facts. Collapsing them would make a tool that's
    installed-but-not-executable get reported as not installed at all —
    exactly the kind of inaccuracy an introspection tool exists to
    avoid."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"timed out after {timeout}s"
    except FileNotFoundError:
        return 127, "", "command not found"
    except PermissionError:
        return 126, "", "command not executable (permission denied)"


def _read_file(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError:
        return ""


def _cached(name, collector_fn):
    now = time.time()
    if name in _cache:
        result, fetched_ts = _cache[name]
        if now - fetched_ts < CACHE_TTL_SECONDS:
            return result
    result = collector_fn()
    _cache[name] = (result, now)
    return result


def clear_cache():
    _cache.clear()


# ---------------------------------------------------------------------------
# collectors — each one parses real command/file output into structured data
# ---------------------------------------------------------------------------

def collect_host():
    rc, out, err = _run(["uname", "-srm"])
    parts = out.strip().split()
    kernel_name = parts[0] if len(parts) > 0 else "unknown"
    kernel_release = parts[1] if len(parts) > 1 else "unknown"
    arch = parts[2] if len(parts) > 2 else "unknown"

    rc2, hostname_out, _ = _run(["hostname"])
    hostname = hostname_out.strip() or "unknown"

    os_release = _read_file("/etc/os-release")
    pretty_name = "unknown"
    m = re.search(r'^PRETTY_NAME="?([^"\n]+)"?', os_release, re.MULTILINE)
    if m:
        pretty_name = m.group(1)

    uptime_raw = _read_file("/proc/uptime")
    uptime_seconds = None
    if uptime_raw:
        try:
            uptime_seconds = float(uptime_raw.split()[0])
        except (ValueError, IndexError):
            pass

    return {
        "hostname": hostname, "os": pretty_name, "kernel": f"{kernel_name} {kernel_release}",
        "arch": arch, "uptime_seconds": uptime_seconds,
    }


def collect_cpu():
    cpuinfo = _read_file("/proc/cpuinfo")
    model = "unknown"
    m = re.search(r"^model name\s*:\s*(.+)$", cpuinfo, re.MULTILINE)
    if m:
        model = m.group(1).strip()

    rc, out, err = _run(["nproc"])
    try:
        cores = int(out.strip())
    except ValueError:
        cores = cpuinfo.count("processor\t:")  # fallback: count entries

    loadavg_raw = _read_file("/proc/loadavg")
    load_1m = load_5m = load_15m = None
    if loadavg_raw:
        fields = loadavg_raw.split()
        if len(fields) >= 3:
            try:
                load_1m, load_5m, load_15m = float(fields[0]), float(fields[1]), float(fields[2])
            except ValueError:
                pass

    return {"model": model, "cores": cores, "load_1m": load_1m, "load_5m": load_5m, "load_15m": load_15m}


def collect_memory():
    rc, out, err = _run(["free", "-b"])
    total = used = free = available = None
    for line in out.splitlines():
        if line.startswith("Mem:"):
            fields = line.split()
            try:
                total, used, free = int(fields[1]), int(fields[2]), int(fields[3])
                if len(fields) >= 7:
                    available = int(fields[6])
            except (ValueError, IndexError):
                pass
            break

    def gb(n):
        return round(n / (1024 ** 3), 2) if n is not None else None

    return {
        "total_bytes": total, "used_bytes": used, "free_bytes": free, "available_bytes": available,
        "total_gb": gb(total), "used_gb": gb(used), "available_gb": gb(available),
    }


_SKIP_FS_TYPES = {"tmpfs", "devtmpfs", "overlay", "squashfs", "proc", "sysfs",
                   "cgroup", "cgroup2", "devpts", "mqueue", "efivarfs"}


def collect_disk():
    rc, out, err = _run(["df", "-B1", "--output=source,fstype,target,size,used,avail,pcent"])
    filesystems = []
    lines = out.strip().splitlines()
    for line in lines[1:]:  # skip header
        fields = line.split(None, 6)
        if len(fields) < 7:
            continue
        source, fstype, target, size, used, avail, pcent = fields
        if fstype in _SKIP_FS_TYPES:
            continue
        try:
            size_i, used_i, avail_i = int(size), int(used), int(avail)
        except ValueError:
            continue
        filesystems.append({
            "source": source, "fstype": fstype, "target": target,
            "size_gb": round(size_i / (1024 ** 3), 2),
            "used_gb": round(used_i / (1024 ** 3), 2),
            "avail_gb": round(avail_i / (1024 ** 3), 2),
            "used_percent": pcent.rstrip("%"),
        })
    return {"filesystems": filesystems}


def collect_ollama():
    """`ollama list`'s SIZE column is itself two tokens ("4.9 GB") —
    splitting on plain whitespace grabs only the number and silently
    drops the unit. Real column boundaries in this output are 2+ spaces;
    a single space stays WITHIN a column (e.g. between "4.9" and "GB").
    Splitting on \\s{2,} instead of any whitespace is what keeps that
    unit attached. Confirmed against real Ollama output on Bucky, which
    is exactly what caught this the first time — the earlier version's
    own test used realistic-looking text but never asserted the size
    value itself, so it passed while quietly losing the unit."""
    rc, out, err = _run(["ollama", "list"])
    if rc == 127:
        return {"installed": False, "models": []}
    if rc != 0:
        return {"installed": True, "models": [], "error": err.strip()}

    models = []
    lines = out.strip().splitlines()
    for line in lines[1:]:  # skip header (NAME  ID  SIZE  MODIFIED)
        if not line.strip():
            continue
        fields = re.split(r"\s{2,}", line.strip())
        if len(fields) >= 3:
            models.append({"name": fields[0], "id": fields[1], "size": fields[2]})
    return {"installed": True, "models": models}


def collect_docker():
    rc, out, err = _run(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"])
    if rc == 127:
        return {"installed": False, "containers": [], "images": []}

    containers = []
    for line in out.strip().splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) >= 3:
            containers.append({"name": fields[0], "image": fields[1], "status": fields[2]})

    rc2, out2, err2 = _run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}"])
    images = []
    for line in out2.strip().splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) >= 2:
            images.append({"repo_tag": fields[0], "size": fields[1]})

    return {"installed": True, "containers": containers, "images": images}


def collect_dev_tools():
    tools = {}
    for name, cmd in DEV_TOOLS.items():
        rc, out, err = _run(cmd)
        if rc == 127:
            tools[name] = {"installed": False, "version": None}
        elif rc == 0:
            version_line = (out or err).strip().splitlines()[0] if (out or err).strip() else ""
            tools[name] = {"installed": True, "version": version_line}
        else:
            tools[name] = {"installed": True, "version": None, "error": err.strip()[:200]}
    return tools


COLLECTORS = {
    "host": collect_host,
    "cpu": collect_cpu,
    "memory": collect_memory,
    "disk": collect_disk,
    "ollama": collect_ollama,
    "docker": collect_docker,
    "dev_tools": collect_dev_tools,
}


def op_get(name: str, force: bool = False):
    if name not in COLLECTORS:
        raise IntrospectionError(f"no collector named {name!r} — known: {sorted(COLLECTORS.keys())}")
    if force:
        _cache.pop(name, None)
    return _cached(name, COLLECTORS[name])


def op_summary(force: bool = False):
    if force:
        clear_cache()
    return {name: _cached(name, fn) for name, fn in COLLECTORS.items()}


def op_refresh():
    clear_cache()
    return op_summary()
