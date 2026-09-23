#!/bin/bash
# install_systemd.sh — wires all eleven organs in as user-scope systemd
# services, same pattern akasha-oracle already used on this machine.
#
# Run this FROM WHEREVER YOU EXTRACTED THE TARBALL, after /srv/organs
# already has every organ in place (i.e. after install.sh).
#
# What it does:
#   1. Copies the .service files to ~/.config/systemd/user/
#   2. Enables "linger" for your user — WITHOUT this, user-scope services
#      stop the moment you log out, and won't come back on reboot until
#      you log in again. With it, they behave like real system services.
#   3. daemon-reload, enable both units, start registry then memory
#   4. Verifies both are up and registered with each other

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"

echo "== Installing systemd units =="
mkdir -p "$UNIT_DIR"
cp "$SRC_DIR/organs-registry.service" "$UNIT_DIR/"
cp "$SRC_DIR/organs-memory.service" "$UNIT_DIR/"
cp "$SRC_DIR/organs-communications.service" "$UNIT_DIR/"
cp "$SRC_DIR/organs-orchestrator.service" "$UNIT_DIR/"
cp "$SRC_DIR/organs-reflection.service" "$UNIT_DIR/"
cp "$SRC_DIR/organs-introspection.service" "$UNIT_DIR/"
cp "$SRC_DIR/organs-sandbox.service" "$UNIT_DIR/"
cp "$SRC_DIR/organs-critic.service" "$UNIT_DIR/"
cp "$SRC_DIR/organs-executive.service" "$UNIT_DIR/"
cp "$SRC_DIR/organs-io-interface.service" "$UNIT_DIR/"
cp "$SRC_DIR/organs-forge.service" "$UNIT_DIR/"
cp "$SRC_DIR/organs-telemetry.service" "$UNIT_DIR/"
echo "-> copied to $UNIT_DIR"

echo
echo "== Enabling linger for $USER =="
echo "   (without this, these services die when you log out — needs sudo once)"
sudo loginctl enable-linger "$USER"

echo
echo "== Reloading systemd, enabling units =="
systemctl --user daemon-reload
systemctl --user enable organs-registry.service
systemctl --user enable organs-memory.service
systemctl --user enable organs-communications.service
systemctl --user enable organs-orchestrator.service
systemctl --user enable organs-reflection.service
systemctl --user enable organs-introspection.service
systemctl --user enable organs-sandbox.service
systemctl --user enable organs-critic.service
systemctl --user enable organs-executive.service
systemctl --user enable organs-io-interface.service
systemctl --user enable organs-forge.service
systemctl --user enable organs-telemetry.service

echo
echo "== Starting registry first, then the rest (Critic before Executive, Executive before I/O Interface) =="
systemctl --user start organs-registry.service
sleep 2
systemctl --user start organs-memory.service
systemctl --user start organs-communications.service
systemctl --user start organs-orchestrator.service
systemctl --user start organs-reflection.service
systemctl --user start organs-introspection.service
systemctl --user start organs-sandbox.service
systemctl --user start organs-critic.service
sleep 1
systemctl --user start organs-executive.service
sleep 1
systemctl --user start organs-io-interface.service
sleep 1
systemctl --user start organs-forge.service
sleep 1
systemctl --user start organs-telemetry.service
sleep 2

echo
echo "== Status =="
systemctl --user status organs-registry.service --no-pager -l | head -8
echo
systemctl --user status organs-memory.service --no-pager -l | head -8
echo
systemctl --user status organs-communications.service --no-pager -l | head -8
echo
systemctl --user status organs-orchestrator.service --no-pager -l | head -8
echo
systemctl --user status organs-reflection.service --no-pager -l | head -8
echo
systemctl --user status organs-introspection.service --no-pager -l | head -8
echo
systemctl --user status organs-sandbox.service --no-pager -l | head -8
echo
systemctl --user status organs-critic.service --no-pager -l | head -8
echo
systemctl --user status organs-executive.service --no-pager -l | head -8
echo
systemctl --user status organs-io-interface.service --no-pager -l | head -8
echo
systemctl --user status organs-forge.service --no-pager -l | head -8
echo
systemctl --user status organs-telemetry.service --no-pager -l | head -8

echo
echo "== Verifying they actually found each other =="
sleep 2
curl -s localhost:8000/registry/organs | python3 -m json.tool || echo "(registry not answering yet — check: journalctl --user -u organs-registry -f)"

echo
echo "== Done =="
echo "Reflection is running but OFF — confirm with:"
echo "  curl localhost:8004/reflection/status"
echo "Enable it (it'll start muttering into Memory on its configured interval):"
echo "  curl -X POST localhost:8004/reflection/enable"
echo
echo "See what Introspection knows about this machine:"
echo "  curl localhost:8005/introspect/summary"
echo
echo "Confirm Sandbox can actually see Docker:"
echo "  curl localhost:8006/sandbox/doctor"
echo
echo "See Critic's actual rule set:"
echo "  curl localhost:8007/critic/rules"
echo
echo "Create a test goal in Executive:"
echo "  curl -X POST localhost:8008/executive/goals -H 'content-type: application/json' -d '{\"description\":\"test\"}'"
echo
echo "Try the real front door — natural language in, right organ out:"
echo "  curl -X POST localhost:8009/io/handle -H 'content-type: application/json' -d '{\"text\":\"memory stats\"}'"
echo "  curl -X POST localhost:8009/io/handle -H 'content-type: application/json' -d '{\"text\":\"restart ollama\"}'"
echo "See the whole catalog it understands:"
echo "  curl localhost:8009/io/catalog"
echo
echo "Forge generates code via a REAL Ollama call — no sim, no stub. Check"
echo "it can actually reach Ollama with:"
echo "  curl localhost:8010/health"
echo "Try it (this makes a real generation call, may take a few seconds):"
echo "  curl -X POST localhost:8010/forge/build -H 'content-type: application/json' \"
echo "    -d '{\"spec\":\"a function that returns the sum of two numbers\",\"language\":\"python\",\"filename\":\"solution.py\"}'"
echo
echo "Telemetry is the observation layer — see what it knows so far:"
echo "  curl localhost:8011/telemetry/stats"
echo "  curl localhost:8011/telemetry/recent"
echo "Nothing calls it yet — instrumenting the other organs to emit events"
echo "is the next real step, not done automatically by this script."
echo
echo "Useful commands going forward:"
echo "  systemctl --user status organs-memory organs-communications organs-orchestrator organs-reflection organs-introspection organs-sandbox organs-critic organs-executive organs-io-interface organs-forge organs-telemetry"
echo "  systemctl --user restart organs-memory"
echo "  journalctl --user -u organs-memory -f      # live logs"
echo "  journalctl --user -u organs-communications -f"
echo "  journalctl --user -u organs-orchestrator -f"
echo "  journalctl --user -u organs-reflection -f"
echo "  journalctl --user -u organs-introspection -f"
echo "  journalctl --user -u organs-sandbox -f"
echo "  journalctl --user -u organs-critic -f"
echo "  journalctl --user -u organs-executive -f"
echo "  journalctl --user -u organs-io-interface -f"
echo "  journalctl --user -u organs-forge -f"
echo "  journalctl --user -u organs-telemetry -f"
echo "  journalctl --user -u organs-registry -f"
echo
echo "Orchestrator's services.json was created with defaults for ollama and"
echo "open-webui. Check it points at the right OI container name:"
echo "  cat /srv/organs/orchestrator/services.json"
