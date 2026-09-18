# 12 — Detailed Roadmap

Sequencing principle: every milestone ends in something demoable. Effort assumes ~10–15 h/week.

## M0 — Scaffolding (1 week)
- [x] Repo skeleton per docs/07; `uv` envs, ruff/mypy/pytest configs, UI scaffold -- originally
      planned as a pnpm scaffold; the `pnpm-workspace.yaml` drafted here was never actually filled
      in and silently broke the `ci` workflow's `ui` job on every push from this point through M5
      (`docker-compose.yml`'s `ui` service had always used npm in practice) -- found and fixed as
      part of M6's doc-alignment pass, see that entry below
- [x] `docker-compose.yml`: mediamtx + redis + postgres + api (stub) + ui (stub) + vision (stub)
- [x] CI: `ci.yaml` + `iac-check.yaml` (validate-only) green on empty pipelines -- `ci.yaml` was
      not actually green from here through M5 (see above); `iac-check.yaml` existed but wasn't
      exercised against real Terraform until M6 (see that entry)
- [x] `config/*.yaml` schemas + Pydantic settings validation (fail-fast loader)
- [x] Pydantic v2 schemas for TrackletFrame/TriggerEvent + JSON Schema export
**Exit:** `make up` boots all containers; schema round-trip test green.
**M0 CLOSED 2026-09-16** (per PLAN.md's milestone table and every later milestone building on it);
these checkboxes were left unchecked at the time and are corrected here retroactively, not backdated
as newly-done work.

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
      **Update 2026-09-18 (found via M6's replay-mode push breaking CI, not by inspection):**
      that resolution was incomplete -- in two stages, both caught by actually running CI, not by
      inspection. First pass: the 4 valid candidates were picked by smallest reconstructed distance
      from the origin alone, which is mathematically blind to a *global* point-reflection
      (`‖(x,y)‖ == ‖(-x,-y)‖` for any x,y, always) -- so on every calibration, not just this
      fixture, which sign combination won was decided by sub-ulp floating-point noise: green
      locally (Windows), wrong sign on GitHub Actions' Linux runner. An initial fix added an
      exact, non-heuristic "reference pixel must reconstruct in front of the camera" depth check --
      genuinely correct, but only for *one* of the two independent sign ambiguities here (which way
      is "up"); it still failed the exact same way in CI, because the *other* ambiguity (which way
      is "positive" in the ground plane's own X/Y -- a 180-degree in-plane rotation about the now-
      fixed vertical axis) leaves every camera-observable fact, including that depth check,
      identical, so it still can't be resolved from `ground_reference_px` alone. Real fix:
      `ground_homography_from_vanishing_points`/`calibrate_from_vanishing_points` now take a new
      required `ground_reference_expected_xy` -- an operator's own *rough* real-world estimate of
      where the reference pixel sits (same role as `camera_height_m`: an assumed anchor, not a
      measurement) -- and disambiguate against that instead of the origin, which is mathematically
      capable of breaking a reflection tie. Verified the fix is robust, not just "happens to pass
      again": the two physically-valid candidates now separate by a real ~4.5x margin in
      reconstruction error (1.12 vs 5.02), not a sub-ulp tie. `pipelines/geometry/calibrate.py`'s
      `--lines` JSON schema, the real `config/calibration/dining_room_01.lines.json` fixture, and
      all call sites updated for the new required field. Regression test:
      `test_ground_homography_sign_disambiguation_not_decided_by_a_symmetric_tie`.
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
- [x] React dashboard: incident feed with live WS updates, **needs_review queue UI** (docs/05 §8,
      state filter + review-decision form posting to `/review`), KPI bar, evidence viewer (clip
      player + tracks.jsonl link), shift-report link -- done 2026-09-17.
      `ui/src/hooks/useLiveIncidents.ts` loads via REST then keeps the feed live over `/live/ws`,
      reconnecting with backoff and a REST re-fetch on drop (the WS server has no replay, so a
      reconnect alone would silently miss anything pushed during the gap). **Not built**: the
      video+boxes overlay and 2D site canvas from the original scope -- both need `frame.ticker`
      (live track positions over WS), which docs/06 §5 already flags as unwired; this pass only
      covers what the current incident-only push actually supports. **Verification note**: no
      in-session browser/screenshot tool was available, so this wasn't eyeballed in an actual
      browser. What *was* verified for real: `tsc -b` and `vite build` both clean; the built
      `docker-api` image restarted with the new code and its new endpoints curl-tested directly;
      the `ui` dev container restarted with the new `vite.config.ts` proxy and its `/api/v1/*`,
      `/healthz`, and `/live/ws` routes round-tripped through the exact same proxy path (including
      the incident-push WS message) a browser would use, via a raw Postgres UPDATE while a
      websockets client held the proxied connection open.
- [x] Clip persistence + evidence viewer -- done 2026-09-17. `EvidenceCapture` already wrote
      `tracks.jsonl`/`clip.mp4` to `{workspace_root}/incidents/{event_id}/` (M2); what was missing
      was serving them. `docker-compose.yml` now mounts the same `agent_workspace` volume
      read-only into the `api` service (`WORKSPACE_ROOT=/workspace`); `api/main.py` adds
      `GET /api/v1/incidents/{event_id}/evidence/{tracks,clip}` (`tracks` returns parsed JSON
      frames, `clip` streams `clip.mp4` via `FileResponse`, both 404 cleanly when the file doesn't
      exist -- e.g. every needs_review case where the agent step never ran). `event_id` is
      regex-validated before it reaches a filesystem path (`^[A-Za-z0-9_.-]+$`) -- a real
      path-traversal guard, not just a stylistic check, verified with a `..%2F..%2Fetc` request
      against the live container (404, not a directory listing).
- [x] Shift report rendering (md → styled HTML) -- done 2026-09-17, scoped honestly: `api/reports.py`
      renders the incidents in a window (`GET /api/v1/shift-report?from_ts=&to_ts=`) to one styled
      HTML page, using each incident's own `narrative_md`/`recommended_actions` -- **not** a new
      T3-synthesized cross-incident summary (that's a separate agent prompt/eval pair, out of scope
      here). No PDF export step; a browser's own "Print to PDF" on the HTML is the interim path.
      Pure-function renderer (`tests/test_reports.py`, incl. an HTML-escaping/XSS test for
      `narrative_md`), plus an integration test asserting the live endpoint serves it.
**Exit:** live demo of full loop on 3 simulated streams; S1 smoke test green. **Both are now met**:
S1 was closed in the backend pass above; the dashboard now gives the loop a real portfolio-demo
surface (live incident feed, needs_review queue with a working review action, evidence playback,
shift report) rather than just a passing script -- with the video-overlay/2D-canvas piece honestly
deferred pending `frame.ticker`, and browser-visual QA honestly deferred pending a browser tool in
a future session.

## M5 — Evaluation & tuning (1–2 weeks)
- [x] Benchmark matrix (2 models × 2 precisions × 1-3 streams) + MOTA/IDF1 harness -- done
      2026-09-18, `docs/benchmarks.md`. Real gap closed along the way: the M1/M2 roadmap had
      checked off a TensorRT FP16 export path that never actually existed (`detector.py` only
      loaded plain `.pt` weights; `tensorrt` wasn't installed) -- installed it for real
      (`tensorrt` 11.3.0.99 + `nvidia-modelopt[onnx]`) and exported working FP16 engines rather
      than substituting an FP16-autocast proxy. Single-stream: TensorRT is a real 34-57% win, both
      models converging to ~36.4-36.5 FPS (confirms decode is the 1080p bottleneck once inference
      is fast enough). Multi-stream: an **honest negative result** -- S2 (≥3 streams ≥25 FPS) is
      not met today even with TensorRT (9.5-13.2 FPS/stream at 3 streams), because the GPU was
      already under over an hour of continuous sustained load by then (`sm_clock` collapsed to
      210-315 MHz, confirmed via thermal snapshots now recorded on every benchmark row) -- a more
      severe instance of the throttling M2's supplementary run already flagged, not a code
      regression; 2-stream FP16 TensorRT (24.6 FPS min-stream) is the closest approach to the S2
      floor. MOTA/IDF1: real run against 3 MOT17 sequences, honest low scores (0.16-0.46 MOTA)
      explained (generic COCO detector, no MOT17 fine-tuning, crowd-density mismatch with this
      project's actual demo scenes) rather than hidden.
- [x] Expand seeded incident eval set to 30 + agent metrics (pass rate, agreement, tokens, latency)
      -- done 2026-09-18. 20 new fixtures target the classifier's exact numeric boundaries
      (near_miss `<2.0m`, violation `<1.0m`) and multi-track distractor scenes. Raw validation pass
      rate came in at 26/30 = 86.7%, below the 90% target -- but all 4 failures were the identical
      150s external timeout, not a capability failure (see next item). Classification agreement
      23/28 = 82.1%, clears its 80% target on the raw number. `evaluation/agent_eval.py` now also
      aggregates tokens/incident from `IncidentRecord.agent_run` (closes the "not yet aggregated"
      gap M3 left open) -- added after this run started, so no real token numbers yet; next run
      will have them. Full writeup: `docs/eval-m5-agent-slow-path.md`.
- [x] Threshold calibration pass -- done 2026-09-18, evidence-based not guessed: re-ran the 4
      timed-out fixtures with a longer timeout and all 4 completed correctly in 48-65s, proving
      the 150s ceiling was genuinely too tight (real run-to-run LLM latency variance, not a stuck
      agent). `agent/prime_adapter.py`'s `DEFAULT_TIMEOUT_S` raised 150s → 210s (~2x the highest
      max ever observed, 96.0s at M3), propagated to `evaluation/agent_eval.py` and
      `scripts/smoke_test.py`. Timeout-adjusted (what this eval set scores with the new default):
      30/30 = 100% validation pass, 27/28 = 96.4% classification agreement. `docs/benchmarks.md`
      publication -- done (both sections above).
- [ ] Optional (per docs/05): stream watchdog + parameter reviewer sub-agents -- still optional,
      not started
**Exit:** S6 met for the deterministic layers (benchmark/tracking harnesses reproduce their
published numbers headlessly via `make eval` / `make tracking-eval`, CPU- or GPU-portable);
`make agent-eval`'s reproducibility stays CLI-availability-gated (prime-agent's private-registry
gap, unchanged from M3, docs/12 M3 notes) -- a pre-existing, separately-tracked limitation, not a
new M5 gap. **S2 is met**, confirmed 2026-09-19 with an idle-recovered-GPU rerun of the multi-stream
matrix (`docs/benchmarks.md`): 3-stream FP16 TensorRT reaches 30.2 FPS min-stream, clearing the
≥25 FPS floor. The original sustained-load run (9.5-13.2 FPS/stream at 3 streams) is kept published
alongside it, not replaced by it -- production sizing (docs/10 cost model, M6 Terraform) should use
the sustained-load number, since that's the actual production duty cycle, not the best-case one.

**M5 CLOSED 2026-09-19.**

## M6 — Reference architecture & portfolio polish (2 weeks)
- [x] Terraform AWS environment realized from the existing PDF spec (modules + env), GCP + Azure envs
      (GCP env documents the Filestore/alternative decision from docs/10 §4) -- done 2026-09-19.
      AWS ported from the repo-root PDF spec's own file layout
      (variables/sqs/efs/security_iam/main/outputs.tf); GCP and Azure ported from
      docs/deployment/{gcp,azure}-deployment-guide.md §3's inline HCL. Real bugs caught by
      actually running `terraform validate` against real provider schemas, not by inspection:
      GCP's push subscription referenced an undefined `google_service_account.run_invoker`
      (added it); Azure's Service Bus namespace name ended in the reserved "-sb" suffix (renamed);
      `azurerm_storage_share` has no `protocol` argument, the real one is `enabled_protocol`
      (fixed, verified against the provider's own schema); PostgreSQL Flexible Server's required
      `administrator_login`/`administrator_password` were missing from the guide's illustrative
      snippet (added, password has no default). All three fixes landed in both the `.tf` files
      and the source markdown guides, not just the code. `deploy/terraform/modules/README.md`
      updated to document a real decision -- no shared cross-cloud module layer, since AWS/GCP/
      Azure's primitives don't share Terraform resource schemas closely enough to warrant one.
- [x] `iac-check.yaml` enforcing fmt+validate -- already existed from M0, now actually exercised
      for real: downloaded terraform 1.9.8 locally and ran the exact fmt-check/init/validate
      sequence the CI workflow runs, for all three environments; all green.
- [x] Runbook review pass; cost model finalize -- done 2026-09-19. Runbooks: GCP/Azure guides
      referenced a nonexistent `services/` directory for Docker builds (fixed to the real
      `docker/Dockerfile.{agent,web}` paths); AWS guide referenced a `scripts/smoke_test_telemetry.py`
      that was never built (replaced with an honest note + a real manual `aws sqs send-message`
      verification); AWS's architecture table promised Aurora + S3 that the PDF-sourced Terraform
      never included (added `db.tf`/`s3.tf` for real 3-cloud parity). Cost model: corrected a real
      inaccuracy -- Aurora Serverless v2 and GCP Cloud SQL both have no true pause/scale-to-zero
      (only Serverless v1, which doesn't support Postgres in most regions, could do that); Scenario
      A's idle/mo figures revised from ~$5-15 (implicitly assumed a free DB) to ~$50-65/~$55-75/
      ~$20-40 across AWS/GCP/Azure. See `docs/10-cost-model.md` §4 for the reasoning.
- [x] Simulated-live replay mode (fixtures → cloud backend) for the $0 public demo -- done
      2026-09-18. `scripts/replay_demo.py` loops the 30 M5 seeded fixtures
      (`evaluation/fixtures/incidents/`) into the real Postgres/API/WS path with no GPU vision
      container and no LLM call in the loop -- the two components that cost real money to run
      continuously. Honest by construction, not just by convention: `classification`/`state` are
      each fixture's own hand-labeled ground truth (`expected.json` -- the same labels M3/M5's real
      agent-eval runs scored against), `narrative_md` is a `[REPLAY DEMO]`-tagged deterministic
      template (never to be confused with a real agent narrative), and for proximity fixtures
      `verified_kinematics` is genuine recomputation -- `agent.band3.recompute_kinematics` replays
      the actual captured `tracks.jsonl` through the same pairwise-distance math the Band-3 gate
      itself uses, not a copied-through number (verified: `evt_seed_violation_01`'s replayed
      min-distance is 0.70 m, matching the fixture's seeded metric exactly, because it's the same
      computation, not a coincidence). `agent_run` reports `model="replay-mode (no LLM call)"`,
      tokens=0 -- so existing observability doesn't miscount these as real agent invocations.
      `docker/Dockerfile.replay` is deliberately not `Dockerfile.agent`: pure Python
      (pydantic/pyyaml/asyncpg only), no Node/prime-agent -- sidestepping prime-agent's still-open
      private-registry gap (docs/12 M3 notes) entirely for the public-demo path.
      `docker/docker-compose.replay.yml` is a standalone compose file (postgres + api + ui +
      replay, no mediamtx/vision-\*/agent), not an override -- compose has no clean "omit this
      service" verb. Two real bugs found and fixed by actually running the stack, not by
      inspection: (1) no explicit `name:` meant it defaulted to the same project name as
      `docker-compose.yml` (both files live in `docker/`) and a live test **recreated the main
      dev stack's `postgres` container** on shared container/network names -- fixed with an
      explicit `name: sitework-replay-demo`; (2) `depends_on: [postgres]` alone only waits for the
      container to *start*, not for Postgres to accept connections or for `api`'s own
      `init_schema` to have run yet -- a live test hit both races for real (`api` and `replay` both
      crashed with `ConnectionRefusedError` on first boot, then `replay` crashed again with
      `UndefinedTableError: relation "incidents" does not exist` once Postgres was up but before
      `api`'s schema-creating startup had finished) -- fixed with a `postgres` healthcheck
      (`pg_isready`) and an `api` healthcheck (`/healthz`, which only returns 200 once its
      lifespan's `init_schema` has completed), with `depends_on: condition: service_healthy`
      gating both `api` (on postgres) and `replay` (on api). Re-verified clean after the fix:
      `docker compose up` brings all three up in the correct order, `GET /api/v1/incidents`
      serves real replayed records, and the evidence viewer (`GET .../evidence/tracks`) round-trips
      the staged `tracks.jsonl`. `make replay-up`/`make replay-down` added.
- [ ] README narrative, ADR finalization, demo GIF/video, architecture diagrams (C4 + sequence)
- [ ] Helm chart explicitly descoped (stretch only, not part of M6 exit)
**Exit:** S5 met; public demo $0/mo; portfolio package complete.

## Ongoing habits
- Weekly: one merged demoable increment; keep `docs/spikes/` for any 1–2 day investigations.
- Red-team fixtures for prompt injection added alongside agent features (docs/08-security.md).
