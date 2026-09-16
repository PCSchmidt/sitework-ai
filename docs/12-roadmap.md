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
- [ ] **Spike-00 (first 2 days):** GPU benchmark probe → `docs/spikes/spike-00-gpu-benchmark.md`;
      gates the S2 commitment and the YOLO11n→11s upgrade decision
- [ ] **Spike-02 (parallel):** forklift-class options measured on demo clip →
      `docs/spikes/spike-02-forklift-class.md`; decide YOLO-World vs proxy vs mini fine-tune
- [ ] Dataset selection + `data/manifests/` (versions, licenses, SHA256) for the actual demo clips;
      request AI City access early (approval latency)
- [ ] Ingestion: MediaMTX MP4 looping; RTSP frame source (PyAV/GStreamer), decode benchmarks
- [ ] `detector.py`: YOLO11n via Ultralytics → ONNX → TensorRT FP16 wrappers (11s/INT8 after spike-00)
- [ ] `tracker.py`: ByteTrack + per-track Kalman (position/velocity, covariance)
- [ ] `pipeline.py`: decode→detect→track→TrackletFrame publisher (Redis XADD @10 Hz)
- [ ] `evaluation/benchmark_models.py` v1 (single stream)
**Exit:** 1 stream ≥ 25 FPS on sample clip; tracklets in Redis; benchmark table v1; spike-00/02 recorded.

## M2 — Spatial layer (2 weeks)
- [ ] `geometry/homography.py` + `calibrate.py` manual calibration tool; quality metric (RMS)
- [ ] Ground-plane projection + metric velocity; zone polygon engine (Shapely, precomputed)
- [ ] Fast rule engine: zone_intrusion, proximity, dwell, speed (+ cooldown dedup)
- [ ] TriggerEvent emission + evidence window capture (tracks.jsonl + clip segment)
- [ ] Broker hardening: streams, retention, consumer groups, replay tooling
**Exit:** forklift-vs-worker proximity demo fires with metric distances on clip #1.

## M3 — Agent slow path (2–3 weeks)
- [ ] **M3.0 Feasibility spike (2 days)** per docs/prime-agent-feasibility.md §5; record in
      `docs/spikes/spike-01-prime-agent-headless.md`; explicit go/no-go: on fail, switch to
      `agent/worker_fallback.py` (LiteLLM) and M3 continues unchanged (ADR-005)
- [ ] Seeded incident eval set (~10 incidents with hand labels, grows to 30+ at M5) — created here
      so the M3 exit metric (validation pass ≥ 90%) is measurable
- [ ] `Dockerfile.agent` (pinned prime-agent, Node 20 + Python 3.11 + uv, non-root)
- [ ] `prime_adapter.py` (RPC JSON-lines driver) + `worker.py` queue consumer
- [ ] Harness sub-agent specs: trajectory-inspector, compliance-auditor (persisted in `agent/harness/`)
- [ ] Band-3 gate: schema validation + recomputation cross-check per docs/06 §3 tolerances
- [ ] Incident persistence + `agent_runs` observability + `agent/worker_fallback.py`
- [ ] `contract-agent.yaml` CI created immediately after the spike (the spike's golden session is
      the fixture); guards future prime-agent version bumps
**Exit:** end-to-end: anomaly → verified incident in Postgres; validation pass ≥ 90% on the seeded
set; spike metrics recorded.

## M4 — Delivery plane (2 weeks)
- [ ] FastAPI REST + WS (telemetry ticker, incident push); asyncpg queries
- [ ] React dashboard: video+boxes overlay, 2D site canvas (tracks, zones), incident feed,
      **needs_review queue UI** (docs/05 §8)
- [ ] Clip persistence on trigger + evidence viewer
- [ ] Shift report rendering (md → styled HTML/PDF)
**Exit:** live demo of full loop on 3 simulated streams; S1 smoke test green.

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
