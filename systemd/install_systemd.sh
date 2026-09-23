#!/bin/bash
# install_systemd.sh — installs the eleven current Renaissance Organs
# runtime services as user-scope systemd units.
#
# Run this after install.sh has successfully updated /srv/organs.
#
# It removes the retired Sensei service, reloads systemd, enables the current
# eleven services, restarts them in dependency-sensitive order, and verifies
# Registry discovery.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"

echo "== Installing Renaissance Organs systemd units =="
mkdir -p "$UNIT_DIR"

for unit in organs-registry.service organs-memory.service organs-communications.service organs-orchestrator.service organs-reflection.service organs-introspection.service organs-sandbox.service organs-critic.service organs-executive.service organs-io-interface.service organs-telemetry.service; do
    cp "$SRC_DIR/$unit" "$UNIT_DIR/"
done

echo "-> copied current eleven units to $UNIT_DIR"

echo
echo "== Removing retired Sensei service =="
systemctl --user disable --now organs-sensei.service 2>/dev/null || true
rm -f "$UNIT_DIR/organs-sensei.service"

echo
echo "== Enabling linger for $USER =="
sudo loginctl enable-linger "$USER"

echo
echo "== Reloading systemd and enabling current services =="
systemctl --user daemon-reload
for service in organs-registry.service organs-memory.service organs-communications.service organs-orchestrator.service organs-reflection.service organs-introspection.service organs-sandbox.service organs-critic.service organs-executive.service organs-io-interface.service organs-telemetry.service; do
    systemctl --user enable "$service"
done

echo
echo "== Restarting current services =="
systemctl --user restart organs-registry.service
sleep 2
systemctl --user restart organs-memory.service
systemctl --user restart organs-communications.service
systemctl --user restart organs-orchestrator.service
systemctl --user restart organs-reflection.service
systemctl --user restart organs-introspection.service
systemctl --user restart organs-sandbox.service
systemctl --user restart organs-critic.service
sleep 1
systemctl --user restart organs-executive.service
sleep 1
systemctl --user restart organs-io-interface.service
sleep 1
systemctl --user restart organs-telemetry.service
sleep 2

echo
echo "== Status =="
for service in organs-registry organs-memory organs-communications organs-orchestrator organs-reflection organs-introspection organs-sandbox organs-critic organs-executive organs-io-interface organs-telemetry; do
    systemctl --user status "$service.service" --no-pager -l | head -8
    echo
done

echo "== Verifying Registry discovery =="
sleep 2
curl -s localhost:8000/registry/organs | python3 -m json.tool || {
    echo "(registry not answering yet — inspect: journalctl --user -u organs-registry.service -f)"
    exit 1
}

echo
echo "== Done =="
echo
echo "Reflection is running but OFF by default:"
echo "  curl localhost:8004/reflection/status"
echo
echo "Useful runtime checks:"
echo "  curl localhost:8005/introspect/summary"
echo "  curl localhost:8006/sandbox/doctor"
echo "  curl localhost:8007/critic/rules"
echo "  curl localhost:8011/telemetry/stats"
echo "  curl localhost:8009/io/catalog"
echo
echo "Useful service commands:"
echo "  systemctl --user status organs-registry organs-memory organs-communications organs-orchestrator organs-reflection organs-introspection organs-sandbox organs-critic organs-executive organs-io-interface organs-telemetry"
echo "  systemctl --user restart organs-memory"
echo "  journalctl --user -u organs-memory.service -f"
echo "  journalctl --user -u organs-registry.service -f"
