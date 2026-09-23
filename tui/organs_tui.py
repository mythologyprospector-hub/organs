"""
organs_tui.py — live terminal dashboard for the whole system. Not an
organ: nothing registers this with the Registry, nothing discovers it,
nothing calls it. It's the first thing in this system that only
CONSUMES — every organ built before this one provides a capability
something else calls; this calls all of them and provides nothing
back.

Run it:
    python3 organs_tui.py

Keys: 1-9 and 0 switch tabs (0 = the 10th, Input), PgUp/PgDn also cycle
tabs, r forces an immediate refresh, q quits. The Tests and Executive
tabs are also independently interactive (see their own keybinding
hints on-screen) — approving/rejecting a step there hits the real
Executive endpoints, same as a curl call would, with an explicit
confirming keypress or typed reason required before anything happens.
Auto-refreshes every TUI_REFRESH_SECONDS (default 3s).

Every panel is populated by a real HTTP call in tui_data.py — there is
no synthetic or placeholder data anywhere in this file. An organ that's
down, restarting, or never registered shows as exactly that in its own
panel, in plain language, and never takes any other panel down with
it — same discipline as every organ's own health checks.

Deliberately dumb on purpose: this file only formats and draws what
tui_data.py already fetched. It has no retry logic, no interpretation,
no fallback data of its own to make a panel look more complete than
reality — if tui_data.py says an organ is unreachable, this file's job
is to say that as clearly as possible, not soften it.
"""
import curses
import os
import time

import tui_data as td
from tui_test_runner import TestRunner, available_suites

REFRESH_SECONDS = float(os.environ.get("TUI_REFRESH_SECONDS", "3.0"))

TAB_NAMES = [
    "Overview", "Tests", "Memory", "Sandbox", "Telemetry",
    "Executive", "Orchestrator", "Misc", "Diagnostics", "Input",
]
INPUT_TAB_INDEX = TAB_NAMES.index("Input")
TESTS_TAB_INDEX = TAB_NAMES.index("Tests")
DIAGNOSTICS_TAB_INDEX = TAB_NAMES.index("Diagnostics")
EXECUTIVE_TAB_INDEX = TAB_NAMES.index("Executive")


def _safe_addstr(win, y, x, text, attr=0):
    """curses raises if a string would run past the window's bottom-
    right corner — routine when a terminal is resized smaller than the
    dashboard expects. Never let a resize crash the whole TUI over one
    line of text."""
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x < 0 or x >= max_x:
        return
    try:
        win.addstr(y, x, text[: max_x - x - 1], attr)
    except curses.error:
        pass


def _error_line(win, y, key, value):
    if td.is_error(value):
        _safe_addstr(win, y, 2, f"{key}: {value['error']}", curses.A_DIM)
        return y + 2
    return None


def draw_tab_bar(win, current_tab):
    """Render tabs and controls without letting the control legend collide
    with the tab labels on narrower terminals.  The tab row is always just
    tabs; controls get their own row."""
    max_x = win.getmaxyx()[1]
    x = 0
    for i, name in enumerate(TAB_NAMES):
        label = f" {i + 1}:{name} "
        if x + len(label) >= max_x - 1:
            break
        attr = curses.A_REVERSE if i == current_tab else curses.A_NORMAL
        _safe_addstr(win, 0, x, label, attr)
        x += len(label) + 1

    if current_tab == INPUT_TAB_INDEX:
        hint = "[PgUp/PgDn] tabs   [Enter] send   [Esc] clear"
    elif current_tab == TESTS_TAB_INDEX:
        hint = "[Enter] run suite   [t] full suite   [j/k] select   [r] refresh"
    elif current_tab == DIAGNOSTICS_TAB_INDEX:
        hint = "[d] sweep   [r] refresh   [PgUp/PgDn] tabs"
    else:
        hint = "[1-9][0] tabs   [r] refresh   [d] diagnostics   [PgUp/PgDn] tabs"
    _safe_addstr(win, 1, 2, hint, curses.A_DIM)


def draw_overview(win, data):
    y = 2
    _safe_addstr(win, y, 2, "REGISTRY", curses.A_BOLD)
    y += 1
    registry = data["registry"]
    if td.is_error(registry):
        _safe_addstr(win, y, 2, f"unreachable: {registry['error']}", curses.A_DIM)
        y += 2
    else:
        organs = sorted(registry.get("organs", []), key=lambda o: o.get("name", ""))
        _safe_addstr(win, y, 2, f"{'NAME':<16}{'STATUS':<10}{'HEARTBEAT':<14}{'VERSION':<10}", curses.A_UNDERLINE)
        y += 1
        for o in organs:
            status = o.get("status", "?")
            attr = curses.A_NORMAL if status == "alive" else curses.A_DIM
            age = td.format_age(o.get("last_heartbeat_age_seconds"))
            _safe_addstr(
                win, y, 2,
                f"{o.get('name', '?'):<16}{status:<10}{age:<14}{o.get('version', '?'):<10}",
                attr,
            )
            y += 1
        if not organs:
            _safe_addstr(win, y, 2, "(no organs currently registered)", curses.A_DIM)
            y += 1
        y += 1

    y += 1
    _safe_addstr(win, y, 2, "MACHINE (Introspection)", curses.A_BOLD)
    y += 1
    intro = data["introspection"]
    if td.is_error(intro):
        _safe_addstr(win, y, 2, f"unreachable: {intro['error']}", curses.A_DIM)
        return
    host = intro.get("host", {})
    cpu = intro.get("cpu", {})
    mem = intro.get("memory", {})
    _safe_addstr(win, y, 2, f"host: {host.get('hostname', '?')}  {host.get('kernel_name', '')} {host.get('kernel_release', '')}")
    y += 1
    load = cpu.get("load_1m")
    load_str = f"{load:.2f}" if isinstance(load, (int, float)) else "?"
    _safe_addstr(win, y, 2, f"cpu: {cpu.get('cores', '?')} cores, load(1m) {load_str}")
    y += 1
    used_gb = mem.get("used_gb")
    total_gb = mem.get("total_gb")
    if used_gb is not None and total_gb is not None:
        _safe_addstr(win, y, 2, f"memory: {used_gb:.1f} GB / {total_gb:.1f} GB used")
    y += 1


def draw_memory(win, data):
    y = 2
    _safe_addstr(win, y, 2, "MEMORY", curses.A_BOLD)
    y += 1
    stats = data["memory"]
    if td.is_error(stats):
        _safe_addstr(win, y, 2, f"unreachable: {stats['error']}", curses.A_DIM)
        return
    for key in ("ledger_entries", "indexed_entries", "unembedded", "archived_entries",
                "pinned_entries", "active_scars", "pending_promises", "open_unknowables",
                "unresolved_relations"):
        if key in stats:
            _safe_addstr(win, y, 2, f"{key:<24}{stats[key]}")
            y += 1


def draw_sandbox(win, data):
    y = 2
    _safe_addstr(win, y, 2, "SANDBOX — execution boundary", curses.A_BOLD)
    y += 1
    doctor = data["sandbox_doctor"]
    if td.is_error(doctor):
        _safe_addstr(win, y, 2, f"unreachable: {doctor['error']}", curses.A_DIM)
        return
    for key in ("docker_available", "docker_version", "configured_images"):
        if key in doctor:
            _safe_addstr(win, y, 2, f"{key:<24}{doctor[key]}")
            y += 1
    if not doctor:
        _safe_addstr(win, y, 2, "(no diagnostic data)", curses.A_DIM)

def draw_telemetry(win, data):
    y = 2
    _safe_addstr(win, y, 2, "TELEMETRY — stats", curses.A_BOLD)
    y += 1
    stats = data["telemetry_stats"]
    if td.is_error(stats):
        _safe_addstr(win, y, 2, f"unreachable: {stats['error']}", curses.A_DIM)
    else:
        _safe_addstr(win, y, 2, f"total events: {stats.get('total_events', 0)}")
        y += 1
        by_source = stats.get("by_source") or {}
        if by_source:
            _safe_addstr(win, y, 2, "by source: " + ", ".join(f"{k}={v}" for k, v in by_source.items()))
            y += 1
        avg_dur = stats.get("avg_duration_ms")
        if avg_dur is not None:
            _safe_addstr(win, y, 2, f"avg duration: {avg_dur:.1f}ms")
            y += 1

    y += 1
    _safe_addstr(win, y, 2, "RECENT EVENTS", curses.A_BOLD)
    y += 1
    recent = data["telemetry_recent"]
    if td.is_error(recent):
        _safe_addstr(win, y, 2, f"unreachable: {recent['error']}", curses.A_DIM)
        return
    if not recent:
        _safe_addstr(win, y, 2, "(nothing recorded yet — no events in the recorder)", curses.A_DIM)
        return
    now = time.time()
    for event in recent[:15]:
        age = td.format_age(now - event["timestamp"]) if event.get("timestamp") else "?"
        _safe_addstr(
            win, y, 2,
            f"{age:<10}{event.get('source', '?'):<14}{event.get('event_type', '?'):<14}{event.get('status', '?')}",
        )
        y += 1


def _pending_steps(goals):
    """Flatten every pending_approval step across every goal into one
    list, each entry carrying its own goal_id/step_id so an action on it
    is unambiguous — the panel shows one flat queue rather than nested
    per-goal lists, since approval is a queue you work through, not
    something you browse goal-by-goal."""
    if td.is_error(goals):
        return []
    out = []
    for goal in goals:
        for step in goal.get("steps", []):
            if step.get("status") == "pending_approval":
                out.append({
                    "kind": "step",
                    "goal_id": goal.get("id"),
                    "goal_description": goal.get("description", ""),
                    "step_id": step.get("id"),
                    "organ": step.get("organ"), "method": step.get("method"), "path": step.get("path"),
                    "body": step.get("body"), "description": step.get("description", ""),
                    "risk_tier": step.get("risk_tier"), "risk_reasoning": step.get("risk_reasoning", ""),
                })
    return out


def _executable_goals(goals):
    """Goals with every currently-visible step already approved (or
    mid-execution) — safe to call execute_next on right now. Only
    consults goal.status, which Executive itself already computes and
    maintains (op_approve_step sets it to "ready", op_execute_next_step
    to "executing") — this does not re-derive step-readiness itself,
    since Executive's own step-selection logic in op_execute_next_step
    is the one place that should ever decide what runs next; calling it
    and showing whatever it reports back is simpler and can't drift out
    of sync with the real rule the way re-implementing that logic here
    could."""
    if td.is_error(goals):
        return []
    return [
        {"kind": "goal", "goal_id": g.get("id"), "goal_description": g.get("description", ""),
         "goal_status": g.get("status")}
        for g in goals if g.get("status") in ("ready", "executing")
    ]


def _queue_items(goals):
    """The combined worklist the panel shows: steps still waiting on a
    human, then goals that are clear to actually run. One shared list,
    one shared cursor — approving a step is usually the immediate
    precursor to wanting to execute its goal, so keeping them in one
    queue instead of two separately-navigated sections matches how
    they're actually used together."""
    return _pending_steps(goals) + _executable_goals(goals)


def draw_executive(win, data, exec_state):
    """The one other interactive panel besides Input. Read status only
    — approve()/reject()/execute_next() themselves live in tui_data.py
    and hit the real Executive endpoints, no gating logic of its own
    added here, same discipline draw_input already documents for
    itself. Nothing here ever acts on a single keystroke — select, then
    a separate confirming keypress (or typed reason for reject) — since
    a curses window is easy to have a stray key land in, and this is
    the one panel that can trigger a real action."""
    max_y, max_x = win.getmaxyx()
    y = 2
    _safe_addstr(win, y, 2, "EXECUTIVE — approval & execution queue", curses.A_BOLD)
    y += 1
    goals = data["executive_goals"]
    if td.is_error(goals):
        _safe_addstr(win, y, 2, f"unreachable: {goals['error']}", curses.A_DIM)
        return

    items = _queue_items(goals)
    exec_state["items"] = items
    if items:
        exec_state["selected"] = min(exec_state["selected"], len(items) - 1)

    if not items:
        _safe_addstr(win, y, 2, "(nothing pending — no steps to approve, no goals ready to run)", curses.A_DIM)
        y += 2
    else:
        _safe_addstr(win, y, 2, "[k/up j/down] select  [a] approve  [x] reject  [e] execute next step", curses.A_DIM)
        y += 1
        list_bottom = min(max_y - 6, y + len(items))
        for i, item in enumerate(items):
            if y >= list_bottom:
                _safe_addstr(win, y, 2, f"... and {len(items) - i} more", curses.A_DIM)
                break
            selected = i == exec_state["selected"] and exec_state["mode"] == "browse"
            marker = ">" if selected else " "
            if item["kind"] == "step":
                line = (f"{marker} [{item['risk_tier'] or '?':<10}] {item['organ']:<12}{item['method']:<6}"
                        f"{item['path'][:28]:<28} {item['description'][:35]}")
            else:
                line = f"{marker} [{item['goal_status']:<10}] READY TO RUN: {item['goal_description'][:50]}"
            _safe_addstr(win, y, 2, line, curses.A_REVERSE if selected else curses.A_NORMAL)
            y += 1
        y += 1

        if 0 <= exec_state["selected"] < len(items):
            sel = items[exec_state["selected"]]
            _safe_addstr(win, y, 2, f"goal: {sel['goal_description'][:70]}", curses.A_DIM)
            y += 1
            if sel["kind"] == "step":
                if sel["risk_reasoning"]:
                    _safe_addstr(win, y, 2, f"risk reasoning: {sel['risk_reasoning'][:70]}", curses.A_DIM)
                    y += 1
                if sel["body"]:
                    _safe_addstr(win, y, 2, f"body: {str(sel['body'])[:70]}", curses.A_DIM)
                    y += 1

    y += 1
    if exec_state["mode"] == "confirm_approve":
        sel = items[exec_state["selected"]]
        _safe_addstr(win, y, 2, f"approve {sel['organ']} {sel['method']} {sel['path']}? [y]es / [n]o", curses.A_REVERSE)
    elif exec_state["mode"] == "confirm_execute":
        sel = items[exec_state["selected"]]
        _safe_addstr(win, y, 2, f"run next step of {sel['goal_description'][:50]!r}? [y]es / [n]o", curses.A_REVERSE)
    elif exec_state["mode"] == "reject_reason":
        _safe_addstr(win, y, 2, f"reject reason (Enter=submit, Esc=cancel): {exec_state['reason_buffer']}",
                      curses.A_REVERSE)

    if exec_state.get("message"):
        _safe_addstr(win, max_y - 2, 2, exec_state["message"], curses.A_BOLD)


def draw_orchestrator(win, data):
    y = 2
    _safe_addstr(win, y, 2, "ORCHESTRATOR — managed services", curses.A_BOLD)
    y += 1
    services = data["orchestrator_services"]
    if td.is_error(services):
        _safe_addstr(win, y, 2, f"unreachable: {services['error']}", curses.A_DIM)
        return
    if not services:
        _safe_addstr(win, y, 2, "(no services configured)", curses.A_DIM)
        return
    for svc in services:
        status = svc.get("status", "?")
        attr = curses.A_NORMAL if status == "running" else curses.A_DIM
        _safe_addstr(win, y, 2, f"{svc.get('name', '?'):<16}{svc.get('driver', '?'):<16}{status:<12}{svc.get('detail', '')}", attr)
        y += 1


def draw_misc(win, data):
    y = 2
    _safe_addstr(win, y, 2, "REFLECTION", curses.A_BOLD)
    y += 1
    refl = data["reflection_status"]
    if td.is_error(refl):
        _safe_addstr(win, y, 2, f"unreachable: {refl['error']}", curses.A_DIM)
    else:
        enabled = "ON" if refl.get("enabled") else "OFF"
        _safe_addstr(win, y, 2, f"{enabled} — interval {refl.get('interval_seconds', '?')}s, model {refl.get('model', '?')}")
    y += 2

    _safe_addstr(win, y, 2, "SANDBOX", curses.A_BOLD)
    y += 1
    sbx = data["sandbox_doctor"]
    if td.is_error(sbx):
        _safe_addstr(win, y, 2, f"unreachable: {sbx['error']}", curses.A_DIM)
    else:
        docker = "available" if sbx.get("docker_available") else "NOT available"
        _safe_addstr(win, y, 2, f"docker: {docker} ({sbx.get('docker_version') or 'n/a'})")
    y += 2

    _safe_addstr(win, y, 2, "COMMUNICATIONS — topics", curses.A_BOLD)
    y += 1
    topics = data["bus_topics"]
    if td.is_error(topics):
        _safe_addstr(win, y, 2, f"unreachable: {topics['error']}", curses.A_DIM)
    elif not topics:
        _safe_addstr(win, y, 2, "(no topics yet)", curses.A_DIM)
    else:
        for t in topics[:8]:
            _safe_addstr(win, y, 2, f"{t.get('topic', '?'):<20}{t.get('event_count', 0)} events")
            y += 1
    y += 2

    _safe_addstr(win, y, 2, "CRITIC", curses.A_BOLD)
    y += 1
    rules = data["critic_rules"]
    if td.is_error(rules):
        _safe_addstr(win, y, 2, f"unreachable: {rules['error']}", curses.A_DIM)
    else:
        _safe_addstr(win, y, 2, f"{len(rules)} rule(s) loaded")



def _test_status_line(snapshot):
    if snapshot["running"]:
        started = snapshot.get("started")
        age = td.format_age(time.time() - started) if started else "?"
        return f"RUNNING — {snapshot['label']} — {age}"
    rc = snapshot.get("returncode")
    if rc is None:
        return "IDLE — no test run yet"
    return "PASS" if rc == 0 else f"FAIL (exit {rc})"


def _test_summary(snapshot):
    summary = snapshot.get("summary") or {}
    bits = []
    for key, label in (("passed", "passed"), ("failed", "failed"),
                       ("errors", "errors"), ("skipped", "skipped"),
                       ("warnings", "warnings")):
        value = summary.get(key)
        if value is not None:
            bits.append(f"{value} {label}")
    duration = summary.get("duration")
    if duration is not None:
        bits.append(f"{duration:.2f}s")
    return "  ".join(bits)


def draw_tests(win, test_state):
    max_y, max_x = win.getmaxyx()
    snapshot = test_state["runner"].snapshot()
    suites = test_state["suites"]
    selected = test_state["selected"]

    _safe_addstr(win, 2, 2, "TEST CENTER", curses.A_BOLD)
    _safe_addstr(win, 2, 15, _test_status_line(snapshot))
    summary = _test_summary(snapshot)
    if summary:
        _safe_addstr(win, 3, 2, summary, curses.A_DIM)

    # On normal terminals the suite selector and run output share the screen
    # side-by-side.  On narrow terminals we fall back to a single column.
    if max_x >= 100:
        left_w = min(34, max_x // 3)
        right_x = left_w + 3
        _safe_addstr(win, 5, 2, "SUITES", curses.A_BOLD)
        _safe_addstr(win, 5, right_x, "RESULT / OUTPUT", curses.A_BOLD)
        _safe_addstr(win, 6, 2, "Enter run   t full   j/k select   r refresh", curses.A_DIM)

        list_top = 8
        list_bottom = max_y - 3
        visible_suites = max(0, list_bottom - list_top)
        start = 0
        if selected >= visible_suites and visible_suites:
            start = selected - visible_suites + 1
        for row, i in enumerate(range(start, min(len(suites), start + visible_suites))):
            attr = curses.A_REVERSE if i == selected else curses.A_NORMAL
            _safe_addstr(win, list_top + row, 2, suites[i][:left_w - 3], attr)

        out_top = 7
        lines = snapshot.get("lines") or []
        if snapshot.get("running"):
            _safe_addstr(win, out_top, right_x, "live output", curses.A_DIM)
        elif snapshot.get("returncode") is None:
            _safe_addstr(win, out_top, right_x, "No test run yet. Select a suite and press Enter.", curses.A_DIM)
        elif snapshot.get("returncode") == 0:
            _safe_addstr(win, out_top, right_x, "completed successfully", curses.A_BOLD)
        else:
            _safe_addstr(win, out_top, right_x, "completed with failures", curses.A_BOLD)

        visible = max(0, max_y - out_top - 3)
        for row, line in enumerate(lines[-visible:]):
            _safe_addstr(win, out_top + 1 + row, right_x, line[:max_x - right_x - 2])
    else:
        y = 5
        _safe_addstr(win, y, 2, "SUITES", curses.A_BOLD)
        y += 1
        for i, suite in enumerate(suites):
            attr = curses.A_REVERSE if i == selected else curses.A_NORMAL
            _safe_addstr(win, y, 4, suite, attr)
            y += 1
            if y >= max_y // 2:
                break
        y = max_y // 2
        _safe_addstr(win, y, 2, "OUTPUT", curses.A_BOLD)
        y += 1
        lines = snapshot.get("lines") or []
        for line in lines[-max(0, max_y - y - 2):]:
            _safe_addstr(win, y, 2, line)
            y += 1


def draw_diagnostics(win, checks_state):
    y = 2
    _safe_addstr(win, y, 2, "LIVE DIAGNOSTICS", curses.A_BOLD)
    y += 1
    _safe_addstr(win, y, 2, "Read-only HTTP sweep using the Registry's current addresses.", curses.A_DIM)
    y += 2
    checks = checks_state.get("checks")
    if checks is None:
        _safe_addstr(win, y, 2, "No sweep run yet. Press [d] to run it.", curses.A_DIM)
        return
    passed = sum(1 for c in checks if c.get("ok"))
    _safe_addstr(win, y, 2, f"result: {passed}/{len(checks)} reachable")
    y += 2
    for check in checks:
        status = "OK" if check.get("ok") else "DOWN"
        attr = curses.A_NORMAL if check.get("ok") else curses.A_DIM
        _safe_addstr(win, y, 2, f"{check.get('organ', '?'):<18}{status:<7}{check.get('label', '')}", attr)
        y += 1
        if not check.get("ok"):
            result = check.get("result") or {}
            _safe_addstr(win, y, 4, str(result.get("error", result))[:120], curses.A_DIM)
            y += 1
        if y >= win.getmaxyx()[0] - 2:
            break

def draw_input(win, io_state):
    """The one interactive panel — everywhere else is read-only. Sends
    to the real I/O Interface organ, the same front door every other
    caller uses: POST /io/handle for the real thing (Critic-gated,
    same as any other caller), or a leading '?' for POST /io/interpret
    — a dry run that shows what WOULD happen without doing it or
    creating a goal. This panel adds no gating logic of its own; a
    human typing directly into a live terminal already IS the human
    approval step for anything /io/handle itself doesn't already gate
    further behind Critic."""
    max_y, max_x = win.getmaxyx()
    _safe_addstr(win, 2, 2, "I/O INTERFACE — real front door", curses.A_BOLD)
    _safe_addstr(win, 3, 2, "type a request, Enter to send. Prefix with ? to dry-run (no action taken).", curses.A_DIM)

    history = io_state["history"]
    # Leave room for: title(2) + hint(1) + blank(1) + prompt line(1) + margin(1)
    available_rows = max(0, max_y - 8)
    y = 5
    for entry in history[-((available_rows // 3) or 1):]:
        marker = "?" if entry["dry_run"] else ">"
        _safe_addstr(win, y, 2, f"{marker} {entry['text']}", curses.A_BOLD)
        y += 1
        for line in entry["display_lines"]:
            _safe_addstr(win, y, 4, line, curses.A_DIM if entry["dry_run"] else curses.A_NORMAL)
            y += 1
            if y >= max_y - 3:
                break
        y += 1
        if y >= max_y - 3:
            break

    prompt_y = max_y - 2
    _safe_addstr(win, prompt_y, 2, f"> {io_state['buffer']}", curses.A_REVERSE)


def _summarize_io_response(response: dict) -> list:
    """Turns a real /io/handle or /io/interpret JSON response into a
    few short display lines — real fields from the real response, no
    invented formatting that could misrepresent what actually
    happened."""
    if td.is_error(response):
        return [f"error: {response['error']}"]
    if not response.get("matched", True):
        lines = [response.get("message", "not recognized")]
        examples = response.get("examples") or []
        if examples:
            lines.append(f"examples: {examples[0]}" + (f" (+{len(examples) - 1} more)" if len(examples) > 1 else ""))
        return lines
    if "interpreted_as" in response:  # a real /io/handle response
        interp = response["interpreted_as"]
        lines = [f"intent: {interp.get('intent')} -> {interp.get('organ')} {interp.get('method')} {interp.get('path')}"]
        risk = response.get("risk", {})
        tier = risk.get("risk_tier", "?")
        if response.get("action_taken"):
            lines.append(f"risk: {tier} — executed")
            result = response.get("result")
            if result is not None:
                lines.append(f"result: {str(result)[:100]}")
        elif "error" in response:
            lines.append(f"risk: {tier} — FAILED: {response['error']}")
        else:
            lines.append(f"risk: {tier} — needs approval, gated goal created")
            goal_id = response.get("goal_id") or (response.get("result") or {}).get("id")
            if goal_id:
                lines.append(f"goal_id: {goal_id} — approve via Executive tab or curl")
        return lines
    # a real /io/interpret response (matched, no execution attempted)
    return [f"intent: {response.get('intent')} -> {response.get('organ')} {response.get('method')} {response.get('path')}",
            f"body: {str(response.get('body'))[:100]}"]


DRAW_FUNCS = [draw_overview, draw_memory, draw_sandbox, draw_telemetry,
              draw_orchestrator, draw_misc]


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(200)

    current_tab = 0
    data = td.fetch_all()
    last_fetch = time.monotonic()
    io_state = {"buffer": "", "history": []}
    test_state = {"runner": TestRunner(), "suites": available_suites(), "selected": 0}
    checks_state = {"checks": None}
    exec_state = {"items": [], "selected": 0, "mode": "browse", "reason_buffer": "", "message": None}

    while True:
        now = time.monotonic()
        if now - last_fetch >= REFRESH_SECONDS:
            data = td.fetch_all()
            last_fetch = now

        stdscr.erase()
        draw_tab_bar(stdscr, current_tab)
        if current_tab == INPUT_TAB_INDEX:
            draw_input(stdscr, io_state)
        elif current_tab == TESTS_TAB_INDEX:
            draw_tests(stdscr, test_state)
        elif current_tab == DIAGNOSTICS_TAB_INDEX:
            draw_diagnostics(stdscr, checks_state)
        elif current_tab == EXECUTIVE_TAB_INDEX:
            draw_executive(stdscr, data, exec_state)
        else:
            # DRAW_FUNCS excludes the three command-center tabs inserted above.
            draw_index = current_tab
            if current_tab > TESTS_TAB_INDEX:
                draw_index -= 1
            if current_tab > EXECUTIVE_TAB_INDEX:
                draw_index -= 1
            if current_tab > DIAGNOSTICS_TAB_INDEX:
                draw_index -= 1
            DRAW_FUNCS[draw_index](stdscr, data)
        stdscr.refresh()

        ch = stdscr.getch()
        if ch == -1:
            continue

        if ch == curses.KEY_PPAGE:
            current_tab = (current_tab - 1) % len(TAB_NAMES)
            continue
        if ch == curses.KEY_NPAGE:
            current_tab = (current_tab + 1) % len(TAB_NAMES)
            continue

        if current_tab == INPUT_TAB_INDEX:
            if ch in (curses.KEY_ENTER, 10, 13):
                text = io_state["buffer"].strip()
                io_state["buffer"] = ""
                if text:
                    dry_run = text.startswith("?")
                    query = text[1:].strip() if dry_run else text
                    base_url = td.base_urls_from_registry(data["registry"]).get("io_interface")
                    response = (td.send_io_interpret(base_url, query) if dry_run
                                else td.send_io_handle(base_url, query))
                    io_state["history"].append({
                        "text": text, "dry_run": dry_run,
                        "display_lines": _summarize_io_response(response),
                    })
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                io_state["buffer"] = io_state["buffer"][:-1]
            elif ch == 27:
                io_state["buffer"] = ""
            elif 32 <= ch <= 126:
                io_state["buffer"] += chr(ch)
            continue

        if current_tab == TESTS_TAB_INDEX:
            if ch in (curses.KEY_UP, ord("k")) and test_state["suites"]:
                test_state["selected"] = (test_state["selected"] - 1) % len(test_state["suites"])
            elif ch in (curses.KEY_DOWN, ord("j")) and test_state["suites"]:
                test_state["selected"] = (test_state["selected"] + 1) % len(test_state["suites"])
            elif ch == ord("t"):
                test_state["runner"].start_all()
            elif ch in (curses.KEY_ENTER, 10, 13) and test_state["suites"]:
                test_state["runner"].start_suite(test_state["suites"][test_state["selected"]])
            elif ch == ord("r"):
                test_state["suites"] = available_suites()
                test_state["selected"] = min(test_state["selected"], max(0, len(test_state["suites"]) - 1))
            elif ch == ord("q"):
                break
            continue

        if current_tab == DIAGNOSTICS_TAB_INDEX:
            if ch == ord("d") or ch == ord("r"):
                checks_state["checks"] = td.fetch_live_checks(data["registry"])
            elif ch == ord("q"):
                break
            continue

        if current_tab == EXECUTIVE_TAB_INDEX:
            items = exec_state["items"]
            if exec_state["mode"] == "browse":
                if ch in (curses.KEY_UP, ord("k")) and items:
                    exec_state["selected"] = (exec_state["selected"] - 1) % len(items)
                elif ch in (curses.KEY_DOWN, ord("j")) and items:
                    exec_state["selected"] = (exec_state["selected"] + 1) % len(items)
                elif ch == ord("a") and items and items[exec_state["selected"]]["kind"] == "step":
                    exec_state["mode"] = "confirm_approve"
                elif ch == ord("x") and items and items[exec_state["selected"]]["kind"] == "step":
                    exec_state["mode"] = "reject_reason"
                    exec_state["reason_buffer"] = ""
                elif ch == ord("e") and items and items[exec_state["selected"]]["kind"] == "goal":
                    exec_state["mode"] = "confirm_execute"
                elif ch == ord("q"):
                    break
            elif exec_state["mode"] == "confirm_approve":
                if ch in (ord("y"), ord("Y")):
                    sel = items[exec_state["selected"]]
                    base_url = td.base_urls_from_registry(data["registry"]).get("executive")
                    result = td.send_executive_approve(base_url, sel["goal_id"], sel["step_id"])
                    exec_state["message"] = (f"approve failed: {result['error']}" if td.is_error(result)
                                              else f"approved: {sel['organ']} {sel['method']} {sel['path']}")
                    data = td.fetch_all()
                    last_fetch = time.monotonic()
                    exec_state["selected"] = 0
                exec_state["mode"] = "browse"
            elif exec_state["mode"] == "confirm_execute":
                if ch in (ord("y"), ord("Y")):
                    sel = items[exec_state["selected"]]
                    base_url = td.base_urls_from_registry(data["registry"]).get("executive")
                    result = td.send_executive_execute_next(base_url, sel["goal_id"])
                    if td.is_error(result):
                        exec_state["message"] = f"execute failed: {result['error']}"
                    elif result.get("done"):
                        exec_state["message"] = f"goal complete: {sel['goal_description'][:50]}"
                    elif result.get("goal_status") == "awaiting_approval":
                        exec_state["message"] = "next step still needs approval — nothing executed"
                    else:
                        exec_state["message"] = f"ran step {result.get('step_id', '?')}: {result.get('step_status', '?')}"
                    data = td.fetch_all()
                    last_fetch = time.monotonic()
                    exec_state["selected"] = 0
                exec_state["mode"] = "browse"
            elif exec_state["mode"] == "reject_reason":
                if ch in (curses.KEY_ENTER, 10, 13):
                    sel = items[exec_state["selected"]]
                    base_url = td.base_urls_from_registry(data["registry"]).get("executive")
                    result = td.send_executive_reject(base_url, sel["goal_id"], sel["step_id"],
                                                       exec_state["reason_buffer"])
                    exec_state["message"] = (f"reject failed: {result['error']}" if td.is_error(result)
                                              else f"rejected: {sel['organ']} {sel['method']} {sel['path']}")
                    data = td.fetch_all()
                    last_fetch = time.monotonic()
                    exec_state["selected"] = 0
                    exec_state["mode"] = "browse"
                elif ch == 27:
                    exec_state["mode"] = "browse"
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    exec_state["reason_buffer"] = exec_state["reason_buffer"][:-1]
                elif 32 <= ch <= 126:
                    exec_state["reason_buffer"] += chr(ch)
            continue

        if ch == ord("q"):
            break
        elif ch == ord("r"):
            data = td.fetch_all()
            last_fetch = time.monotonic()
        elif ch == ord("d"):
            checks_state["checks"] = td.fetch_live_checks(data["registry"])
        elif ord("1") <= ch <= ord("9"):
            current_tab = ch - ord("1")
        elif ch == ord("0"):
            current_tab = 9


if __name__ == "__main__":
    curses.wrapper(main)
