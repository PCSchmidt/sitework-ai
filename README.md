# SiteWatch AI — hybrid deterministic/probabilistic industrial safety intelligence

**Status: active development, no live deployment.** This is a local-stack portfolio
project — `make up` runs the full system (camera simulation, detection/tracking, rule
engine, agent, API, dashboard scaffolding) on your machine via Docker Compose; there is
no hosted demo URL and none is planned (ADR-004: documentation-only cloud deployment —
three fully-specified Terraform stacks for AWS/GCP/Azure exist and validate in CI, but
none is applied to a live account). **M0–M3 are closed; M4 (the delivery plane: REST +
WS API, React dashboard) is next.** Live status: [docs/12-roadmap.md](docs/12-roadmap.md).

## What is this? (plain-language overview)

SiteWatch AI answers an operational question warehouses and construction sites actually
have: *is a worker about to be hit by a forklift, has someone entered an exclusion zone
too long, is a vehicle over the site speed limit — and when something ambiguous happens,
what actually occurred?* It watches simulated camera feeds (MP4 clips looped as RTSP),
detects and tracks people and vehicles, projects every detection onto a metric ground
plane, and evaluates deterministic spatial safety rules in real time. Only the anomalies
that pass those rules go to an LLM agent, which re-verifies the kinematics by executing
code against the raw tracklet data — not by re-describing what the fast path already
claimed — before anything is recorded as a confirmed incident.

The architectural idea — and the portfolio centerpiece — is the **dual-plane split**:

> Fast path (deterministic, ≤100ms/frame, zero LLM cost): decode → YOLO11 detect →
> ByteTrack → Kalman → homography → Shapely zone/rule engine → `TriggerEvent`.
> Slow path (event-driven, seconds): a containerized agent worker re-derives the claimed
> kinematics from the same raw data and either confirms the incident or flags it for
> human review — it never trusts the fast path's numbers without checking them.

The thing that makes it more than "YOLO plus an LLM wrapper":

- **A hard, machine-checked boundary between the two planes.** Every value that crosses
  from vision code to the agent is a Pydantic v2 schema (`pipelines/schemas/models.py`) —
  `TrackletFrame`, `TriggerEvent`, `KinematicsVerdict`, `IncidentRecord`. Calibration has
  a hard numeric gate (`rms_px ≤ 2.0`, docs/04 §3): a camera that fails it doesn't get
  approximate metric rules, it degrades to zone-only geofencing rather than silently
  reporting wrong distances.
- **A recomputation gate the agent cannot talk its way past (Band-3).** `agent/band3.py`
  independently recomputes min-distance/closing-velocity from the stored tracklet window
  using the same math the fast path used, and rejects the incident — `state=needs_review`,
  raw evidence retained, nothing silently dropped — if either the fast path's own claim or
  the agent's verified answer falls outside tolerance (docs/06 §3).
- **The agent's own budget flags turned out not to be enough, so the code doesn't trust
  them alone.** A real feasibility spike found `--autonomous-max-turns` did not stop a
  runaway task (9 turns / 130+s against a limit of 3) — `agent/prime_adapter.py`'s
  external wall-clock timeout, not the CLI flag, is what actually enforces the budget.
  That's the kind of finding this project is built to surface and document, not hide.
- **Real per-camera calibration, done honestly.** Both calibration methods (point-
  correspondence homography and single-view-metrology from vanishing points) are
  validated against real phone footage, not just synthetic fixtures — including catching
  and fixing two real bugs (a vanishing-point sign ambiguity, an overly strict rotation
  tolerance) that only showed up on noisy real-world data.

| | |
| --- | --- |
| Deployment | Local only, `docker compose up` (mediamtx + redis + postgres + api + vision workers + agent) |
| Fast path | YOLO11s (Ultralytics) + ByteTrack, homography/vanishing-point calibration, Shapely zone engine, deterministic rule engine (proximity, zone-dwell, speed) |
| Slow path | [Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent) — Prime Intellect's open-source [RLM](https://www.primeintellect.ai/blog/rlm) (Recursive Language Model) agent — driven headless over a JSON-lines RPC protocol; per-incident trajectory-verification prompt; Band-3 recomputation gate |
| Broker | Redis Streams, time-based retention (`XTRIM MINID`), consumer groups for crash-safe agent consumption |
| Schemas | Pydantic v2, single source of truth, JSON Schema exported for a future TS dashboard |
| Benchmark (M1) | YOLO11s @ 35 FPS single-stream 1080p on an RTX A4500 (spike-00); thermal-throttle finding recorded honestly alongside the clean number |
| Agent eval (M3) | 10 hand-labeled incidents run against the real `prime-agent` CLI: **10/10 validation pass, 9/9 classification agreement**, p50 75.6s — [docs/eval-m3-agent-slow-path.md](docs/eval-m3-agent-slow-path.md) |
| Tests | 112 passing, offline where possible (`uv run pytest`); a golden-session contract test replays a real captured agent RPC transcript so CI doesn't need the (currently non-public) `prime-agent` package |
| Honest scope | portfolio project; simulated camera feeds (looped demo clips, not live cameras); real per-camera calibration for the three named demo cameras is still open — only a personal-footage fixture has been calibrated end-to-end so far |

## Architecture at a glance

```mermaid
flowchart TD
    SRC["MediaMTX<br>looped demo clips as simulated RTSP cameras"] --> DET
    subgraph fast["Fast path — deterministic, every frame, zero LLM cost"]
        DET["YOLO11s detector<br>+ ByteTrack / Kalman tracker"] --> GEOM["pipelines/geometry<br>homography / vanishing-point calibration"]
        GEOM --> RULES["Shapely zone engine + RuleEngine<br>proximity · zone_intrusion · speed"]
    end
    RULES --> BROKER[("Redis Streams<br>tracklets · trigger_events")]
    RULES --> EVID["EvidenceCapture<br>tracks.jsonl + clip.mp4"]
    BROKER --> WORKER
    subgraph slow["Slow path — event-driven, on trigger only"]
        WORKER["agent/worker.py<br>consumer-group queue dispatcher"] --> ADAPTER["agent/prime_adapter.py<br>RPC driver, external timeout+kill"]
        ADAPTER --> PA["Prime Agent (RLM)<br>verifies kinematics via code execution"]
        PA --> GATE["agent/band3.py<br>independent recomputation cross-check"]
    end
    GATE --> REC[("IncidentRecord<br>confirmed / needs_review")]
```

Where things live:

| Path | What it is |
| --- | --- |
| `pipelines/ingestion/` | MP4→RTSP simulation config (MediaMTX), frame source |
| `pipelines/vision/` | `detector.py`, tracker, `rules.py` (the fast-path rule engine), `pipeline.py` (frame loop), `evidence.py` (trigger evidence capture) |
| `pipelines/geometry/` | `homography.py` (DLT point-correspondence), `vanishing_point.py` (single-view metrology), `calibrate.py` (CLI tool, both methods), `zones.py` |
| `pipelines/broker/` | Redis Streams retention (`XTRIM MINID`) + consumer-group hardening, replay tooling |
| `pipelines/schemas/` | Pydantic v2 single source of truth for everything crossing the fast/slow boundary |
| `agent/worker.py` | Queue dispatcher: pops `TriggerEvent`s, writes incident payload files, drives the agent, applies the Band-3 gate |
| `agent/prime_adapter.py` | The only module allowed to invoke `prime-agent`; external wall-clock timeout+kill on every prompt |
| `agent/band3.py` | Recomputation cross-check gate (docs/06 §3) |
| `agent/prompts/` | Per-incident prompt templates (trajectory verification, generic classification) |
| `evaluation/` | `build_seed_incidents.py` + `agent_eval.py` (the M3 agent eval set/runner), `benchmark_models.py` (fast-path FPS/latency/VRAM) |
| `api/`, `ui/` | FastAPI + React — M0 scaffolding today; the real REST/WS surface and dashboard land at M4 |
| `config/` | `cameras.yaml`, `zones.yaml`, `rules.yaml` — the deterministic rule configuration |
| `docs/` | The full design suite: architecture, schemas, security, cost model, risk register, ADRs, spike reports |
| `tests/` | 112 tests: schema round-trips, rule-engine known-answer tests, calibration math, broker hardening, agent/adapter plumbing against a scripted stand-in, and the golden-session contract replay |
| `.github/workflows/` | `ci.yaml` (lint/type/test/schema-compat), `contract-agent.yaml` (golden RPC replay), `iac-check.yaml` (`terraform validate` for all three clouds, never applied) |

## Quickstart

Requires Docker, [uv](https://docs.astral.sh/uv/) (Python 3.11+), and — only if you want
to run the real agent slow path, not just the fast path — a working local install of
[`prime-agent`](https://github.com/PrimeIntellect-ai/prime-agent) (not yet on the public
npm registry; see `docker/vendor/README.md` for the current vendoring workaround).

```bash
git clone https://github.com/PCSchmidt/sitework-ai
cd sitework-ai
uv sync
uv run pytest              # 112 tests, offline

make up                    # docker compose up --build: full local stack,
                            # simulated camera feeds, no credentials needed
make calib                 # launch the manual camera-calibration CLI
make agent-eval             # run the seeded incident set against the real prime-agent CLI
```

## Approach: why it is built this way

- **Deterministic first, LLM only on ambiguity.** Every safety-critical alert (proximity,
  zone dwell, speed) fires from documented, versioned geometric math — zero LLM cost, zero
  hallucination surface. The agent only ever runs on triggers the deterministic layer
  already raised, and re-derives its own answer from raw data rather than trusting the
  trigger's summary.
- **The gate is structural, not prompted.** `agent/band3.py` doesn't ask the model to
  double-check itself — it independently recomputes the same numbers from `tracks.jsonl`
  and compares both the fast path's claim and the agent's claim against that recompute.
  Either one drifting outside tolerance rejects the incident to `needs_review`.
- **Calibration has a hard numeric floor, and degrades honestly.** `rms_px ≤ 2.0` is not a
  suggestion — a camera that fails it keeps zone-intrusion detection (geometric
  containment tolerates imprecision) but proximity/speed rules that need real metric
  distance go inert rather than reporting a number nobody verified.
- **Real footage before real cameras.** Rather than guess at calibration math against
  synthetic data alone, both calibration methods were run against actual phone footage —
  which caught two real implementation bugs synthetic tests hadn't surfaced (see
  `docs/12-roadmap.md`'s M2 notes).
- **The agent's own safety rails were tested, not assumed.** A dedicated feasibility spike
  (`docs/spikes/spike-01-prime-agent-headless.md`) found a real gap in `prime-agent`'s own
  budget-enforcement flags and changed the design in response — external timeout
  ownership moved into `agent/prime_adapter.py` rather than staying a documentation
  assumption.
- **Everything that can be tested against the real system, is.** The M3 agent eval set
  runs against the actual `prime-agent` CLI (not a mock); the CI contract test replays a
  real captured RPC transcript rather than a synthetic one, because `prime-agent` isn't
  installable in CI yet (see Limitations).

## Motivation

Warehouse and construction-site safety systems either stop at "an alert fired" — no
verification, no audit trail, no explanation of what actually happened — or they route
everything through an LLM and inherit its unreliability for decisions that matter. This
project is a demonstration of the middle path: keep the safety-critical layer
deterministic and auditable, and use a reasoning agent only where judgment is genuinely
needed (was this really a near-miss? does the claimed kinematics hold up?) — with a
recomputation gate the agent cannot bypass no matter how confident it sounds.

**This is a portfolio project.** All camera feeds are looped demo clips, not live site
cameras; the cloud deployment story (ADR-004) is documentation-and-Terraform-only, never
applied to a live account.

## Method (what the pipeline actually does)

1. **Ingest.** MediaMTX loops pinned demo clips as RTSP streams, one per simulated camera
   (`config/cameras.yaml`).
2. **Detect and track.** YOLO11s detects people/vehicles per frame; ByteTrack + a Kalman
   filter maintain per-camera track identity and state.
3. **Project to the ground plane.** If a calibration exists for the camera
   (`pipelines/geometry/calibrate.py`, either point-correspondence or vanishing-point
   method), each track's bottom-center pixel is projected to `ground_point_m` through the
   homography; zone membership (`pipelines/geometry/zones.py`, Shapely) is computed
   whenever *any* calibration exists — metric velocity/speed only when it clears the hard
   RMS gate.
4. **Evaluate deterministic rules.** `pipelines/vision/rules.py`'s `RuleEngine` evaluates
   proximity (pairwise distance + duration + closing speed), zone_intrusion (dwell timer),
   and speed (instantaneous, zone-gated) rules with cooldown-based dedup, and emits a
   `TriggerEvent` on any rule condition holding for its configured threshold.
5. **Capture evidence.** `pipelines/vision/evidence.py` keeps a rolling buffer of recent
   `TrackletFrame`s and, on a trigger, writes the pre/post-trigger window to
   `tracks.jsonl` + `clip.mp4` — exactly the data the slow path re-verifies against.
6. **Dispatch to the agent.** `agent/worker.py` pops the `TriggerEvent` off a Redis
   consumer group (crash-safe: an unacked entry gets reclaimed, never silently dropped),
   writes the incident payload files, and drives one `prime-agent` RPC session with a
   role-specific prompt — pairwise-distance verification for proximity triggers, a
   simpler sanity-check prompt for zone/speed triggers.
7. **Verify, don't trust.** The agent must execute real code against `tracks.jsonl` to
   answer — no eyeballing, no estimating — and writes `result.json` (`KinematicsVerdict`
   schema). `agent/band3.py` independently recomputes the same numbers and rejects on
   mismatch against either the fast path's or the agent's claim.
8. **Record.** Pass → `IncidentRecord` with `state=confirmed`. Fail (schema-invalid,
   Band-3 mismatch, agent timeout/crash) → `state=needs_review`, `rejection_reason` set,
   raw evidence retained for a human reviewer — never a silently dropped or fabricated
   classification. Postgres persistence + dashboard surfacing land at M4.

## Results

All numbers are reproducible from this repo:

- **M1 (fast-path benchmark):** YOLO11s clears the ≥25 FPS single-stream floor at 1080p
  (**35.0 FPS**, RTX A4500) — both a clean-boot number and a thermal-throttled number
  (15–17 FPS after 2 hours of contended GPU load) are recorded, because hiding the
  discrepancy would be dishonest and the throttling finding is itself useful for hardware
  sizing (`docs/benchmarks.md`).
- **M2 (spatial layer):** rule engine, evidence capture, and broker hardening validated
  by 94 tests at close, including real (not just synthetic) calibration data from actual
  phone footage — which caught two real bugs: a vanishing-point sign ambiguity and an
  overly-strict rotation tolerance that rejected valid noisy real-world line picks.
- **M3 (agent slow path), measured 2026-09-17:** 10 hand-designed incidents run against
  the real `prime-agent` 0.9.3 CLI (proximity, zone-intrusion, and speed rule kinds, plus
  one fixture deliberately designed to make the recomputation gate reject regardless of
  the agent's answer) — **10/10 validation pass, 9/9 classification agreement, p50 triage
  latency 75.6s, max 96.0s.** Full table and honest caveats:
  [docs/eval-m3-agent-slow-path.md](docs/eval-m3-agent-slow-path.md).
- **112 tests pass** (`uv run pytest`), ruff and mypy clean on `pipelines/` and `agent/`.

## Limitations

- **No live deployment, and none is planned as a hosted demo.** This is a local-stack
  project by design (ADR-004); three complete Terraform stacks (AWS/GCP/Azure) exist and
  validate in CI (`terraform fmt -check` + `validate`, never `apply`) as reference
  architecture, not a running service.
- **Real per-camera calibration for the three named demo cameras (dock/yard/warehouse) is
  still open.** Both calibration methods are validated end-to-end against real footage of
  a personal test fixture, not the actual demo camera angles — that's a genuine,
  unresolved gap, not a documentation nit.
- **`prime-agent` isn't installable in CI yet.** It isn't on the public npm registry
  (`"private": true` in its own `package.json`); `Dockerfile.agent` uses a vendored
  tarball as an interim (`docker/vendor/README.md`), and the CI contract test replays a
  real captured transcript rather than driving the live CLI. A private registry (GitHub
  Packages) with build-time auth is the real fix, still owed.
- **The M3 eval set is small (n=10).** It exercises all three rule kinds and both the
  confirm and reject paths, but 10 synthetic fixtures is not a statistically tight
  estimate; it grows to 30+ at M5 per the testing strategy (docs/09 §3).
- **The delivery plane doesn't exist yet.** `api/` and `ui/` are M0 scaffolding stubs
  (`/healthz` and empty list routes); the real REST+WS API, React dashboard, and
  Postgres-backed incident persistence are M4 scope.
- **PPE detection (helmet/vest) isn't built.** The schema has fields for it
  (`PPEState`); the fine-tuned classifier lands at M5 alongside the full benchmark
  matrix.
- **Agent budget flags alone are not a trustworthy ceiling** — documented, not hidden:
  spike-01 found `--autonomous-max-turns` did not stop a runaway task, so
  `agent/prime_adapter.py`'s own external timeout is the real backstop, and any future
  agent-driving code in this repo needs the same discipline.

## Operational notes

### What actually runs where

| Component | Runs as | Notes |
| --- | --- | --- |
| `mediamtx` | Docker Compose service | Loops pinned demo clips as RTSP (simulated cameras) |
| `redis` | Docker Compose service | Streams broker: `tracklets:{camera}` (5 min retention), `trigger_events` (1 h retention, consumer groups) |
| `postgres` | Docker Compose service | Schema exists in docs/06 §6; incident writes land at M4 |
| `vision-*` workers | Docker Compose service, one per camera, GPU passthrough | `pipelines.vision.pipeline`, YOLO11s + ByteTrack |
| `agent/worker.py` | Not yet containerized as a standing service | `docker/Dockerfile.agent` builds and runs `prime-agent --mode rpc`; runnable locally today via `uv run python -m agent.worker` against a running Redis |
| `api` (FastAPI) | Docker Compose service | M0 stub (`/healthz` only) until M4 |

### Data and keys

| Variable | Purpose |
| --- | --- |
| `REDIS_URL` | broker connection (`pipelines/vision/pipeline.py`, `agent/worker.py`); defaults to `redis://localhost:6379` |
| `YOLO_WEIGHTS` | override the detector weights path; defaults to `yolo11s.pt` |
| — | `prime-agent`'s own model/API auth (OpenRouter) is configured through its own persistent harness state (`~/.prime/`), not a `sitework-ai` environment variable |

No cloud credentials are used anywhere in this repo's runtime path — the Terraform in
`deploy/` is validated, never applied (ADR-004).

### Verify the claims (a reviewer's path)

```bash
uv run pytest -q                          # 112 tests, offline
uv run ruff check . && uv run mypy        # lint + types (pipelines/, agent/)
uv run python scripts/check_docs.py       # cross-doc consistency gate
uv run python -m evaluation.agent_eval    # re-run the M3 seeded eval (needs prime-agent installed)
make up                                   # full local stack, simulated feeds
curl -s http://localhost:8000/healthz     # API stub liveness
```

### Documentation map

| Doc | What it covers |
| --- | --- |
| [PLAN.md](PLAN.md) | The master plan: scope, milestones, success criteria |
| [docs/01](docs/01-vision-and-scope.md)–[06](docs/06-schemas-and-api.md) | Vision/scope, system architecture, hybrid design, data/models, agent orchestration, schemas+API |
| [docs/07-repo-layout.md](docs/07-repo-layout.md) | Repo layout, conventions, CI workflows, Makefile targets |
| [docs/08-security.md](docs/08-security.md) | Container hardening, secrets, prompt-injection posture |
| [docs/09-testing-and-evaluation.md](docs/09-testing-and-evaluation.md) | Test pyramid, known-answer tests, agent eval methodology |
| [docs/10-cost-model.md](docs/10-cost-model.md) | LLM spend mechanics, measured vs. estimated cost |
| [docs/11-risks.md](docs/11-risks.md) | Risk register with measured outcomes, not just guesses |
| [docs/12-roadmap.md](docs/12-roadmap.md) | Live milestone status — the actual source of truth for "what's done" |
| [docs/benchmarks.md](docs/benchmarks.md) | M1 fast-path FPS/latency/VRAM numbers |
| [docs/eval-m3-agent-slow-path.md](docs/eval-m3-agent-slow-path.md) | M3 agent eval results, run against the real CLI |
| [docs/prime-agent-feasibility.md](docs/prime-agent-feasibility.md) | The feasibility analysis behind embedding Prime Agent as a runtime component |
| [docs/spikes/](docs/spikes/) | Time-boxed de-risking spikes (GPU benchmark, forklift class, Prime Agent headless) with honest results |
| [docs/adr/](docs/adr/) | Architecture decision records |
| [docs/deployment/](docs/deployment/) | AWS/GCP/Azure reference deployment guides (documentation-only, ADR-004) |

## Engineering context

The slow-path agent is a containerized deployment of **[Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent)**, Prime Intellect's open-source agent built on their **[RLM](https://www.primeintellect.ai/blog/rlm) (Recursive Language Model)** idea: instead of stuffing everything into one model's context window, an RLM keeps its own reasoning lean and manages a persistent Python REPL plus recursive calls to sub-LLMs to do the heavy lifting — exactly the shape this project needed for an incident verifier that must *compute* an answer (execute code against the raw tracklet window) rather than *guess* one from a prompt. `agent/prime_adapter.py` is the only module in this repo allowed to invoke it, wrapped in an external timeout the feasibility spike showed was necessary regardless of the CLI's own budget flags — see [docs/prime-agent-feasibility.md](docs/prime-agent-feasibility.md) for the full verified-capability writeup and [docs/spikes/spike-01-prime-agent-headless.md](docs/spikes/spike-01-prime-agent-headless.md) for the honest results of actually running it headless.

## License

[MIT](LICENSE).

## Author

**Paul Christopher Schmidt** — [@PCSchmidt](https://github.com/PCSchmidt)
