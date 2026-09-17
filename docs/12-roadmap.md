# 12 — Detailed Roadmap

Sequencing principle: every milestone ends in something demoable. Effort assumes ~10–15 h/week.

## M0 — Scaffolding (1 week)
- [ ] Repo skeleton per docs/07; `uv` envs, ruff/mypy/pytest configs, pnpm UI scaffold
- [ ] `docker-compose.yml`: mediamtx + redis + postgres + api (stub) + ui (stub) + vision (stub)
- [ ] CI: `ci.yaml` + `iac-check.yaml` (validate-only) green on empty pipelines
- [ ] `config/*.yaml` schemas + Pydantic settings validation (fail-fast loader)
- [ ] Pydantic v2 schemas for TrackletFrame/TriggerEvent + JSON Schema export
**Exit:** `make up` boots all containers; schema round-trip test green.

## M0.5 — Doc-consistency pass (2–3 days, blocks M1)
- [x] Resolve Band-3 tolerances (0.15 m / 0.2 m/s / 0.2 s / 5% rel) — single normative spec in docs/06 §3
- [x] Resolve vision baseline: YOLO11n until spike-00 probe; 11s is the upgrade target (ADR-003, docs/04)
- [x] Scope M3 to 2 sub-agents; watchdog/parameter-reviewer marked M5+ optional (docs/05)
- [x] Hard calibration gate defined: `valid = rms_px ≤ 2.0` (docs/04 §3, docs/06 §1)
- [x] Cost model: Scenario B total row, GCP Filestore caveat, heartbeat free-tier assumption (docs/10)
- [x] needs_review workflow defined (docs/05 §8)
- [ ] Consistency check script (`scripts/check_docs.py`): greps for tolerance strings, role counts,
      baseline model across PLAN/04/05/06/12 — green before M1 starts
**Exit:** check script green; no contradictory numbers across the doc suite.

## M1 — Perception core (2–3 weeks)
- [x] **Spike-00 (first 2 days):** GPU benchmark probe → `docs/spikes/spike-00-gpu-benchmark.md`;
      done 2026-09-16: RTX A4500 16 GB, YOLO11s adopted as default, 1080p transcode required,
      3-stream 22–26 FPS (TensorRT FP16 at M2 to clear S2)
- [x] **Spike-02 (parallel):** forklift-class options measured → `docs/spikes/spike-02-forklift-class.md`;
      decided: ship the truck/bus → heavy_vehicle proxy for M1–M4; real-frame fine-tune at M5
- [x] Dataset selection + `data/manifests/` (versions, licenses, SHA256) for the actual demo clips —
      done 2026-09-16: Mendeley machinery, HF warehouse, MOT17 mirror, Pexels demo set
      (see `docs/04-data-and-models.md` §1 for the verified source table)
- [x] Ingestion: MediaMTX MP4 looping; RTSP frame source (PyAV/GStreamer), decode benchmarks
- [x] `detector.py`: YOLO11s via Ultralytics → ONNX → TensorRT FP16 wrappers (11n fallback via config)
- [x] `tracker.py`: ByteTrack + per-track Kalman (position/velocity, covariance)
- [x] `pipeline.py`: decode→detect→track→TrackletFrame publisher (Redis XADD @10 Hz) — verified
      end-to-end in Docker 2026-09-16 (commit d64c7fe): 3 GPU workers, valid TrackletFrames in Redis
- [x] `evaluation/benchmark_models.py` v1 (single stream) — done 2026-09-16, see `docs/benchmarks.md`
**Exit:** 1 stream ≥ 25 FPS on sample clip; tracklets in Redis; benchmark table v1; spike-00/02 recorded.
**M1 CLOSED 2026-09-16** — see `docs/benchmarks.md` for the exit checklist.

## M2 — Spatial layer (2 weeks)
- [x] `geometry/homography.py` + `calibrate.py` manual calibration tool; quality metric (RMS) —
      done 2026-09-16: DLT solve + RMS reprojection gate (tests: test_homography.py,
      test_calibrate.py); CLI takes a point-correspondences JSON rather than interactive frame
      clicks (scriptable/testable — clicking is just one way to produce that file). Actual per-site
      `config/calibration/{camera_id}.json` files still need a human to pick real ground points
      against camera footage + site measurements — not yet run against real demo footage. Tried
      the demo clip directly (dock_north_01 flagship frame): its only clean reference geometry is
      two collinear wheel-contact points on one side of a forklift — not enough for a >=4-point,
      non-collinear DLT fit. Added a second calibration method for exactly this case —
      `pipelines/geometry/vanishing_point.py`: single-view metrology from vanishing points of
      structural parallel lines (roof trusses, wall-floor edges, a mast) instead of a clean
      reference object, with one required scale anchor (assumed camera height). 10 tests
      (`tests/test_vanishing_point.py`) verify a full synthetic-camera round trip, including a
      real sign ambiguity in the recovered axes (a vanishing point encodes a direction, not a
      signed ray) resolved by searching the 4 valid proper-rotation sign combinations.
      **Attempted against both `forklift_workers_interaction.mp4` and `worker_walking_aisle.mp4`
      preview frames (2026-09-17) — both inconclusive, honestly.** Forklift frame: clean lateral
      lines (wall/partition edges) were too close to parallel-in-image for a reliable vanishing
      point; a depth-direction pairing that gave a plausible-looking focal length turned out to
      combine two lines (a roof diagonal + a wall edge) with no verified reason to be parallel in
      3D — discarded rather than reported, since presenting it would manufacture false confidence,
      not measure anything. Aisle frame: strong lateral (shelf beam) and vertical (rack posts)
      lines, but no identifiable depth-direction line anywhere in the frame (checked floor joints,
      ceiling, adjacent rack bays — nothing usable). **Conclusion: neither stock clip has
      calibration-grade geometry for either method; this is a property of the footage (not
      composed for calibration), not a gap in the tooling, which is real and independently
      verified.**
      **Update 2026-09-17: real footage tried, real bug found and fixed, real end-to-end
      success.** A short deliberately-composed phone clip (a room corner, two baseboards
      meeting, floor, a rug — not a job site, just a space with visible orthogonal structure)
      exposed a genuine bug: `ground_homography_from_vanishing_points` rejected valid real-world
      line picks as "degenerate" because it demanded near-exact orthogonality (1e-3), which only
      synthetic test data ever satisfies. Fixed by projecting onto the nearest true rotation via
      SVD instead of rejecting (regression test: `test_ground_homography_tolerates_imprecise_real_world_line_picks`).
      `calibrate.py` now supports `--method vanishing_point` end-to-end (not just as a library),
      producing a real `config/calibration/dining_room_01.json` — which **fails** the hard RMS
      gate (`valid=false`, `rms_px≈105` vs `RMS_GATE_PX=2.0`; hand-picked lines from a phone photo
      aren't survey precision, an honest and expected result, not a bug). Using this real
      (gate-failing) calibration also surfaced and fixed a real pipeline gap: `pipeline.py` was
      disabling zone containment entirely whenever calibration was invalid, contradicting docs/04
      §3's "degrade to zone-only" design — only proximity/speed should require the hard gate.
      Fixed in `pipeline.py` + `rules.py` (3 new tests). End-to-end simulation with the real
      calibration confirms the intended behavior exactly: `zone_intrusion` fires correctly via
      `dining_room_test_zone`/`dining_room_test_intrusion` (new test-fixture camera/zone/rule,
      clearly marked as such, not a site demo), while `proximity`/`speed` correctly stay inert.
      Real per-camera calibration for the *actual* demo cameras (dock_north_01 etc.) still stays
      deferred — this fixture validates the tooling and the degrade-safely design against real
      data, it doesn't calibrate a real site.
- [x] Ground-plane projection + metric velocity; zone polygon engine (Shapely, precomputed) —
      `pipelines/geometry/zones.py` (ZoneEngine) + wired into `pipeline.py`: bottom-center bbox
      projected through H -> `ground_point_m`, finite-difference velocity/speed, zone containment
      populates `zone_ids`. Degrades to nulls/empty when no valid calibration exists (docs/04 §3).
- [x] Fast rule engine: zone_intrusion, proximity, dwell, speed (+ cooldown dedup) — done
      2026-09-16: `pipelines/vision/rules.py` (`RuleEngine`), 13 tests in `tests/test_rules.py`.
      `ppe_absence` and `wrong_way` are loaded but ignored (no PPE-classifying detector or
      lane-direction config yet); left for a later milestone.
- [x] TriggerEvent emission + evidence window capture (tracks.jsonl + clip segment) — done
      2026-09-17: `pipeline.py` runs every published TrackletFrame through `RuleEngine.process()`
      and XADDs results to the `trigger_events` Redis stream (fast path -> agent queue handoff).
      `pipelines/vision/evidence.py` (`EvidenceCapture`) keeps a rolling per-camera buffer of
      recent TrackletFrames + images; on a TriggerEvent it opens a
      `[trigger_ts - pre_window_s, trigger_ts + post_window_s]` window (defaults 5s/5s), and once
      the post-window closes writes `incidents/{event_id}/tracks.jsonl` (one TrackletFrame per
      line) and `incidents/{event_id}/clip.mp4` (H.264 via PyAV) — the exact paths already stamped
      onto `track_window_ref`/`clip_ref`. 7 tests in `tests/test_evidence.py`. Known simplification:
      buffers/clip run at the ~10 Hz publish cadence, not full decode-rate, to bound memory.
- [x] Broker hardening: streams, retention, consumer groups, replay tooling — done 2026-09-17:
      `pipelines/broker/streams.py` replaces the M1 count-based `XADD ... MAXLEN` trim with
      time-based `XTRIM ... MINID` (`trim_to_retention`, checked every 30s in `pipeline.py`) —
      `tracklets:{camera_id}` at 5 min retention, `trigger_events` at 1 h, matching docs/02 §2/§6
      (which previously said `telemetry.{camera_id}`/`triggers` — corrected to the actual stream
      keys). `ConsumerGroupReader` wraps XREADGROUP/XACK plus XAUTOCLAIM-based stale-pending
      reclaim, ready for the M3 agent worker to consume `trigger_events` reliably.
      `pipelines/broker/replay.py` dumps a stream's history (optionally since a timestamp) to
      JSONL via XRANGE, independent of consumer-group offsets, for backfill/local dev. 15 tests
      (`tests/test_broker_streams.py`, `tests/test_broker_replay.py`) using fakeredis, since no
      test elsewhere in the repo depends on a live Redis.
**M2 CLOSED 2026-09-17.** Remaining, not part of the M2 exit: real per-camera calibration data
(a human/on-site task, not code — see PLAN.md and the calibration tool's own docs); the
forklift-vs-worker proximity demo itself hasn't been run end-to-end against real footage since
that depends on the calibration data.
**Exit:** forklift-vs-worker proximity demo fires with metric distances on clip #1.

## M3 — Agent slow path (2–3 weeks)
- [x] **M3.0 Feasibility spike (2 days)** per docs/prime-agent-feasibility.md §5; recorded in
      `docs/spikes/spike-01-prime-agent-headless.md` — done 2026-09-17. **Verdict: Conditional
      GO** (ADR-005 updated). 5/5 golden-incident runs (4 local + 1 in the real built container)
      produced correct, schema-valid `result.json`, including unprompted Band-3-style discrepancy
      flagging. Session persistence confirmed across a hard kill. Two real gaps found, not
      fallback-triggers but binding on how `worker.py`/`Dockerfile.agent` get built: (1)
      `--autonomous-max-turns` did NOT stop a runaway task at 3x its limit — `worker.py` must add
      its own external subprocess timeout/kill, not trust the flag alone; (2) p50 triage ran
      82–96s in 2/3 timed runs vs the 60s target — budget 90–120s for flash-tier models. Also
      found and fixed for real: `Dockerfile.agent` as drafted didn't build (`prime-agent` isn't on
      the public npm registry, UID 1000 collision, Node version mismatch vs the package's actual
      `engines` requirement, a `curl | sh` silently swallowing a network failure) — see the spike
      doc for all four fixes. Not switching to `agent/worker_fallback.py`; the core mechanism
      works and was demonstrated repeatedly, including inside the actual container.
- [x] Seeded incident eval set (10 incidents with hand labels, grows to 30+ at M5) — done
      2026-09-17. `evaluation/build_seed_incidents.py` generates 10 hand-designed fixtures (6
      proximity, 2 zone_intrusion, 2 speed) covering near_miss/violation/normal_ops/false_positive
      plus one deliberate evidence-inconsistency case designed to make Band-3 reject regardless of
      the agent's answer; `evaluation/agent_eval.py` runs each through the real `AgentWorker`
      pipeline against the real `prime-agent` 0.9.3 CLI (not a mock) and scores validation pass
      rate + classification agreement. **Result: 10/10 validation pass, 9/9 classification
      agreement (the 10th is the gate-rejection fixture, correctly rejected), p50 75.6s / max
      96.0s** — full table and honest caveats (n=10 is small, synthetic tracklets not real
      footage) in `docs/eval-m3-agent-slow-path.md`. **M3's exit metric (validation pass ≥ 90%) is
      met.**
- [x] `Dockerfile.agent` (pinned prime-agent, Node 22 + Python 3.11 + uv, non-root) — built and
      verified working as part of the spike (see above); still owes a real private-registry fix
      before anyone but this machine can build it (`docker/vendor/README.md` has the interim
      vendoring steps and what the real fix looks like)
- [x] `agent/prime_adapter.py` (RPC JSON-lines driver) + `agent/worker.py` queue consumer — done
      2026-09-17. `PrimeAdapter.prompt()` enforces the external supervisory timeout spike-01
      Finding 4 required, via a background reader thread + `queue.Queue.get(timeout=)` rather than
      iterating `proc.stdout` directly — a plain iteration blocks indefinitely on a silent pipe,
      exactly the failure mode one spike run hit (20+ min hang, no events at all). `worker.py`
      pops `trigger_events` off a Redis consumer group (crash-safe reclaim via `claim_stale`),
      writes the incident payload files, prompts the trajectory-inspector role (proximity triggers
      get the pairwise-distance verification prompt spike-01 validated against the real CLI;
      zone_intrusion/speed triggers get a simpler single-track sanity-check prompt — there's no
      pairwise distance for those rule kinds), and gates the result through Band-3
      (`agent/band3.py`) before producing an `IncidentRecord`. Tested against a scripted stand-in
      `prime-agent` process (tests/_fake_prime_agent.py), not the real CLI — spike-01 already
      covered the real CLI's behavior; these tests cover the adapter/worker's own plumbing
      (timeout-and-kill, schema validation, Band-3 rejection, missing-evidence handling). Schema
      gap found and fixed along the way: `IncidentRecord` had no way to represent docs/05 §8's
      `state=needs_review` path (Postgres `incidents.state`/`rejection_reason` existed in docs/06
      §6 but not in the Pydantic model) — added `IncidentState` enum and `state`/
      `rejection_reason` fields, `classification`/`verified_kinematics` now `Optional`.
- [x] Harness sub-agent prompts: trajectory-inspector, generic classification (persisted as
      templates in `agent/prompts/`, filled per-incident by `worker.py`) — not yet registered as
      *harness* sub-agent specs (`agent/harness/`, prime-agent's own sub-agent mechanism per docs/05
      §2); current implementation drives one root session per incident with a role-specific prompt,
      which was what spike-01 actually tested. Promoting to real harness sub-agent specs is a
      follow-up, not blocking M3's exit criterion.
- [x] Band-3 gate: schema validation + recomputation cross-check per docs/06 §3 tolerances — done
      2026-09-17 (`agent/band3.py`), recomputes pairwise ground-distance from `tracks.jsonl` using
      the same math `RuleEngine._eval_proximity` uses, checked against both the fast path's claimed
      metrics and the agent's claimed verdict.
- [ ] Incident persistence (Postgres insert) + `agent_runs` observability — `worker.py` currently
      returns/logs `IncidentRecord`s; DB wiring lands with the dashboard work (M4). Not building
      `agent/worker_fallback.py` — spike-01's Conditional GO didn't trigger the fallback path.
- [x] `contract-agent.yaml` CI — done 2026-09-17, scoped honestly to what's actually possible:
      `prime-agent` still isn't installable in CI (private-registry gap, spike-01 Finding 1,
      unresolved), so this doesn't drive the live CLI. Instead `scripts/record_golden_session.py`
      captures a real RPC transcript (run manually, on a machine with the pinned version) into
      `tests/fixtures/golden_prime_agent_session.jsonl` (888 real events, captured 2026-09-17
      against 0.9.3); `tests/_fake_prime_agent.py`'s new `golden_replay` mode replays it
      byte-for-byte; `tests/test_contract_agent.py` asserts `PrimeAdapter` parses the real output
      shape correctly and the captured `result.json` still validates against `KinematicsVerdict`.
      Guards this repo's adapter code against regressions, not prime-agent's own protocol drift —
      re-run the recording script (and re-verify against the spike) whenever
      `PINNED_PRIME_AGENT_VERSION` bumps.
**Exit:** end-to-end: anomaly → verified incident in Postgres; validation pass ≥ 90% on the seeded
set; spike metrics recorded.

**M3 CLOSED 2026-09-17** except incident persistence (Postgres insert + `agent_runs`), which is
explicitly deferred to M4's dashboard/DB wiring rather than built standalone here — `worker.py`
already returns/logs full `IncidentRecord`s, so that's a storage-layer follow-up, not a gap in the
agent pipeline itself. Both the dispatcher (`agent/prime_adapter.py` + `agent/worker.py` + Band-3)
and the eval-set exit criterion are done and verified against the real `prime-agent` CLI, not
mocks.

## M4 — Delivery plane (2 weeks)
- [x] FastAPI REST + WS (telemetry ticker, incident push); asyncpg queries -- done 2026-09-17.
      `api/schema.sql` (`incidents`, `reviews`, `agent_runs`; a `NOTIFY`-emitting trigger on
      `incidents` for the WS push); `api/repository.py` (asyncpg queries, `IncidentRecord` is the
      wire format in both directions, no second driftable shape); `api/main.py` -- REST:
      `GET/POST /api/v1/incidents[/{event_id}][/review]`, `GET /api/v1/{cameras,zones,rules}`
      (served straight from `config/*.yaml`, not duplicated in Postgres), `GET /api/v1/kpis`; WS:
      `/live/ws` pushes `incident.created`/`incident.updated` via Postgres `LISTEN`/`NOTIFY`
      (the one mechanism that crosses the `agent/worker.py` <-> API process boundary without a
      second broker). `frame.ticker` (live track positions, docs/06 §5) is **not** wired yet --
      bridging Redis's per-camera tracklet streams to WS is real remaining work.
      `agent/persistence.py`'s `PostgresPersister` closes M3's explicitly-deferred DB item:
      `agent/worker.py` now writes every `IncidentRecord` (confirmed or needs_review) and its
      `agent_run` stats for real. Tested against a real local Postgres (11 API tests, 9 repository
      tests, 2 worker-persistence tests, all `@pytest.mark.integration`, skip cleanly without a DB
      via a fast TCP reachability pre-check; `ci.yaml` now runs a Postgres service container so
      they execute for real in CI, not just skip forever). Real bug caught before it shipped:
      `PostgresPersister.persist()` originally called `asyncio.run()` directly, which raises
      inside a caller that already has a running event loop (exactly what the integration test
      needed to also `await` DB reads) -- fixed by running in a dedicated thread.
- [x] `scripts/smoke_test.py` (docs/09 §6, S1) -- done 2026-09-17, for real: injects a synthetic
      `TriggerEvent` into the real `trigger_events` Redis stream, drives it through
      `AgentWorker` (agent stubbed via the same fake-CLI stand-in the test suite uses by default;
      `--real-agent` drives the actual CLI), asserts the confirmed incident lands in Postgres,
      and asserts the WS `incident.created` push is observed -- connecting the WS client *before*
      the trigger fires, since Postgres `NOTIFY` isn't queued for late listeners (a real ordering
      bug the first draft had, caught by actually running it, not by inspection).
      **Verified passing end-to-end**, including inside the actual built `Dockerfile.agent` +
      `Dockerfile.web` images (not just on the host): a container running `agent/worker.py`
      persisted a confirmed incident to a real Postgres, and a second container running the real
      FastAPI app served that exact row back over `GET /api/v1/incidents`.
- [x] `docker/Dockerfile.agent` + `docker/Dockerfile.web` updated to actually run the M4 code --
      done 2026-09-17. Two real gaps found and fixed along the way: (1) `agent/worker.py`
      transitively imported `pipelines.vision.pipeline` (torch/ultralytics, ~5 GB) just for two
      string constants (`TRIGGER_STREAM_KEY`/`STREAM_KEY_PREFIX`) -- moved them to
      `pipelines/broker/streams.py`, confirmed via `sys.modules` after `import agent.worker` that
      torch/ultralytics no longer load; `Dockerfile.agent` installs a small explicit package list
      (pydantic/pyyaml/redis/asyncpg) rather than `uv sync`-ing the full lockfile, matching the
      pattern `Dockerfile.vision`/`Dockerfile.web` already use. (2) `Dockerfile.agent` set
      `WORKDIR /workspace` before its `CMD ["python3", "-m", "agent.worker", ...]` -- `-m` resolves
      packages against the *current working directory*, so this broke with `ModuleNotFoundError`
      at runtime; fixed by keeping `WORKDIR /app` (where `agent/`/`pipelines/`/`api/` actually
      live) and passing `/workspace` only as the `--workspace-root` argument.
      `Dockerfile.web`'s pip-install list was still the M0 stub set (missing `asyncpg`,
      `websockets`) and would have failed to boot the real API -- fixed. `docker-compose.yml` gets
      a real `agent` service (mounts the host's `~/.prime` harness state, override via
      `PRIME_HARNESS_DIR`) and `api`'s `DATABASE_URL`.
- [ ] React dashboard: video+boxes overlay, 2D site canvas (tracks, zones), incident feed,
      **needs_review queue UI** (docs/05 §8) -- not started; needs visual/browser iteration a
      terminal-only session can't fully verify, scoped as separate follow-up work from the backend
      slice above
- [ ] Clip persistence on trigger + evidence viewer -- `EvidenceCapture` already writes
      `tracks.jsonl`/`clip.mp4` to disk per incident (M2); serving/viewing them through the API is
      what's still open
- [ ] Shift report rendering (md → styled HTML/PDF)
**Exit:** live demo of full loop on 3 simulated streams; S1 smoke test green. **S1 (smoke test) is
met** for the backend loop (broker -> worker -> Postgres -> WS, verified both on the host and
inside the real built containers); the "live demo" half of this exit criterion still needs the
dashboard to be a demo in the portfolio sense, not just a passing script.

## M5 — Evaluation & tuning (1–2 weeks)
- [ ] Benchmark matrix (2 models × 2 precisions × 1–3 streams on the spike-00 hardware; expand only
      if the probe shows headroom) + MOTA/IDF1 harness. Note in docs/benchmarks.md: >3–4 streams is
      an unvalidated extrapolation, not a measured claim.
- [ ] Expand seeded incident eval set to 30+ + agent metrics (pass rate, agreement, tokens, latency)
- [ ] Threshold calibration pass; `docs/benchmarks.md` publication
- [ ] Optional (per docs/05): stream watchdog + parameter reviewer sub-agents
**Exit:** S2 + S6 met; all published numbers reproducible via `make eval`.

## M6 — Reference architecture & portfolio polish (2 weeks)
- [ ] Terraform AWS environment realized from the existing PDF spec (modules + env), GCP + Azure envs
      (GCP env documents the Filestore/alternative decision from docs/10 §4)
- [ ] `iac-check.yaml` enforcing fmt+validate; runbook review pass; cost model finalize
- [ ] Simulated-live replay mode (fixtures → cloud backend) for the $0 public demo
- [ ] README narrative, ADR finalization, demo GIF/video, architecture diagrams (C4 + sequence)
- [ ] Helm chart explicitly descoped (stretch only, not part of M6 exit)
**Exit:** S5 met; public demo $0/mo; portfolio package complete.

## Ongoing habits
- Weekly: one merged demoable increment; keep `docs/spikes/` for any 1–2 day investigations.
- Red-team fixtures for prompt injection added alongside agent features (docs/08-security.md).
