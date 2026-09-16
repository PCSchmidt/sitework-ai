# 12 — Detailed Roadmap

Sequencing principle: every milestone ends in something demoable. Effort assumes ~10–15 h/week.

## M0 — Scaffolding (1 week)
- [ ] Repo skeleton per docs/07; `uv` envs, ruff/mypy/pytest configs, pnpm UI scaffold
- [ ] `docker-compose.yml`: mediamtx + redis + postgres + api (stub) + ui (stub) + vision (stub)
- [ ] CI: `ci.yaml` + `iac-check.yaml` (validate-only) green on empty pipelines
- [ ] `config/*.yaml` schemas + Pydantic settings validation (fail-fast loader)
- [ ] Pydantic v2 schemas for TrackletFrame/TriggerEvent + JSON Schema export
**Exit:** `make up` boots all containers; schema round-trip test green.

## M1 — Perception core (2–3 weeks)
- [ ] Ingestion: MediaMTX MP4 looping; RTSP frame source (PyAV/GStreamer), decode benchmarks
- [ ] `detector.py`: YOLO11s via Ultralytics → ONNX → TensorRT FP16/INT8 wrappers
- [ ] `tracker.py`: ByteTrack + per-track Kalman (position/velocity, covariance)
- [ ] `pipeline.py`: decode→detect→track→TrackletFrame publisher (Redis XADD @10 Hz)
- [ ] `evaluation/benchmark_models.py` v1 (single stream)
**Exit:** 1 stream ≥ 25 FPS on sample clip; tracklets in Redis; benchmark table v1.

## M2 — Spatial layer (2 weeks)
- [ ] `geometry/homography.py` + `calibrate.py` manual calibration tool; quality metric (RMS)
- [ ] Ground-plane projection + metric velocity; zone polygon engine (Shapely, precomputed)
- [ ] Fast rule engine: zone_intrusion, proximity, dwell, speed (+ cooldown dedup)
- [ ] TriggerEvent emission + evidence window capture (tracks.jsonl + clip segment)
- [ ] Broker hardening: streams, retention, consumer groups, replay tooling
**Exit:** forklift-vs-worker proximity demo fires with metric distances on clip #1.

## M3 — Agent slow path (2–3 weeks)
- [ ] **M3.0 Feasibility spike (2 days)** per docs/prime-agent-feasibility.md §5; record in
      `docs/spikes/spike-01-prime-agent-headless.md`; decide RPC vs fallback (ADR-005)
- [ ] `Dockerfile.agent` (pinned prime-agent, Node 20 + Python 3.11 + uv, non-root)
- [ ] `prime_adapter.py` (RPC JSON-lines driver) + `worker.py` queue consumer
- [ ] Harness sub-agent specs: trajectory-inspector, compliance-auditor (persisted in `agent/harness/`)
- [ ] Band-3 gate: schema validation + metric recomputation cross-check
- [ ] Incident persistence + `agent_runs` observability + `agent/worker_fallback.py`
**Exit:** end-to-end: anomaly → verified incident in Postgres; validation pass ≥ 90%; spike metrics recorded.

## M4 — Delivery plane (2 weeks)
- [ ] FastAPI REST + WS (telemetry ticker, incident push); asyncpg queries
- [ ] React dashboard: video+boxes overlay, 2D site canvas (tracks, zones), incident feed, review UI
- [ ] Clip persistence on trigger + evidence viewer
- [ ] Shift report rendering (md → styled HTML/PDF)
**Exit:** live demo of full loop on 3 simulated streams; S1 smoke test green.

## M5 — Evaluation & tuning (1–2 weeks)
- [ ] Full benchmark matrix (models × precision × 1–4 streams) + MOTA/IDF1 harness
- [ ] 30-seed incident eval set + agent metrics (pass rate, agreement, tokens, latency)
- [ ] Threshold calibration pass; `docs/benchmarks.md` publication
**Exit:** S2 + S6 met; all published numbers reproducible via `make eval`.

## M6 — Reference architecture & portfolio polish (2 weeks)
- [ ] Terraform AWS environment realized from the existing PDF spec (modules + env), GCP + Azure envs
- [ ] `iac-check.yaml` enforcing fmt+validate; runbook review pass; cost model finalize
- [ ] Simulated-live replay mode (fixtures → cloud backend) for the $0 public demo
- [ ] README narrative, ADR finalization, demo GIF/video, architecture diagrams (C4 + sequence)
**Exit:** S5 met; public demo $0/mo; portfolio package complete.

## Ongoing habits
- Weekly: one merged demoable increment; keep `docs/spikes/` for any 1–2 day investigations.
- Red-team fixtures for prompt injection added alongside agent features (docs/08-security.md).
