#!/bin/bash
# install.sh — installs the current Renaissance Organs runtime at /srv/organs.
#
# Run this FROM THE REPOSITORY CHECKOUT (or extracted source tree).
# It figures out its own location, so the source path does not matter.
#
# Runtime data under /srv/organs/*/data is intentionally preserved by this
# overlay model. Retired components are removed explicitly and narrowly.
#
# This script does not install or modify systemd units.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST=/srv/organs

echo "== Installing Renaissance Organs runtime =="
echo "   from: $SRC_DIR"
echo "   to:   $DEST"
echo

if [ ! -d "$DEST" ]; then
    echo "-> Creating $DEST (needs sudo)"
    sudo mkdir -p "$DEST"
else
    echo "-> $DEST already exists; preserving existing runtime data"
fi

echo "-> Copying current runtime components"
for organ in shared registry memory communications orchestrator reflection introspection sandbox critic executive io_interface telemetry tui; do
    sudo cp -r "$SRC_DIR/$organ" "$DEST/"
done

echo "-> Removing retired Sensei runtime tree, if present"
sudo rm -rf "$DEST/sensei"

echo "-> Copying current canonical project docs and test tooling"
for f in README.md CANON.md ARCHITECTURE.md CONTRIBUTING.md DEV_NOTES.md SECURITY.md MAXIMIZATION_PASS.md REPO_MIGRATION.md run_all_tests.sh pytest.ini requirements.txt; do
    if [ -f "$SRC_DIR/$f" ]; then
        sudo cp "$SRC_DIR/$f" "$DEST/"
    else
        echo "   (skipping $f — not present in $SRC_DIR)"
    fi
done
sudo chmod +x "$DEST/run_all_tests.sh" 2>/dev/null || true

echo "-> Handing ownership to $USER"
sudo chown -R "$USER":"$USER" "$DEST"

echo "-> Creating required organ data directories"
mkdir -p "$DEST/registry/data" "$DEST/memory/data" "$DEST/communications/data"

echo "-> Installing Python dependencies for $USER"
pip install --break-system-packages -r "$SRC_DIR/requirements.txt"

echo
echo "-> Running the full test suite"
(cd "$DEST" && ./run_all_tests.sh)

echo
echo "== Install complete =="
echo "The installed runtime is on disk at $DEST."
echo "Existing runtime data was preserved."
echo "Retired Sensei runtime files were removed."
echo

RUNNING_ORGANS=()
for organ_service in registry memory communications orchestrator reflection introspection sandbox critic executive io-interface telemetry; do
    if systemctl --user is-active --quiet "organs-${organ_service}.service" 2>/dev/null; then
        RUNNING_ORGANS+=("organs-${organ_service}")
    fi
done
if [ ${#RUNNING_ORGANS[@]} -gt 0 ]; then
    echo "!! Running Organs services detected; restart them to load the new code:"
    printf '   %s\n' "  systemctl --user restart ${RUNNING_ORGANS[*]}"
else
    echo "(no current Organs systemd services detected)"
fi

echo
echo "Installed layout:"
find "$DEST" -maxdepth 2 -type d | sort
echo
echo "Full test suite:"
echo "  cd $DEST && ./run_all_tests.sh"
echo
echo "Systemd installation is separate:"
echo "  cd $SRC_DIR/systemd && ./install_systemd.sh"
