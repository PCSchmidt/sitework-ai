# 11 — Risk Register

| # | Risk | P | Impact | Mitigation | Early warning |
| --- | --- | --- | --- | --- | --- |
| R1 | **Scope explosion** — 4 planes is a lot for one dev | High | Schedule slip | Milestone gating; M1–M3 = minimum viable story; each milestone demoable alone | Milestone > 1.5× estimate |
| R2 | **Dataset access/license drift** | Medium | Demo/eval gaps | **Occurred and resolved 2026-09-16:** S2TLD-Construction unverifiable, MOCS link dead, AI City 2025 T3 is VLM stills not tracklets, Macgence Kaggle is a marketing page. Actual pinned set: Mendeley rz8723t6d7 (CC BY 4.0), HF PhysicalAI Warehouse (CC-BY-4.0), MOT17 HF mirror, Pexels demo clips, Pictor-v3 — all under `data/manifests/` with hashes | Download failure / license ambiguity |
| R3 | **Prime Agent interface drift** between versions | Medium | Rework in `agent/` | Pin version; single adapter module; golden RPC contract test in CI (feasibility F1) | Contract test failure on bump |
| R4 | **Agent output unreliability** (hallucinated numbers, parse failures) | Medium | DB integrity, credibility | Band-3 recomputation gate (`agent/band3.py`); needs_review state; never auto-apply; eval metrics on the seeded set (10 at M3, 30 at M5) | **The early-warning threshold fired at M5, and the cause was real but different from what this risk describes:** raw validation pass dropped to 26/30 (86.7%, below 90%) on the expanded set (2026-09-18) -- but all 4 misses were the identical external timeout (`PrimeAgentTimeout`), not a hallucination/parse failure; retested and all 4 completed correctly (48-65s) once the timeout was raised on that evidence (150s → 210s). Classification agreement held at 23/28 (82.1%, clears its 80% target). Net: Band-3/schema reliability itself wasn't the problem this time, but the early-warning mechanism worked exactly as designed -- see `docs/eval-m5-agent-slow-path.md` for the full account, `docs/eval-m3-agent-slow-path.md` for the earlier 10/10 baseline |
| R5 | **Cost runaway** from autonomous loops | Medium | Budget | Per-day incident budget; tier routing; escalation caps; **`PrimeAdapter`'s own external wall-clock timeout+kill** (`agent/prime_adapter.py`) -- spike-01 Finding 4 found `--autonomous-max-turns`/`-max-tokens` alone did NOT stop a runaway task (9 turns/130s+ against a max-turns-3 limit), so those flags are defense-in-depth, not the actual backstop | tokens/incident trend up; any `PrimeAgentTimeout` in worker logs |
| R6 | **Homography accuracy** insufficient on real footage | Medium | Metric rules unreliable | Manual calib tool + hard RMS gate (`valid = rms_px ≤ 2.0`); document error bounds; metric rules degrade to zone-only when invalid | RMS > 2 px on test feeds |
| R7 | **GPU constraints locally** (VRAM, TensorRT friction) | Medium | Benchmark targets missed | **Probed 2026-09-16 (spike-00):** RTX A4500 16 GB; YOLO11s @ 35 FPS 1080p single-stream, 22–26 FPS 3-stream; decode is the wall, not the GPU. **TensorRT FP16 landed at M5, not M2 as originally planned** (a real doc/reality gap the M5 pass closed -- `tensorrt` was never actually installed until then) -- measured result is genuinely mixed, not a clean "lifts it over 25 FPS": 3-stream FP16 hits 30.2 FPS min-stream under idle-recovered conditions (clears S2) but only 9.5-13.2 FPS/stream under sustained thermal load (doesn't) -- both published in `docs/benchmarks.md`, since production sizing needs the worst case | 3-stream TensorRT rerun < 25 FPS under sustained load (S2 fallback: 2 streams, or server-class GPU for production sizing) |
| R8 | **Security misconfig in agent container** | Low | Credibility | Container hardening checklist (docs/08-security.md); no cloud creds; egress allowlist | any egress beyond allowlist |
| R9 | **Prompt injection via payload strings** | Low | Agent misbehavior | Schema enums; escaping; harness policy (docs/08-security.md §4) | red-team fixture test |
| R10 | **Motivation/momentum** on long solo project | Medium | Project stall | Weekly demoable increments; public commit log; portfolio narrative per milestone | 2 weeks without merged milestone task |

## Rollback / Descope Positions

If time compresses, the project degrades gracefully in this order (each keeps a coherent story):

1. Drop multi-cloud Terraform to AWS-only (the PDF spec already exists).
2. Replace live agent path with replay-mode agent results (fixtures) — dashboard story intact.
3. Drop PPE classes (fine-tuning) — keep person/vehicle + spatial rules.
4. Drop tracking eval (MOTA/IDF1) — keep FPS/latency benchmarks.
