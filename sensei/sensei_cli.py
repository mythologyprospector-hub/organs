#!/usr/bin/env python3
"""
sensei — command-line toggle for Digital Sensei.

    sensei ready     switch to ready mode (nudges surface)
    sensei mute      switch to watching mode (observes quietly, default)
    sensei status    show current mode + recent nudge count

Talks to the sensei organ over HTTP, same as the TUI keybind and any
future hotkey daemon do — this file is a thin client, not a second
copy of the toggle logic.
"""
import json
import sys
import urllib.error
import urllib.request

BASE_URL = "http://localhost:8012"


def _post(path, body):
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path):
    req = urllib.request.Request(f"{BASE_URL}{path}")
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("ready", "mute", "status"):
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    try:
        if cmd == "ready":
            result = _post("/sensei/mode", {"mode": "ready"})
            print(f"sensei: ready — nudges will surface (since {result['mode_changed_ts']})")
        elif cmd == "mute":
            result = _post("/sensei/mode", {"mode": "watching"})
            print(f"sensei: watching — quiet (since {result['mode_changed_ts']})")
        elif cmd == "status":
            result = _get("/sensei/status")
            print(f"mode: {result['mode']}")
            print(f"nudges recorded: {result['nudge_count']}")
            if result.get("last_nudge_ts"):
                print(f"last nudge: {result['last_nudge_ts']}")
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"sensei: could not reach organ at {BASE_URL} — is it running? ({e})")
        sys.exit(1)


if __name__ == "__main__":
    main()
