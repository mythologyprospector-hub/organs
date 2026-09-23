"""
conftest.py (repo root) — a deliberate tripwire, not a normal fixture
file.

Every organ (and the tui/ tool) imports its own top-level modules by
BARE NAME inside its own tests/conftest.py — `import main`, `import
memory_core`, `import forge_core`, etc. This only works safely because
run_all_tests.sh runs each one in its OWN subprocess: each interpreter
only ever has ONE organ's `main` entry in sys.modules for the lifetime
of that process.

Running pytest across more than one organ in a SINGLE process (e.g.
bare `pytest` from this root, or `pytest memory forge`) breaks that
assumption — SILENTLY, not as a clean crash. The first organ collected
wins sys.modules['main']; every subsequent organ's `import main` inside
ITS OWN conftest.py just returns that FIRST organ's already-imported
module instead of its own. The existing `importlib.reload(main)` calls
in several conftest.py files don't protect against this either —
reload() re-executes the module using its ORIGINAL file location, not
whichever organ is currently trying to import it.

Reproduced and confirmed live: `pytest memory/tests/test_api.py
forge/tests/test_api.py` in one process produces ten of memory's tests
failing with 404s and KeyErrors — not because anything is broken, but
because memory's fixtures ended up running against forge's app. That's
worse than a crash: it looks like a real, confusing bug and sends
whoever hits it chasing the wrong thing. This file exists so that
never happens quietly again — it fails fast and loud, before a single
test executes, with a message that explains exactly why and how to run
it correctly instead.

Correct usage:
    ./run_all_tests.sh                      (every organ + tui, isolated)
    cd <organ-or-tool> && pytest tests/     (just that one)
"""
import pytest


def pytest_collection_modifyitems(session, config, items):
    if not items:
        return

    rootdir = str(config.rootdir)
    top_level_dirs = set()
    for item in items:
        path = getattr(item, "path", None)
        path_str = str(path) if path is not None else str(getattr(item, "fspath", ""))
        rel = path_str[len(rootdir) + 1:] if path_str.startswith(rootdir) else path_str
        top_level = rel.split("/")[0] if "/" in rel else rel
        top_level_dirs.add(top_level)

    if len(top_level_dirs) > 1:
        pytest.exit(
            "\n"
            "REFUSING TO RUN: this collection spans more than one organ/tool's\n"
            f"tests in a single process: {sorted(top_level_dirs)}\n\n"
            "Every organ (and tui/) imports its own top-level modules by bare\n"
            "name (`import main`, `import forge_core`, etc.) inside its own\n"
            "tests/conftest.py. Running more than one in the SAME interpreter\n"
            "collides on sys.modules['main'] — silently, not as a clean crash:\n"
            "every organ collected after the first runs its tests against the\n"
            "FIRST organ's already-imported main.py instead of its own. This\n"
            "has been reproduced (see this file's own docstring) — it is not a\n"
            "theoretical concern.\n\n"
            "Correct usage:\n"
            "  ./run_all_tests.sh                      (all organs + tui, isolated)\n"
            "  cd <organ-or-tool> && pytest tests/     (just that one)\n",
            returncode=1,
        )
