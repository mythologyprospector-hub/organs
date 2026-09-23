#!/bin/bash
# install.sh — puts the organ skeleton in place at /srv/organs.
#
# Run this FROM WHEREVER YOU EXTRACTED THE TARBALL (e.g. ~/Downloads/organs).
# It figures out its own location, so it doesn't matter what that path is.
#
# What it does:
#   1. sudo mkdir /srv/organs (if it doesn't exist)
#   2. copies every organ directory into it
#   3. copies the project docs (README, CANON, CONTRIBUTING, DEV_NOTES,
#      SECURITY) and the test-runner/config files to the same place —
#      an installed /srv/organs with code but no documentation isn't
#      actually a complete install
#   4. chowns it to YOU, not root — so adding organs later never needs sudo
#   5. installs fastapi/uvicorn for your user
#   6. creates each organ's data/ dir
#   7. runs the full test suite as a sanity check — safe to do even when
#      this machine already has the real organs running live (each
#      organ's tests point ORGAN_REGISTRY_URL at a dead address before
#      touching anything, so a fresh/updated install can never register
#      test noise into a Registry that's actually in production)
#
# It does NOT set up systemd yet — that's deliberately deferred until the
# organ set is actually settled. Run commands are printed at the end.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST=/srv/organs

echo "== Installing organ skeleton =="
echo "   from: $SRC_DIR"
echo "   to:   $DEST"
echo

if [ ! -d "$DEST" ]; then
    echo "-> Creating $DEST (needs sudo)"
    sudo mkdir -p "$DEST"
else
    echo "-> $DEST already exists, adding into it"
fi

echo "-> Copying shared/, registry/, memory/, communications/, orchestrator/, reflection/, introspection/, sandbox/, critic/, executive/, io_interface/, forge/, telemetry/, tui/"
sudo cp -r "$SRC_DIR/shared" "$DEST/"
sudo cp -r "$SRC_DIR/registry" "$DEST/"
sudo cp -r "$SRC_DIR/memory" "$DEST/"
sudo cp -r "$SRC_DIR/communications" "$DEST/"
sudo cp -r "$SRC_DIR/orchestrator" "$DEST/"
sudo cp -r "$SRC_DIR/reflection" "$DEST/"
sudo cp -r "$SRC_DIR/introspection" "$DEST/"
sudo cp -r "$SRC_DIR/sandbox" "$DEST/"
sudo cp -r "$SRC_DIR/critic" "$DEST/"
sudo cp -r "$SRC_DIR/executive" "$DEST/"
sudo cp -r "$SRC_DIR/io_interface" "$DEST/"
sudo cp -r "$SRC_DIR/forge" "$DEST/"
sudo cp -r "$SRC_DIR/telemetry" "$DEST/"
sudo cp -r "$SRC_DIR/tui" "$DEST/"  # a tool, not an organ — no port, no systemd unit

echo "-> Copying project docs (README, CANON, CONTRIBUTING, DEV_NOTES, SECURITY) and test tooling"
for f in README.md CANON.md CONTRIBUTING.md DEV_NOTES.md SECURITY.md run_all_tests.sh pytest.ini requirements.txt; do
    if [ -f "$SRC_DIR/$f" ]; then
        sudo cp "$SRC_DIR/$f" "$DEST/"
    else
        echo "   (skipping $f — not present in $SRC_DIR)"
    fi
done
sudo chmod +x "$DEST/run_all_tests.sh" 2>/dev/null || true

echo "-> Handing ownership to $USER (so you don't need sudo to add the next organ)"
sudo chown -R "$USER":"$USER" "$DEST"

echo "-> Creating each organ's data/ directory"
mkdir -p "$DEST/registry/data" "$DEST/memory/data" "$DEST/communications/data"

echo "-> Installing Python dependencies for $USER"
pip install --break-system-packages -r "$SRC_DIR/requirements.txt"

echo
echo "-> Running the test suite (each organ in its own subprocess, isolated"
echo "   from any organs already running live on this machine — including"
echo "   this exact install, if you're updating in place)"
(cd "$DEST" && ./run_all_tests.sh)

echo
echo "== Done =="
echo

# This block exists because of a real, confusing failure mode caught
# live on mythos1: this script updates code on disk, but if any organ
# is ALREADY running as a systemd service, that running process keeps
# executing whatever it loaded into memory when it last started —
# updated files on disk are invisible to it until it's restarted.
# Reinstalling looked like it "didn't work" for a fix that was actually
# sitting correctly on disk the whole time. Detect and say so loudly,
# rather than leaving this as a silent trap on every future update.
RUNNING_ORGANS=()
for organ_service in registry memory communications orchestrator reflection introspection sandbox critic executive io-interface forge telemetry; do
    if systemctl --user is-active --quiet "organs-${organ_service}.service" 2>/dev/null; then
        RUNNING_ORGANS+=("organs-${organ_service}")
    fi
done
if [ ${#RUNNING_ORGANS[@]} -gt 0 ]; then
    echo "!! These organs are ALREADY RUNNING as systemd services — the code"
    echo "   just installed above is on disk now, but each of these processes"
    echo "   is still executing whatever it loaded into memory at its last"
    echo "   start. Restart them to actually pick up anything that changed:"
    echo
    echo "     systemctl --user restart ${RUNNING_ORGANS[*]}"
    echo
fi

echo "Layout now:"
find "$DEST" -maxdepth 2 -type d | sort
echo
echo "Docs installed alongside the code — read them from $DEST directly:"
echo "  $DEST/README.md          what each organ does, right now"
echo "  $DEST/CANON.md            the permanent rules"
echo "  $DEST/CONTRIBUTING.md     how to add the next organ without breaking CANON.md"
echo "  $DEST/DEV_NOTES.md        why specific lines of code look the way they do"
echo "  $DEST/SECURITY.md         the actual, unglamorous security posture"
echo
echo "Test everything at once (each organ in its own subprocess):"
echo "  cd $DEST && ./run_all_tests.sh"
echo
echo "To run it (two terminals — systemd comes once the organ set is settled):"
echo
echo "  cd $DEST/registry       && uvicorn main:app --host 0.0.0.0 --port 8000"
echo "  cd $DEST/memory         && uvicorn main:app --host 0.0.0.0 --port 8001"
echo "  cd $DEST/communications && uvicorn main:app --host 0.0.0.0 --port 8002"
echo "  cd $DEST/orchestrator   && uvicorn main:app --host 0.0.0.0 --port 8003"
echo "  cd $DEST/reflection     && uvicorn main:app --host 0.0.0.0 --port 8004"
echo "  cd $DEST/introspection  && uvicorn main:app --host 0.0.0.0 --port 8005"
echo "  cd $DEST/sandbox        && uvicorn main:app --host 0.0.0.0 --port 8006"
echo "  cd $DEST/critic         && uvicorn main:app --host 0.0.0.0 --port 8007"
echo "  cd $DEST/executive      && uvicorn main:app --host 0.0.0.0 --port 8008"
echo "  cd $DEST/io_interface   && uvicorn main:app --host 0.0.0.0 --port 8009"
echo "  cd $DEST/forge          && uvicorn main:app --host 0.0.0.0 --port 8010"
echo "  cd $DEST/telemetry      && uvicorn main:app --host 0.0.0.0 --port 8011"
echo
echo "Not a service — a tool. Once organs are running, watch them live:"
echo "  cd $DEST/tui            && python3 organs_tui.py"
echo "  (1-7 switch tabs, r refreshes now, q quits. Zero extra dependencies"
echo "   — curses is stdlib. Needs a real terminal, not a pipe/redirect.)"
echo
echo "The real front door — try it once everything's running:"
echo "  curl -X POST localhost:8009/io/handle -H 'content-type: application/json' -d '{\"text\":\"memory stats\"}'"
echo
echo "Executive requires Critic to gate anything safely — start Critic before Executive."
echo
echo "Sandbox runs jobs in Docker — check it can see Docker with:"
echo "  curl localhost:8006/sandbox/doctor"
echo
echo "Forge generates code via a REAL Ollama call — no sim, no stub. Check"
echo "it can actually reach Ollama with:"
echo "  curl localhost:8010/health"
echo "Default model is qwen2.5-coder:7b — override per-request or set FORGE_MODEL."
echo
echo "Telemetry is now wired into the shared organ convention — HTTP requests,"
echo "mutations, and failures are observed automatically. Correlation propagation"
echo "across organ-to-organ calls is the next tightening pass."
echo "Query it directly for now:"
echo "  curl localhost:8011/telemetry/stats"
echo
echo "Reflection is OFF by default even once running — it only starts"
echo "actually thinking once you POST to /reflection/enable."
echo
echo "Orchestrator manages Ollama/Open WebUI/OI-sandbox — edit"
echo "  $DEST/orchestrator/services.json"
echo "once it's created (first run) to fill in the real OI container name."
echo
echo "If you have existing llama_memory data to bring over, point Memory at it"
echo "before starting it:"
echo
echo "  export LLAMA_MEMORY_DIR=/path/to/old/data"
echo
echo "Sanity check once both are running:"
echo "  curl localhost:8000/registry/organs"
echo "  curl localhost:8001/health"
