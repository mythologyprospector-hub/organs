# Organs

See **GOAL.md** for the project's current purpose and the feature-freeze/maximization boundary. **MAXIMIZATION_PASS.md** records the latest bounded consolidation pass.

Bucky's replacement for Akasha's monorepo. Instead of one giant codebase
sharing a single venv — where everything is tangled and you can't touch
one piece without risking the whole thing — each capability is its own
independent service ("organ") that talks to the others over HTTP,
through one shared convention, discoverable by name through a registry
instead of hardcoded addresses.

Built with a specific rule in mind: each organ gets built to completion
before moving to the next one. Akasha's failure mode was "moving on" too
early and never coming back. Memory is the proof this rule holds.

---

## Layout

```
/srv/organs/
  shared/
    organ_base.py       every organ's /health, /info, standard error envelope
    organ_client.py      every organ's self-registration + discovery
  registry/               the one fixed address in the system (port 8000)
    registry_core.py
    main.py
  memory/                  first complete organ (port 8001)
    memory_core.py
    main.py
    tests/                 57 tests, no network dependency
  communications/           pub/sub bus + dispatch (port 8002)
    comm_core.py
    main.py
    tests/                 28 tests, no network dependency
  orchestrator/             manages OS-level dependencies (port 8003)
    orchestrator_core.py
    main.py
    services.json           created on first run — EDIT the OI container name
    tests/                 28 tests, no real systemd/docker needed
  reflection/                background muttering, OFF by default (port 8004)
    reflection_core.py
    main.py
    state.json               created on first run — enabled: false
    history.jsonl
    tests/                 24 tests, no real model needed
  introspection/             the machine's live self-knowledge (port 8005)
    introspection_core.py
    main.py
    tests/                 23 tests, realistic sample command output
  sandbox/                   ephemeral isolated code execution (port 8006)
    sandbox_core.py
    main.py
    tests/                 28 tests, safety-property-focused
  critic/                    deterministic risk gate, stateless (port 8007)
    critic_core.py
    main.py
    tests/                 20 tests, every risk tier covered
  executive/                  goal/plan/step tracking, Critic-gated (port 8008)
    executive_core.py
    main.py
    tests/                 25 tests, approval-gate focused
  io_interface/               the real front door (port 8009)
    io_interface_core.py
    main.py
    tests/                 30 tests, catalog + gating logic
  forge/                      real Ollama code generation (port 8010)
    forge_core.py
    main.py
    tests/                 30 tests, includes real unmocked Ollama calls
  telemetry/                  the observation layer (port 8011)
    telemetry_core.py
    main.py
    tests/                 29 tests
  tui/                        live dashboard — a TOOL, not an organ, no port
    tui_data.py
    organs_tui.py
    tests/                 44 tests
  systemd/                  user-scope unit files, one per organ
  requirements.txt
  install.sh
```

---

## The convention

Every organ is built on two shared files, so a new organ never has to
reinvent how it presents itself or finds anyone else.

**`organ_base.py`** — `create_organ_app(name, version, description, capabilities, health_checks)`
gives you a FastAPI app with three guarantees, no matter which organ
you're talking to:

- `GET /health` — reports `ok`/`degraded`, with per-dependency detail
  (e.g. "ollama: reachable" or "ollama: unreachable, here's why")
- `GET /info` — what this organ is and what it can do
- Every error comes back as `{"error": {"code": "...", "message": "..."}}`
  — never a raw stack trace, never a shape that differs organ to organ

**`organ_client.py`** — `attach_to_registry(app, name, base_url, version, capabilities)`
registers the organ with the Registry on startup and re-registers
(heartbeats) on an interval. `discover(name)` looks up another organ's
address by name — and refuses to hand back an address for anything
that's gone stale (missed its heartbeats), rather than routing a caller
into a wall.

The same `organ_base.py` boundary also records operational HTTP activity to
Telemetry. This is intentionally shared infrastructure rather than twelve
separate implementations: reads become `request` events, writes become
`mutation` events, and HTTP failures become `failure` events. Observation is
best-effort and is skipped for `/health`, `/info`, and Telemetry itself.

`ORGAN_TELEMETRY_ENABLED=0` disables that automatic observation for isolated
test runs; production defaults to enabled.

---

## Registry

The one hardcoded address in the whole system: `http://localhost:8000`
by convention (`ORGAN_REGISTRY_URL` to override). Everything else finds
everything else through it — nobody hardcodes anyone else's port.

| Method | Path | Purpose |
|---|---|---|
| POST | `/registry/register` | Register or heartbeat (same call — an upsert) |
| GET | `/registry/organs` | List every known organ, with `alive`/`stale` status |
| GET | `/registry/organs/{name}` | Look up one organ |
| DELETE | `/registry/organs/{name}` | Deregister |

An organ that stops heartbeating (crashed, or just stopped) ages into
`stale` after `REGISTRY_STALE_AFTER` seconds (default 30) — a crash and
a clean shutdown look identical to the registry, which is deliberate:
you can't rely on a crashing process to announce its own death.

---

## Memory (v0.3.0)

The first organ built to completion. Answers GOAL.md's question set
without building 21 separate memory systems — most of those questions
turned out to be fields every record carries, not new subsystems.

**Layers:**

| Layer | What | Lifecycle |
|---|---|---|
| 0 | `ledger.jsonl` | Permanent, append-only. **Never pruned, never lost** — a thought survives even if Ollama is down when it's written. |
| 1 | `entries` (sqlite) | Active, searchable, salience-scored |
| 1.5 | `archived_entries` | Where "forgotten" entries go. Not deleted — one call (`revive`) from active again |
| 2 | `facts.jsonl` | Consolidated from clusters of similar entries, confidence-scored |
| 2.5 | `scars.jsonl` | Permanent behavioral mutations. Corrections supersede, never overwrite |
| 3 | `promises` / `unknowable` / `relations` (sqlite) | Structured state — a promise's status, a placeholder for inaccessible knowledge, an edge between any two records |

**Core principles, all covered by tests:**
- **Ledger permanence** — writing to the ledger never fails, even if the
  embedding call does. Forgetting only ever affects the *searchable
  index*, never this file.
- **Forgetting ≠ deletion** — low-salience entries get archived, not
  erased. Salience decays on recency + access frequency; pinning makes
  something permanently findable.
- **Confidence ≠ salience** — same half-life decay mechanism, two
  different questions: salience is "how findable," confidence is "how
  sure we are it's still true." Confidence never fully bottoms out;
  decayed-to-unsure isn't the same claim as known-false.
- **Nothing cheap commits permanently, unsupervised** — facts and scars
  both go through propose → human decides → canon. A local 8b model can
  suggest; only a decision makes something permanent.

### API reference

**Entries / recall**

| Method | Path | Body / params |
|---|---|---|
| POST | `/memory/add` | `text, tags, provenance, witness, confidence, owner, may_reveal, may_modify, may_delete` |
| GET | `/memory/recall` | `q, k, include_archived, sim_weight, sal_weight` |
| GET | `/memory/entries/{id}` | — |
| POST | `/memory/entries/{id}/confirm` | resets confidence decay |
| POST | `/memory/entries/{id}/pin` | — |
| DELETE | `/memory/entries/{id}/pin` | — |
| POST | `/memory/entries/{id}/revive` | — |
| GET | `/memory/list` | `n` |
| GET | `/memory/stats` | — |
| GET | `/memory/archived` | `n` |
| POST | `/memory/backfill` | re-embeds anything missing from the index |
| POST | `/memory/prune` | `threshold, min_age_days, dry_run` |
| GET | `/memory/doctor` | deep Ollama/data-dir diagnostic |

**Facts**

| Method | Path | Body / params |
|---|---|---|
| POST | `/memory/consolidate` | `threshold, min_witnesses` |
| GET | `/memory/proposals` | `status` |
| POST | `/memory/proposals/{id}/decide` | `decision: accept\|skip` |
| GET | `/memory/facts` | `n` |

**Scars**

| Method | Path | Body / params |
|---|---|---|
| POST | `/memory/scars/propose` | `trigger_event, lesson, confidence, source_ids, supersedes` |
| GET | `/memory/scars/proposals` | `status` |
| POST | `/memory/scars/proposals/{id}/decide` | `decision: accept\|reject` |
| GET | `/memory/scars` | `status: active\|superseded` |

**Promises**

| Method | Path | Body / params |
|---|---|---|
| POST | `/memory/promises` | `text, owner, condition` |
| GET | `/memory/promises` | `status: pending\|fulfilled\|broken\|cancelled` |
| POST | `/memory/promises/{id}/resolve` | `status, note` |

**Unknowable**

| Method | Path | Body / params |
|---|---|---|
| POST | `/memory/unknowable` | `description, reason, confidence_exists, owner_to_request` |
| GET | `/memory/unknowable` | `status: inaccessible\|resolved` |
| POST | `/memory/unknowable/{id}/resolve` | `resolved_entry_id` |

**Relations**

| Method | Path | Body / params |
|---|---|---|
| POST | `/memory/relations` | `id_a, type_a, id_b, type_b, relation_type, note` |
| GET | `/memory/relations` | `status, relation_type` |
| POST | `/memory/relations/{id}/resolve` | `resolved_which, note` |

`relation_type` is one of `contradicts, relates_to, supersedes,
caused_by, supports`. `contradicts`/`supersedes` start `unresolved` and
need a decision; the rest are just links and resolve immediately.
`type_a`/`type_b` are one of `entry, fact, scar, promise, unknowable` —
one edge table connects any two kinds of record.

### Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `LLAMA_MEMORY_DIR` | `./data` | Where the ledger + sqlite db live |
| `OLLAMA_HOST` | `http://localhost:11434` | — |
| `EMBED_MODEL` | `nomic-embed-text` | — |
| `CONSOLIDATE_MODEL` | `llama3.1:8b` | Used for fact distillation |
| `SALIENCE_HALF_LIFE_DAYS` | `30` | How fast findability decays without reinforcement |
| `CONFIDENCE_HALF_LIFE_DAYS` | `90` | How fast trust decays without confirmation |
| `PRUNE_DEFAULT_THRESHOLD` | `0.15` | Salience floor before something's archived |
| `PRUNE_MIN_AGE_DAYS` | `7` | Nothing gets forgotten just for being new |
| `MEMORY_BASE_URL` | `http://localhost:8001` | What Memory tells the registry to call it |

---

## Communications (v0.1.0)

Two different problems that turned out to share one store:

- **The bus** (publish/consume) — "this happened, whoever cares can
  react." Broadcast semantics: every consumer independently tracks its
  own cursor into a topic's history, so one consumer reading an event
  never removes it for anyone else. Pull-based — consumers poll for
  what's new, rather than Communications pushing into every organ's own
  inbound endpoint. Simpler, and no organ needs to implement a webhook
  receiver just to listen.
- **Dispatch** — "one of you handle this." Generalized straight from
  `group_chat.py`'s round_robin/irc modes: back then it was "which agent
  speaks next in this chat," here it's "which organ (or all of them)
  should get this," with the same handful of strategies.

### API reference

**Bus**

| Method | Path | Body / params |
|---|---|---|
| POST | `/bus/topics/{topic}/publish` | `event_type, payload, publisher` |
| GET | `/bus/topics` | list all topics with event counts |
| GET | `/bus/topics/{topic}/events` | `since_id, limit` — peek, doesn't touch any cursor |
| GET | `/bus/consume` | `consumer, topics (comma-separated), limit` — the normal path, auto-advances that consumer's cursor |
| GET | `/bus/consumers` | every consumer's cursor per topic |
| POST | `/bus/consumers/{consumer}/topics/{topic}/reset` | `to_id` — rewind for replay/debugging |

**Dispatch**

| Method | Path | Body / params |
|---|---|---|
| POST | `/bus/dispatch` | `dispatch_key, candidates, strategy: round_robin\|random\|broadcast` |
| POST | `/bus/dispatch/{dispatch_key}/reset` | restart a round_robin rotation from the top |

`round_robin` state is remembered per `dispatch_key`, so repeated calls
with the same key actually take turns rather than restarting each time.
If the candidate list changes between calls, the rotation index still
applies to whatever list you send next — documented behavior, not a
silent gotcha.

### Current integration state

Memory is now a real publisher: accepted facts, scars, resolved promises,
resolved unknowables, and resolved relations publish the event types
documented in `DEV_NOTES.md`. The bus remains pull-based and broadcast,
with independent cursors per consumer.

There is still **no organ consumer** of those Memory topics. The existing
architecture does not currently specify which organ should react to which
bus event, so this integration pass does not invent a subscriber. That
question remains explicitly open until an existing contract answers it.

### Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `COMM_DATA_DIR` | `./data` | Where the bus's sqlite db lives |
| `COMM_BASE_URL` | `http://localhost:8002` | What Communications tells the registry to call it |

---

## Orchestrator (v0.1.0)

Manages the OS-level things organs actually depend on — Ollama, Open
WebUI, the OI sandbox — as a **fixed, pre-defined set of services** from
`services.json`. This boundary is deliberate, not incidental: there is no
API that accepts an arbitrary command, container name, or unit name from
a request. Every operation is "start/stop/status THIS named service,"
never "run this." That's what keeps an organ that can touch the OS from
being a remote command-execution hole.

**Registry vs. Orchestrator — different layers:**
Registry tracks *organs* (is Memory alive, discoverable by name).
Orchestrator tracks *what organs depend on* (is Ollama up). An organ
dying is "restart the process"; a dependency being down is "the thing
underneath the organs isn't there yet." Different failure mode, different
organ.

**Drivers**, one per kind of thing a service can be:
- `systemd_user` — `systemctl --user` (this process's own scope, no sudo)
- `systemd_system` — status is readable without sudo; start/stop uses
  `sudo -n` (non-interactive), which fails **fast and clearly** if
  passwordless sudo isn't configured, rather than hanging a request on a
  password prompt nobody's there to answer
- `docker` — `docker inspect` / `start` / `stop`

Default `services.json` (created on first run):

```json
{
  "ollama":     {"driver": "systemd_system", "unit": "ollama.service", "always_on": true},
  "open-webui": {"driver": "docker", "container": "open-webui", "always_on": true},
  "oi-sandbox": {"driver": "docker", "container": "REPLACE_ME_oi_container_name", "always_on": false}
}
```

**Edit `oi-sandbox`'s container name before relying on it** — find the
real one with `docker ps -a`. `always_on: false` matters here too: it's
the flag that means "stopped is normal, not alarming" for something
meant to be dormant until needed, versus Ollama/Open WebUI where stopped
means something's actually wrong.

### API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/orchestrator/services` | Every configured service + live status |
| GET | `/orchestrator/services/{name}` | One service's status |
| POST | `/orchestrator/services/{name}/start` | No-ops cleanly if already running |
| POST | `/orchestrator/services/{name}/stop` | No-ops cleanly if already stopped or not found |
| POST | `/orchestrator/services/{name}/restart` | Stop, then start |
| GET | `/orchestrator/doctor` | Config path, whether it's readable, what's configured |

Status is always one of `running`, `stopped`, `not_found`, or `error` —
`not_found` specifically means a docker container by that name doesn't
exist at all, distinct from existing-but-stopped.

### Enabling start/stop for system-scope services

Reading Ollama's status never needs sudo. Starting or stopping it does,
since `ollama.service` is system-scope. Scope a NOPASSWD rule to exactly
that command — not blanket sudo:

```bash
sudo visudo -f /etc/sudoers.d/organs-orchestrator
```
```
jimmydev ALL=(root) NOPASSWD: /usr/bin/systemctl start ollama.service, /usr/bin/systemctl stop ollama.service, /usr/bin/systemctl restart ollama.service
```

Without this, Orchestrator can still always *report* Ollama's status —
only start/stop of that one service is affected, and it fails with a
clear message telling you exactly this, rather than hanging.

### Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `ORCH_CONFIG_PATH` | `./services.json` | The fixed service registry |
| `ORCH_BASE_URL` | `http://localhost:8003` | What Orchestrator tells the registry to call it |

### Honesty about test coverage

The `sudo -n` failure path is covered by a unit test using sudo's actual
real-world stderr text (`"sudo: a password is required"`), not a live
run — the sandbox this was built in doesn't have `sudo` installed at
all. `echo` and the "command not found" paths were verified against a
real subprocess. Worth a live check on Bucky the first time you actually
call start/stop on `ollama`.

---

## Reflection (v0.1.0)

The "old man muttering" organ. A background loop that, **only when
explicitly enabled**, periodically reads recent Memory activity and
writes a low-confidence, self-authored thought back into Memory —
`provenance: "self"`, `witness: "inferred"`, `confidence: 0.3`. It never
answers anyone and nothing waits on it. This isn't a new memory
subsystem — GOAL.md's "Reflection" book was deliberately never given its
own storage; this is why. It's a periodic *writer*, using Memory's own
API like any other organ would.

**OFF by default, and that's the entire safety story.** `state.json`
starts with `enabled: false`. The systemd service *running* is not the
same thing as it *thinking* — you have to explicitly opt in:

```bash
curl -X POST localhost:8004/reflection/enable
curl -X POST localhost:8004/reflection/disable
curl localhost:8004/reflection/status
```

### API reference

| Method | Path | Body / params |
|---|---|---|
| GET | `/reflection/status` | enabled, interval, model, last run, run count |
| POST | `/reflection/enable` | — |
| POST | `/reflection/disable` | — |
| POST | `/reflection/configure` | `interval_seconds` (min 10), `model`, `max_context_entries`, `max_context_chars` |
| POST | `/reflection/tick` | Manually trigger one cycle right now, **bypassing the toggle** — for testing |
| GET | `/reflection/history` | `n` — newest first |

### A bug this README exists partly to document

The first version of the background loop `sleep()`d for the *currently
configured* interval between checks — which at startup is the 300s
default, read once before you've ever had a chance to enable anything.
Flipping the toggle on right after boot wouldn't take effect for up to
five minutes, because the loop wasn't due to check again until then. A
live test (enable, wait 13s, expect a run, get none) caught this — not a
read of the code, an actual run that came back empty when it shouldn't
have. Fixed by splitting poll rate from tick rate: the loop checks the
toggle every 5 seconds regardless of the configured interval, and only
runs an actual tick once that interval has genuinely elapsed since the
last one. Re-verified live afterward — two automatic ticks landed 10s
apart with `interval_seconds: 10`, and disabling stopped new ticks
within the next poll, not the next interval.

### Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `REFLECTION_STATE_PATH` | `./state.json` | Toggle + settings |
| `REFLECTION_HISTORY_PATH` | `./history.jsonl` | Every tick's outcome, success or not |
| `REFLECTION_BASE_URL` | `http://localhost:8004` | What Reflection tells the registry to call it |
| `OLLAMA_HOST` | `http://localhost:11434` | Same as Memory's — this is a separate call to the same Ollama |

Default model is `phi4-mini:latest` — small and fast on purpose, since
this runs unattended and shouldn't compete hard with whatever else is
using Ollama. Change it with `/reflection/configure`.

---

## Introspection (v0.1.0)

The machine's live, queryable self-knowledge — deliberately a small slice
of `DEEPSCAN_ROADMAP.md`'s original 13-phase plan, not the whole atlas.
Building all of that now would repeat exactly the mistake GOAL.md's first
draft made: impressive on paper, never finished. This ships the subset
that's actually load-bearing for what exists *today* — what's running,
what Ollama has, what dev tools are present, what Docker's holding.
Everything else from the roadmap (GPU details, security surface, storage
forensics, the full knowledge graph) stays unbuilt on purpose.

The core distinction from the original `deepscan.sh`: that was a report
you generated and read once. This is queryable live — any organ can ask
"what does this machine look like right now" the same way you'd ask
Memory a question, instead of you feeding it a stale `.txt` file by hand.

### Collectors

| Collector | What it reports |
|---|---|
| `host` | hostname, OS, kernel, arch, uptime |
| `cpu` | model, core count, load average |
| `memory` | total/used/available, in bytes and GB |
| `disk` | real filesystems only — tmpfs/overlay/proc/etc. filtered out |
| `ollama` | installed models (`ollama list`), or cleanly reports "not installed" |
| `docker` | containers and images, or cleanly reports "not installed" |
| `dev_tools` | presence + version of git, python3, pip3, node, npm, rustc, cargo, gcc, docker, ollama |

Results are cached for `INTROSPECT_CACHE_TTL` seconds (default 30) —
`df`/`docker` aren't free to run on every request. Pass `?force=true` to
bypass the cache.

### API reference

| Method | Path | Params |
|---|---|---|
| GET | `/introspect/summary` | `force` — everything at once |
| POST | `/introspect/refresh` | clears the whole cache, returns fresh summary |
| GET | `/introspect/host` | `force` |
| GET | `/introspect/cpu` | `force` |
| GET | `/introspect/memory` | `force` |
| GET | `/introspect/disk` | `force` |
| GET | `/introspect/ollama` | `force` |
| GET | `/introspect/docker` | `force` |
| GET | `/introspect/dev_tools` | `force` |

### Tested against realistic output, not invented output

Every parser test feeds actual real-world command output format — a
genuine `free -b` table, a genuine `ollama list` table, a genuine `df`
line with an `overlay` mount that should get filtered — not a simplified
stand-in. Then verified live against this build's own sandbox: host,
CPU, memory, disk, and dev-tool detection all ran for real, no mocking,
and correctly reported real values (Ubuntu 24.04, real core count, real
free/used memory). Ollama and Docker correctly reported "not installed"
in that environment rather than crashing, the same honest pattern as
everywhere else in this system.

One live finding worth being upfront about: the disk collector doesn't
filter FUSE-backed network mounts, and in the sandbox this was built in,
that meant a virtual filesystem reporting an absurd multi-petabyte size.
Bucky doesn't have anything like that mounted, so it won't show up there
— but it's a real example of why `df` output needs a skeptical reader,
not blind trust, and it's not filtered here on purpose rather than by
oversight — over-fitting the parser to one sandbox's quirks felt worse
than leaving it honest.

### Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `INTROSPECT_BASE_URL` | `http://localhost:8005` | What Introspection tells the registry to call it |
| `INTROSPECT_CACHE_TTL` | `30` | Seconds before a cached collector result is considered stale |

---

## Sandbox (v0.1.0)

Runs code in an ephemeral, isolated Docker container, then destroys the
whole thing. This is the piece the future code forge needs to actually
*execute* what it writes — "run it for real, measure coverage," the
step in the forge pipeline that can't happen inside any organ that
manages persistent, trusted state.

**The safety model here is deliberately different from Memory's.**
Facts and scars use propose-then-a-human-decides because they *become
permanent and trusted*. Nothing here does. Every job gets a fresh
container from a fixed base image, no network by default, hard
memory/CPU/pid/time limits, and the workspace is destroyed immediately
after — success, failure, or timeout, no exceptions. The safety property
is **containment**, not review. A bad job can waste its own container's
resources; it can't touch Bucky, can't persist, can't affect the next
job.

**The fixed boundary, same discipline as Orchestrator's service list:**
only two pre-approved base images exist. There is no API surface that
accepts an arbitrary image name.

```json
{"python": "python:3.11-slim", "node": "node:20-slim"}
```

### API reference

| Method | Path | Body |
|---|---|---|
| POST | `/sandbox/jobs` | `language, files (dict), command, timeout_seconds, network, memory, cpus` |
| GET | `/sandbox/languages` | The fixed allowlist above |
| GET | `/sandbox/doctor` | Whether Docker's actually reachable |

`files` is a flat `{"path/to/file.py": "contents"}` map — nested paths
are fine (`src/main.py`), path traversal (`../`) and absolute paths are
rejected before anything touches disk.

### Every safety property has its own test

Not "the suite passes" — each guarantee is checked directly: path
traversal rejected, absolute paths rejected, network off unless
explicitly requested, resource limits actually present in the
constructed Docker command, oversized/too-numerous files rejected, and
the workspace directory verified gone afterward in three separate
scenarios (success, Docker failure, and timeout) — not just the happy
path.

### A bug this section exists partly to document

The first version of `_run()` *raised* an exception when Docker wasn't
installed, instead of returning a clean result the way every other
organ's `_run()` does. The mocked test for "Docker unavailable" passed
anyway — because the fake simulated a clean return value that the real
function never actually produced. A live run against this sandbox
(which genuinely has no Docker) caught the mismatch immediately: calling
the real function crashed instead of reporting cleanly. Fixed to match
the established convention, and a second test was added that calls the
*real*, unmocked function against this Docker-less environment
specifically so this exact class of bug — a mock that quietly diverges
from reality — can't silently pass again. Same lesson as Introspection's
Ollama-size bug a few organs ago: a green test suite proves the mock was
self-consistent, not that it matched the real thing.

### Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `SANDBOX_BASE_URL` | `http://localhost:8006` | What Sandbox tells the registry to call it |
| `SANDBOX_DEFAULT_TIMEOUT` | `60` | Seconds, per job |
| `SANDBOX_MAX_TIMEOUT` | `300` | Hard cap — no job can request longer |
| `SANDBOX_DEFAULT_MEMORY` | `512m` | Per-container memory limit |
| `SANDBOX_DEFAULT_CPUS` | `1.0` | Per-container CPU limit |
| `SANDBOX_MAX_FILES` | `50` | Per job |
| `SANDBOX_MAX_TOTAL_BYTES` | `2000000` | Per job (2MB) |
| `SANDBOX_WORKSPACE_ROOT` | system temp dir | Where job workspaces are created and destroyed |

Note: this is a user-scope systemd unit, so it can't meaningfully
declare `After=docker.service` (a system-scope unit) — same reason
Memory doesn't declare `After=ollama.service`. If Docker isn't up yet
when Sandbox starts, `/health` honestly reports it as degraded, and jobs
fail cleanly with `exit_code: 127` rather than hanging.

---

## Critic (v0.1.0)

Evaluates a **proposed** action, before it runs, and never after.
Deterministic — a fixed rule set, no LLM. A rule engine can't be talked
into approving something by clever phrasing, doesn't degrade under load,
and its reasoning is always inspectable. This is the system's own
principle — *"don't build moon-shot cognition when a small deterministic
organ will accomplish the job"* — applied to the one place getting it
wrong matters most.

**Fails closed.** Anything not explicitly recognized defaults to
`high_risk`. The allowlist has to affirmatively cover something for it
to skip human review — absence of a matching rule is never treated as
permission. This is the single most important property in the whole
organ, and it has its own dedicated test.

Four tiers, only two of which can auto-proceed:

| Tier | Meaning | Auto-proceeds? |
|---|---|---|
| `safe` | Read-only, or already isolated (Sandbox, network off) | Yes |
| `reversible` | A normal write, nothing becomes permanent | Yes |
| `caution` | Something becoming canon (a fact/scar/promise/relation decision) | **No** |
| `high_risk` | Touches real OS-level state, or an unrecognized action | **No** |

### API reference

| Method | Path | Body |
|---|---|---|
| POST | `/critic/evaluate` | `organ, method, path, body` → risk tier + reasoning |
| GET | `/critic/rules` | The actual rule set, for transparency |

Critic is stateless — every call is independent, nothing persists, no
data directory. It only ever sees what's about to happen, never a
history of what already did.

---

## Executive (v0.1.0)

The first organ in this system that can chain actions across other
organs on its own — which is exactly why it's the most conservatively
built. Highest-stakes piece so far, by a wide margin.

**What this deliberately does NOT do:** use an LLM to autonomously turn
a vague goal into a plan. Given what's already been established about
local model quality, promising that would be dishonest. **What it DOES
do:** track a goal, hold an *explicit* submitted plan, route every
single step through Critic before anything runs, and refuse to execute
anything Critic flags without an explicit human approval — no default,
no timeout-based auto-approval, no exception. Autonomous planning is a
real future capability, layered on top of this skeleton later, not
assumed now.

### The lifecycle

```
goal created (draft)
  → plan submitted as an explicit ordered step list
  → EVERY step classified by Critic at submission time, not later
  → safe/reversible steps: auto-approved
  → caution/high_risk steps: HALT, wait for a named human decision
  → steps execute strictly in order
  → a failed step stops the goal — never cascades past a problem
  → goal ends: completed / failed / blocked
```

### API reference

| Method | Path | Body |
|---|---|---|
| POST | `/executive/goals` | `description, created_by` |
| POST | `/executive/goals/{id}/plan` | `steps: [{organ, method, path, body, description}]` |
| POST | `/executive/goals/{id}/steps/{step_id}/approve` | `approved_by` |
| POST | `/executive/goals/{id}/steps/{step_id}/reject` | `reason` |
| POST | `/executive/goals/{id}/execute_next` | Runs exactly one step, or reports why it can't |
| GET | `/executive/goals/{id}` | Full goal + every step's status |
| GET | `/executive/goals` | `status` filter |

### Proven live, not just unit-tested

A full pipeline ran for real: Registry, Memory, Critic, and Executive all
live, a goal submitted with one safe step (a Memory read) and one risky
step (an Orchestrator restart). Critic correctly classified each. The
safe step executed automatically against real Memory and got a real
result back. Calling execute on the risky step **refused to run it** and
reported exactly why. Only after explicit approval — by name — did it
attempt to execute, and since Orchestrator wasn't running in that test,
it failed *cleanly* (a reported step failure, goal marked `failed`) —
not a crash, not a silent success, not a hang.

If Critic itself is unreachable when a plan is submitted, every step
fails closed to `high_risk`/requires-approval — a down reviewer never
means anything skips review, it means everything needs a human instead.

### Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `EXECUTIVE_DATA_DIR` | `./data` | Where goals/plans/step history live |
| `EXECUTIVE_BASE_URL` | `http://localhost:8008` | What Executive tells the registry to call it |
| `CRITIC_BASE_URL` | `http://localhost:8007` | (Critic's own var — Executive discovers it via the registry, not this) |

---

## I/O Interface (v0.1.0)

The real front door. `talk_to_memory.py` was the seed — this is the
actual thing: type a sentence, it figures out which organ should handle
it, and routes there — instead of you knowing which curl command to run.

**Deliberate scope, same reasoning as Critic:** this is deterministic
pattern matching against a fixed, curated catalog of known intents —
**not** an LLM freely interpreting arbitrary requests into arbitrary API
calls. An 8B local model guessing at API calls from natural language is
exactly the "moon-shot cognition" this system's own principle warns
against. A fixed catalog is testable, predictable, and — critically —
if nothing matches, it says so plainly and shows examples, rather than
guessing at an action it isn't confident about.

**Nothing here bypasses the safety architecture already built.** Every
interpreted action gets classified by the real Critic before anything
happens:

```
text  →  interpret against catalog  →  Critic classifies
                                              │
                          ┌───────────────────┴───────────────────┐
                          ▼                                       ▼
                  safe / reversible                      caution / high_risk
                  execute directly,                       create a real
                  show what happened                      Executive goal,
                                                            wait for approval
```

A natural-language "restart ollama" goes through *exactly* the same
gate as typing the curl command by hand — Critic still says `high_risk`,
Executive still creates a goal, a human still has to approve it by name.
The front door doesn't get to skip the door.

### API reference

| Method | Path | Body |
|---|---|---|
| POST | `/io/handle` | `text` — interprets AND acts (or creates a goal) |
| POST | `/io/interpret` | `text` — dry run, shows what WOULD happen, does nothing |
| GET | `/io/catalog` | Every known intent, with an example phrase |

### The catalog (v0.1.0)

| Say something like... | Routes to |
|---|---|
| "what do you know about X" / "recall X" | Memory recall |
| "remember that X" | Memory add |
| "remind me to X" | Memory promise |
| "memory stats" | Memory stats |
| "system status" / "what's running" | Introspection summary |
| "what models are installed" | Introspection Ollama list |
| "what containers are running" | Introspection Docker |
| "restart / stop / start X" | Orchestrator (all high_risk — gated) |
| "is X running" | Orchestrator status |
| "enable / disable reflection" | Reflection toggle |
| "run this python code: ..." | Sandbox job |

Anything else gets an honest "I don't recognize that yet" plus the full
example list — never a wrong guess.

### Proven live, not just unit-tested

A real bug got caught by the test suite before it ever shipped: the
`orchestrator_status` pattern's `is` alternative had no word boundary,
so **"run this python code"** matched **"is python"** inside the word
"th*is*" — misrouting a sandbox request to an orchestrator status check
on a service literally named "python." Fixed with a proper word
boundary, and a regression test locks in the distinction: "is" embedded
inside another word must never match; "is" as its own genuine word
still correctly can.

Then proven end-to-end with five real organs running together: a plain
English "remember that..." request produced a real write sitting in
Memory's actual ledger. A plain English "restart ollama" request
produced a real, named, waiting Executive goal — Critic classified it
`high_risk`, exactly as it would through any other path in.

### Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `IO_BASE_URL` | `http://localhost:8009` | What I/O Interface tells the registry to call it |

No data directory — stateless, same as Critic. The catalog lives in
`io_interface_core.py` itself.

---

## Forge (v0.1.0)

Generates real code from a spec by calling a real local Ollama model —
**no sim, no stub, in production.** `ollama_generate()` is a genuine
HTTP call to Ollama, same shape as Memory's `ollama_embed`/
`ollama_generate`, monkeypatched only in tests, never faked in
`main.py`. If Ollama isn't actually reachable, a build fails loudly
with an actionable error — it does not silently return placeholder
text.

**Two different external dependencies, two different existing
conventions, matched on purpose rather than picking one pattern for
both:** calling Ollama is a raw network dependency, so it follows
Memory's pattern (a top-level function in `forge_core.py`, faked
directly in tests). Calling Sandbox to actually *execute* the generated
code is calling another **organ**, so it follows Executive's pattern
instead — `run_sandbox_call` is injected into `op_build()`, with the
real implementation (`discover("sandbox")` + the actual HTTP call)
living in `main.py`.

**Forge's own workspace is PERSISTENT — unlike Sandbox's, on purpose.**
Sandbox's own module docstring already named this organ as the reason
it exists ("the piece the future code forge needs to actually execute
what it writes"), and Sandbox destroys its workspace after every job
because its output is disposable. Forge's output is the opposite — the
generated code *is* the deliverable, so nothing here auto-deletes it.
`DELETE /forge/jobs/{id}` is a human decision, never automatic cleanup.
Same hard-veto spine as every other pipeline in this system (gapforge,
pipeline_guard, the gig intake pipeline) — generate, then a human
reviews before anything ships anywhere real. There is no commit/merge/
publish/deploy verb anywhere in this organ, on purpose.

### API reference

| Method | Path | Body / Notes |
|---|---|---|
| POST | `/forge/build` | `spec, language, filename, model?, test_spec?, test_filename?, test_command?, network?` |
| GET | `/forge/jobs` | Newest first, from the append-only ledger |
| GET | `/forge/jobs/{job_id}` | Full manifest + file contents |
| DELETE | `/forge/jobs/{job_id}` | Removes the files; ledger keeps a `deleted: true` record |

If `test_spec` is given, Forge generates a test file and hands both
files to the real Sandbox organ via `POST /sandbox/jobs` — the returned
`sandbox_result` is Sandbox's own real response (`exit_code`, `stdout`,
`coverage_percent`, etc.), not a Forge-side judgment. If Sandbox is
unreachable, the build's generated code is still saved and returned —
a validation failure never destroys output that already exists.

**The test-generation call is given the actual generated implementation
code, not just the English spec a second time — this is load-bearing,
not an optimization.** Caught live on mythos1: without it, the two
Ollama calls (implementation, tests) had no way to agree on a function
name, so the test file redefined its own copy of the function and
tested that instead of importing and testing the real one — a green
test suite that validated nothing. The test prompt now includes the
real implementation verbatim and explicitly instructs against
reimplementing it.

**`network` defaults to `False`, matching Sandbox's own secure default,
and passes straight through — Forge adds no second opinion on top of
it.** The base test images (`python:3.11-slim` etc.) have no test
framework preinstalled, so running an actual `pytest` suite needs BOTH
`network: true` **and** an install step of your own inside
`test_command`, e.g. `"pip install --quiet pytest && pytest -q"`. This
is never turned on silently — it's a deliberate, explicit choice per
build, not a default Forge reaches for on your behalf.

### Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `FORGE_BASE_URL` | `http://localhost:8010` | What Forge tells the registry to call it |
| `OLLAMA_HOST` | `http://localhost:11434` | Where the real Ollama server is |
| `FORGE_MODEL` | `qwen2.5-coder:7b` | Default model — already pulled on Bucky |
| `FORGE_WORKSPACE_ROOT` | `~/forge_workspace` | Persistent job output — home dir, not `/tmp` |
| `FORGE_GENERATE_TIMEOUT` | `180` | Seconds, per generation call |

### Test discipline

Same requirement CONTRIBUTING.md holds every organ to, and the exact
class of bug Sandbox's own Docker check was caught by twice: a suite
that only ever calls a fake proves the fake is self-consistent, never
that it matches reality. `test_real_ollama_generate_survives_whatever_
this_environment_has` calls the real, unmocked `ollama_generate`
against whatever's actually on the machine it runs on — a clean
`ForgeError` where Ollama isn't running (this repo's CI, most
development boxes), or real generated text where it is (Bucky). Either
outcome passes; an unhandled exception does not.

---

## Telemetry (v0.1.0)

The observation layer. Records what actually happened — what ran, when,
how long it took, whether it succeeded, what changed — queryable by
source, event type, status, correlation ID, and time range.

**Not Memory, and the distinction is load-bearing, not semantic:**
Telemetry records operational reality without judgment — a Sandbox job
starting and exiting 0 is a telemetry event whether or not anyone ever
decides it's worth a fact or a scar. Memory decides what operational
reality is worth remembering long-term. Neither replaces the other.

**Storage mirrors Memory's own established pattern on purpose:** a
permanent, append-only `telemetry.jsonl` (never rewritten, same as
Memory's `ledger.jsonl`) plus a `telemetry.sqlite3` index for the
filtered queries a TUI or a model actually needs — by source, event
type, status, correlation ID, time range.

**Two kinds of time on every event, deliberately:** `timestamp`
(wall-clock — "when did this happen") and `monotonic_time`
(`time.monotonic()` — immune to clock adjustments, "how much time
elapsed on this process's own clock"). Duration math should use
monotonic deltas; a caller supplies `duration_ms` directly when it
measured its own operation. Telemetry never reconstructs a duration
from two wall-clock timestamps itself.

**`correlation_id` threads one externally-initiated operation into a
reconstructable causal chain** — an I/O Interface request, the
Executive goal it becomes, the Critic evaluation that gates it, the
Orchestrator action it triggers. `GET /telemetry/timeline` pulls that
exact chain back out, chronologically.

### API reference

| Method | Path | Notes |
|---|---|---|
| POST | `/telemetry/events` | `event_type, source` required; everything else optional |
| GET | `/telemetry/events` | Filter by `source, event_type, status, correlation_id, start, end, limit` |
| GET | `/telemetry/events/{event_id}` | Single event |
| GET | `/telemetry/recent` | Shortcut for an unfiltered query |
| GET | `/telemetry/timeline?correlation_id=X` | One causal chain, chronological |
| GET | `/telemetry/stats` | Counts by source/event_type/status, avg duration |

`event_id` is always server-assigned, never trusted from a caller — two
organs emitting concurrently can never collide on one.

### Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `TELEMETRY_BASE_URL` | `http://localhost:8011` | What Telemetry tells the registry to call it |
| `TELEMETRY_DATA_DIR` | `./data` (relative to the organ) | Where the ledger + sqlite index live |

### Current integration state

Telemetry is now part of the shared organ convention. `organ_base.py`
observes every non-health/non-info HTTP operation automatically: reads are
recorded as `request`, write operations as `mutation`, and HTTP failures
as `failure`. Each event carries the request path, status, measured
duration, and a correlation ID. An incoming `X-Correlation-ID` is
preserved; otherwise the boundary creates one and returns it in the
response.

Observation is deliberately best-effort. If Telemetry or the Registry is
unavailable, the organ operation continues normally. Telemetry does not
observe itself, and its internal discovery/emit traffic is marked so the
observation path cannot recurse through the Registry.

The next integration question is **causal propagation**: existing
organ-to-organ calls do not yet consistently forward the originating
correlation ID. That is a tightening pass over existing call paths, not a
new organ.

---

## Tools (not organs)

Code that lives in this repo, is real and tested, but doesn't provide
an HTTP capability and doesn't register with the Registry. The
distinction is load-bearing, not pedantic — an organ is discoverable
because something else is meant to call it; a tool is something a
human runs.

### TUI

A live terminal dashboard over everything above. Was the first thing in
this whole system that only **consumed** — every organ before it
provides a capability something else calls; the TUI called all of them
and provided nothing back. That changed with the Input tab (below),
its one deliberately interactive panel — everything else stays
read-only.

```bash
cd tui && python3 organs_tui.py
```

`1`–`8` switch tabs (Overview, Memory, Forge, Telemetry, Executive,
Orchestrator, Misc, Input), `PageUp`/`PageDown` also cycle tabs and work
from anywhere including while typing in Input, `r` forces an immediate
refresh, `q` quits. Auto-refreshes every `TUI_REFRESH_SECONDS` (default
3s). **Zero new dependencies** — `curses` is Python stdlib; nothing
here needed `requirements.txt` to grow.

**Same core-vs-render split every organ already has, applied to a
client for the first time:** `tui_data.py` makes every real HTTP call
(discovering base URLs through the real Registry, exactly like an organ
discovering another) and is independently unit tested — 26 tests, none
of them touching curses. `organs_tui.py` only formats and draws what
`tui_data.py` already fetched; curses itself isn't meaningfully
unit-testable (it needs a real terminal), so instead its 39 render
tests exercise every panel's actual drawing function against a fake
window object, proving each one survives three real shapes: healthy
data, every organ unreachable, and every organ present but empty —
because an organ being down must never take the rest of the dashboard
down with it, same discipline every organ's own health checks already
hold themselves to.

An organ that's never registered, currently down, or mid-restart shows
as exactly that, in plain language, in its own panel only — nothing
here has a fallback dataset that would make a panel look more complete
than reality. An empty Telemetry panel right now isn't a bug — nothing
calls Telemetry yet — and the panel says exactly that instead of just
showing a blank list that looks broken.

#### Input tab

Type a request, `Enter` sends it. Prefix with `?` for a dry run.

Both paths go straight to the real I/O Interface organ, the same front
door every other caller already uses — this panel adds **no gating
logic of its own** on top of what `io_interface` already does:
- Plain text → `POST /io/handle`. Routes through the real Critic, same
  as any other caller; anything Critic flags becomes a real Executive
  goal waiting on your approval instead of running. A human typing this
  directly into a live terminal already IS the human-in-the-loop step —
  this panel doesn't add a second one on top, and doesn't skip the one
  `io_interface` itself already enforces for anything risky.
- `?` prefix → `POST /io/interpret`. Shows what WOULD happen —
  matched intent, target organ, method, path, body — without doing it
  or creating a goal. Can't act on anything; nothing to gate.

Every response shown is the real organ's real JSON, summarized to a few
lines — matched intent, risk tier, whether it actually executed or
became a gated goal (with the real goal ID), or the real error if it
failed. Nothing here invents formatting that could misrepresent what
actually happened.

---

## Setup

```bash
tar -xzf organs.tar.gz && cd organs
./install.sh          # installs to /srv/organs, deps, data dirs
```

Run (two terminals, or `nohup ... &` + `disown` to survive shell exit):

```bash
cd /srv/organs/registry && uvicorn main:app --host 127.0.0.1 --port 8000
cd /srv/organs/memory   && uvicorn main:app --host 127.0.0.1 --port 8001
```

Verify:
```bash
curl localhost:8000/registry/organs
curl localhost:8001/info      # should show "0.3.0" and all four new capabilities
```

Run one organ's test suite:
```bash
cd memory && python3 -m pytest tests/ -v
```

Run every organ's test suite, aggregated (each in its own subprocess — see "Known ceilings" below for why not one shared `pytest` run):
```bash
./run_all_tests.sh
```

---

## Known ceilings — not gaps, boundaries

- **No automatic contradiction detection or scar proposal.** The
  plumbing to *record* one is real; deciding *that* something
  contradicts, or *that* an event deserves a scar, stays a human call.
  This is intentional, not deferred.
- **Reflection only mutters when explicitly enabled.** The organ exists
  and runs as a real service; it never generates unprompted thoughts
  until you flip `/reflection/enable` yourself. Off by default, on
  purpose — see the Reflection section above.
- **Recall is a linear scan** over every embedding on every query. Fine
  at current scale; will need real vector indexing if entry count gets
  into the tens of thousands.
- **No unified `pytest` from the repo root, by design — and enforced,
  not just documented.** Every organ has its own `main.py`, its own core
  module — running more than one in ONE Python process causes their bare
  module names to collide in `sys.modules` (the second organ's `import
  main` silently gets the FIRST organ's already-cached module instead
  of loading its own). This isn't theoretical: reproduced live, `pytest
  memory/tests/test_api.py forge/tests/test_api.py` in one process
  produces ten of memory's tests failing with 404s and KeyErrors — not
  because anything is broken, but because memory's fixtures ran against
  forge's app. That's worse than a crash — it looks like a real bug and
  sends whoever hits it chasing the wrong thing, which is exactly what
  happened before this was caught. A root `conftest.py` now detects any
  test collection spanning more than one organ or tool and refuses
  immediately with `pytest.exit()`, before a single test executes — "no
  tests ran," not ten confusing failures. This is the "no monorepo, no
  shared venv" principle from day one, now backed by an actual tripwire
  instead of just a comment: these organs were built to talk over HTTP,
  never to share a Python interpreter. Use `./run_all_tests.sh`
  for a real one-command "test everything," which runs each organ (and
  the `tui` tool) in its own clean subprocess — same as they actually
  deploy — rather than forcing false coexistence for the sake of test
  convenience.
- **Systemd is set up for all twelve organs** — see `systemd/`. Each organ
  is a real user-scope service, `install_systemd.sh` installs and starts
  every one, and linger is enabled so they survive logout and reboot.

## What's next

Every organ from the original list is built, plus two: Registry, Memory,
Communications, Orchestrator, Reflection, Introspection, Sandbox,
Critic, Executive, I/O Interface, Forge, Telemetry. Twelve organs, real,
tested, running live on Bucky, discoverable through the registry,
several of them genuinely reacting to and gating each other rather than
just coexisting.

The wider map (PROSPECTIVE_ORGANS.md) sketched more — State, Goals,
Attention, Curiosity, Drive, Planner — but cross-checking it against
what's already built found two of those (Knowledge, Learning/Model
Update) were already fully satisfied by Memory's existing facts/scars/
confidence system, and several others (Goals vs. Promises, Curiosity
vs. Unknowable+Relations) are close enough to existing organs that
building them without checking risks duplicating real, tested work
rather than filling an actual gap. Worth that same scrutiny before any
of them get built, not assumed wholesale from a second opinion — same
discipline GOAL.md got before Memory was ever written.

Forge landed standing on ground that already existed: Sandbox to run
what it writes, and — once Executive-gated invocation actually gets
built — Critic to gate what it proposes, Executive to hold the plan and
require approval, I/O Interface to be asked in plain language. Today
it's a direct, single-shot HTTP organ (spec in, code out, optionally
validated against the real Sandbox) — deliberately the smaller v1, not
the full pipeline a later roadmap review sketched, which put a
Telemetry/State/Context foundation ahead of Forge for a real reason (an
LLM coding "blind," holding everything in its own context, was the
actual failure mode of the akasha-llm-orchestrator/akasha-forge attempts
this replaces). Building Forge first anyway was a deliberate, named
call, not an oversight — see DEV_NOTES.md.

Telemetry followed Forge — chosen deliberately as the next foundation
piece (not TUI, not Temporal) precisely because it has no dependencies
of its own and both of those genuinely benefit from it existing first:
a TUI showing "recent events" needs real events to show, and reasoning
about time is more grounded with a real event timeline to anchor to
than designed in the abstract.

The first organism-integration pass is now underway: Telemetry is wired
into the shared `organ_base.py` convention, so all twelve HTTP organs
automatically emit operational `request`, `mutation`, and `failure`
events without each organ growing its own telemetry implementation. The
shared client discovers Telemetry through the Registry and fails open for
observation only — an unavailable recorder never turns a successful organ
operation into a failure.

The remaining Telemetry work is causal propagation: existing organ-to-organ
HTTP calls do not yet consistently forward the originating correlation ID.
That is a tightening pass over existing call paths, not a new organ.

TUI and Temporal (Memory schema work — event_time/observation_time/
effective_from/effective_until, temporal relations) remain downstream work.
Temporal is still a reopening of Memory, not a new organ, and no Temporal
schema changes are being made in this pass.

TUI followed Telemetry. Its Telemetry tab was originally honest about an
empty recorder; after this integration pass it can now show real HTTP
activity from the organs. The dashboard itself remains read-only except
for its existing Input path, and its resilience tests still prove that
one unavailable organ cannot take the rest of the dashboard down.

Temporal is next. It's the biggest and riskiest of the three named at
the top of this section — reopening Memory, not adding a new organ —
and now has an actual reason to be more grounded than when this section
was written the first time: TUI gives a live event timeline (once
something's writing to Telemetry) to anchor "before/after/caused"
reasoning to, instead of designing it against an empty stats table.
