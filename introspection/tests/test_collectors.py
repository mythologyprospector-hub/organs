def test_collect_host_parses_real_format(ic, fake_runner, fake_files):
    fake_runner.responses[("uname", "-srm")] = (0, "Linux 6.8.0-generic x86_64\n", "")
    fake_runner.responses[("hostname",)] = (0, "mythos1\n", "")
    fake_files["/etc/os-release"] = 'NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\nVERSION_ID="24.04"\n'
    fake_files["/proc/uptime"] = "123456.78 987654.32\n"

    result = ic.collect_host()
    assert result["hostname"] == "mythos1"
    assert result["kernel"] == "Linux 6.8.0-generic"
    assert result["arch"] == "x86_64"
    assert result["os"] == "Ubuntu 24.04.1 LTS"
    assert result["uptime_seconds"] == 123456.78


def test_collect_host_survives_missing_os_release(ic, fake_runner, fake_files):
    fake_runner.responses[("uname", "-srm")] = (0, "Linux 6.8.0 x86_64\n", "")
    fake_runner.responses[("hostname",)] = (0, "host\n", "")
    # fake_files left empty — /etc/os-release missing entirely
    result = ic.collect_host()
    assert result["os"] == "unknown"


def test_collect_cpu_parses_real_format(ic, fake_runner, fake_files):
    fake_files["/proc/cpuinfo"] = (
        "processor\t: 0\nmodel name\t: AMD Ryzen 9 5900X 12-Core Processor\ncache size\t: 512 KB\n"
        "processor\t: 1\nmodel name\t: AMD Ryzen 9 5900X 12-Core Processor\ncache size\t: 512 KB\n"
    )
    fake_runner.responses[("nproc",)] = (0, "24\n", "")
    fake_files["/proc/loadavg"] = "1.23 0.98 0.75 2/456 12345\n"

    result = ic.collect_cpu()
    assert result["model"] == "AMD Ryzen 9 5900X 12-Core Processor"
    assert result["cores"] == 24
    assert result["load_1m"] == 1.23
    assert result["load_5m"] == 0.98
    assert result["load_15m"] == 0.75


def test_collect_memory_parses_real_free_output(ic, fake_runner):
    # realistic `free -b` output
    fake_runner.responses[("free", "-b")] = (0, (
        "               total        used        free      shared  buff/cache   available\n"
        "Mem:     33654657024  8589934592  4294967296   536870912 20769755136 24696061952\n"
        "Swap:     2147483648           0  2147483648\n"
    ), "")
    result = ic.collect_memory()
    assert result["total_bytes"] == 33654657024
    assert result["used_bytes"] == 8589934592
    assert result["available_bytes"] == 24696061952
    assert result["total_gb"] == round(33654657024 / (1024**3), 2)


def test_collect_disk_skips_pseudo_filesystems(ic, fake_runner):
    fake_runner.responses[("df", "-B1", "--output=source,fstype,target,size,used,avail,pcent")] = (0, (
        "Filesystem                        Type       Mounted on            1B-blocks              Used         Avail Use%\n"
        "/dev/nvme0n1p2                    ext4       /                1000204886016     450102214656  498892222464  48%\n"
        "tmpfs                             tmpfs      /dev/shm           16827328512                0   16827328512   0%\n"
        "/dev/nvme1n1                      ext4       /srv              2000398934016    1200239360819  748954980352  62%\n"
        "overlay                           overlay    /var/lib/docker/overlay2/abc   1000204886016  450102214656  498892222464  48%\n"
    ), "")
    result = ic.collect_disk()
    targets = [fs["target"] for fs in result["filesystems"]]
    assert "/" in targets
    assert "/srv" in targets
    assert "/dev/shm" not in targets  # tmpfs, skipped
    assert not any("docker/overlay2" in t for t in targets)  # overlay, skipped
    root = [fs for fs in result["filesystems"] if fs["target"] == "/"][0]
    assert root["used_percent"] == "48"


def test_collect_ollama_not_installed(ic, fake_runner):
    fake_runner.responses[("ollama", "list")] = (127, "", "command not found")
    result = ic.collect_ollama()
    assert result["installed"] is False
    assert result["models"] == []


def test_collect_ollama_parses_real_list_output(ic, fake_runner):
    fake_runner.responses[("ollama", "list")] = (0, (
        "NAME                     ID              SIZE      MODIFIED\n"
        "llama3.1:8b              a1b2c3d4e5f6    4.9 GB    2 weeks ago\n"
        "nomic-embed-text:latest  f6e5d4c3b2a1    274 MB    3 weeks ago\n"
    ), "")
    result = ic.collect_ollama()
    assert result["installed"] is True
    assert len(result["models"]) == 2
    names = [m["name"] for m in result["models"]]
    assert "llama3.1:8b" in names
    assert "nomic-embed-text:latest" in names

    llama = [m for m in result["models"] if m["name"] == "llama3.1:8b"][0]
    # regression test: size must keep its unit, not just the number —
    # a real live run against Bucky caught this dropping the "GB"/"MB"
    assert llama["size"] == "4.9 GB"
    embed = [m for m in result["models"] if m["name"] == "nomic-embed-text:latest"][0]
    assert embed["size"] == "274 MB"


def test_collect_ollama_size_units_from_actual_bucky_output(ic, fake_runner):
    """The exact bug that shipped: a real `ollama list` run on Bucky
    produced sizes like "4.9" and "274" with the unit silently dropped.
    This is that real output, verbatim in shape, as the regression test."""
    fake_runner.responses[("ollama", "list")] = (0, (
        "NAME                                                         ID              SIZE      MODIFIED     \n"
        "teresa-oracle:latest                                         2e7f6eadd5ee    4.9 GB    2 weeks ago \n"
        "llama3.1:8b                                                  46e0c10c039e    4.9 GB    3 weeks ago \n"
        "nomic-embed-text:latest                                      0a109f422b47    274 MB    3 weeks ago \n"
        "richardyoung/qwen2.5-coder-14b-instruct-abliterated:latest  fb89eb977c11    9.0 GB    2 months ago\n"
    ), "")
    result = ic.collect_ollama()
    sizes = {m["name"]: m["size"] for m in result["models"]}
    assert sizes["teresa-oracle:latest"] == "4.9 GB"
    assert sizes["nomic-embed-text:latest"] == "274 MB"
    assert "GB" in sizes["richardyoung/qwen2.5-coder-14b-instruct-abliterated:latest"]


def test_efivarfs_filtered_as_noise(ic, fake_runner):
    """Real, observed on Bucky: efivarfs reports 0.0 GB across the board
    but a nonzero used_percent — meaningless clutter, same category as
    tmpfs, filtered for the same reason."""
    fake_runner.responses[("df", "-B1", "--output=source,fstype,target,size,used,avail,pcent")] = (0, (
        "Filesystem   Type       Mounted on                1B-blocks   Used   Avail Use%\n"
        "efivarfs     efivarfs   /sys/firmware/efi/efivars         0      0       0  81%\n"
        "/dev/sda1    ext4       /                        900160000000  324480000000  529890000000  38%\n"
    ), "")
    result = ic.collect_disk()
    targets = [fs["target"] for fs in result["filesystems"]]
    assert "/sys/firmware/efi/efivars" not in targets
    assert "/" in targets


def test_collect_docker_not_installed(ic, fake_runner):
    fake_runner.responses[("docker", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}")] = (
        127, "", "command not found"
    )
    result = ic.collect_docker()
    assert result["installed"] is False


def test_collect_docker_parses_real_output(ic, fake_runner):
    fake_runner.responses[("docker", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}")] = (0, (
        "open-webui\tghcr.io/open-webui/open-webui:main\tUp 21 hours (healthy)\n"
        "oi-sandbox\toi-sandbox:latest\tExited (1) 24 seconds ago\n"
    ), "")
    fake_runner.responses[("docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}")] = (0, (
        "oi-sandbox:latest\t913MB\n"
        "ghcr.io/open-webui/open-webui:main\t5.09GB\n"
    ), "")
    result = ic.collect_docker()
    assert result["installed"] is True
    names = [c["name"] for c in result["containers"]]
    assert "open-webui" in names
    assert "oi-sandbox" in names
    assert len(result["images"]) == 2


def test_collect_dev_tools_reports_installed_and_missing(ic, fake_runner):
    fake_runner.responses[("git", "--version")] = (0, "git version 2.43.0\n", "")
    fake_runner.responses[("python3", "--version")] = (0, "Python 3.13.1\n", "")
    fake_runner.responses[("rustc", "--version")] = (127, "", "command not found")
    # everything else falls to fake_runner.default -> 127 not found

    result = ic.collect_dev_tools()
    assert result["git"]["installed"] is True
    assert "2.43.0" in result["git"]["version"]
    assert result["python3"]["installed"] is True
    assert result["rustc"]["installed"] is False


def test_unknown_collector_errors(ic):
    try:
        ic.op_get("nonexistent")
        assert False
    except ic.IntrospectionError:
        pass


def test_summary_includes_every_collector(ic, fake_runner):
    fake_runner.default = (127, "", "not found")  # everything reports "not found" cleanly
    result = ic.op_summary()
    assert set(result.keys()) == {"host", "cpu", "memory", "disk", "ollama", "docker", "dev_tools"}


def test_results_are_cached_within_ttl(ic, fake_runner):
    fake_runner.responses[("hostname",)] = (0, "host1\n", "")
    fake_runner.responses[("uname", "-srm")] = (0, "Linux 6.8.0 x86_64\n", "")

    ic.op_get("host")
    calls_after_first = len(fake_runner.calls)
    ic.op_get("host")  # should hit cache, not call _run again
    calls_after_second = len(fake_runner.calls)

    assert calls_after_second == calls_after_first


def test_force_bypasses_cache(ic, fake_runner):
    fake_runner.responses[("hostname",)] = (0, "host1\n", "")
    fake_runner.responses[("uname", "-srm")] = (0, "Linux 6.8.0 x86_64\n", "")

    ic.op_get("host")
    calls_after_first = len(fake_runner.calls)
    ic.op_get("host", force=True)  # bypasses cache, calls _run again
    calls_after_second = len(fake_runner.calls)

    assert calls_after_second > calls_after_first


def test_timeout_reported_cleanly_not_raised(ic, monkeypatch):
    import subprocess

    def _raise(*a, **k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=8)
    monkeypatch.setattr(ic.subprocess, "run", _raise)

    rc, out, err = ic._run(["slow_command"])
    assert rc == -1
    assert "timed out" in err


def test_command_not_found_reported_cleanly_not_raised(ic, monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError()
    monkeypatch.setattr(ic.subprocess, "run", _raise)

    rc, out, err = ic._run(["nonexistent_binary"])
    assert rc == 127


def test_run_reports_permission_denied_without_raising(ic, monkeypatch):
    """A binary that exists on disk but isn't executable raises
    PermissionError, not FileNotFoundError. _run() must never raise —
    that contract holds for this failure mode too, not just 'not
    found' and 'timed out'. Uses the real POSIX convention (126, not
    127) so callers can tell 'not installed' apart from 'installed but
    not executable' — see the collector-level tests below for why that
    distinction matters here specifically."""
    def _raise(*a, **k):
        raise PermissionError()
    monkeypatch.setattr(ic.subprocess, "run", _raise)
    rc, out, err = ic._run(["some_unexecutable_binary"])
    assert rc == 126
    assert "permission denied" in err


def test_collect_ollama_not_executable_is_reported_as_installed(ic, fake_runner):
    """Regression: _run() briefly collapsed 'not executable' into the
    same rc (127) as 'not installed', which made collect_ollama report
    a genuinely-installed-but-unexecutable ollama as not installed at
    all — exactly the kind of wrong fact this organ exists to avoid."""
    fake_runner.responses[("ollama", "list")] = (126, "", "command not executable (permission denied)")
    result = ic.collect_ollama()
    assert result["installed"] is True
    assert result["models"] == []
    assert "error" in result


def test_collect_docker_not_executable_is_reported_as_installed(ic, fake_runner):
    fake_runner.responses[("docker", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}")] = (
        126, "", "command not executable (permission denied)"
    )
    result = ic.collect_docker()
    assert result["installed"] is True


def test_collect_dev_tools_not_executable_is_reported_as_installed(ic, fake_runner):
    fake_runner.responses[("git", "--version")] = (126, "", "command not executable (permission denied)")
    result = ic.collect_dev_tools()
    assert result["git"]["installed"] is True
    assert "error" in result["git"]

