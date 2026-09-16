# 11 — Risk Register

| # | Risk | P | Impact | Mitigation | Early warning |
| --- | --- | --- | --- | --- | --- |
| R1 | **Scope explosion** — 4 planes is a lot for one dev | High | Schedule slip | Milestone gating; M1–M3 = minimum viable story; each milestone demoable alone | Milestone > 1.5× estimate |
| R2 | **Dataset access/license drift** | Medium | Demo/eval gaps | **Occurred and resolved 2026-09-16:** S2TLD-Construction unverifiable, MOCS link dead, AI City 2025 T3 is VLM stills not tracklets, Macgence Kaggle is a marketing page. Actual pinned set: Mendeley rz8723t6d7 (CC BY 4.0), HF PhysicalAI Warehouse (CC-BY-4.0), MOT17 HF mirror, Pexels demo clips, Pictor-v3 — all under `data/manifests/` with hashes | Download failure / license ambiguity |
| R3 | **Prime Agent interface drift** between versions | Medium | Rework in `agent/` | Pin version; single adapter module; golden RPC contract test in CI (feasibility F1) | Contract test failure on bump |
| R4 | **Agent output unreliability** (hallucinated numbers, parse failures) | Medium | DB integrity, credibility | Band-3 recomputation gate; needs_review state; never auto-apply; eval metrics on 30-seed set | Validation pass rate < 90% |
| R5 | **Cost runaway** from autonomous loops | Medium | Budget | Hard turn/token/time flags; per-day incident budget; tier routing; escalation caps | tokens/incident trend up |
| R6 | **Homography accuracy** insufficient on real footage | Medium | Metric rules unreliable | Manual calib tool + hard RMS gate (`valid = rms_px ≤ 2.0`); document error bounds; metric rules degrade to zone-only when invalid | RMS > 2 px on test feeds |
| R7 | **GPU constraints locally** (VRAM, TensorRT friction) | Medium | Benchmark targets missed | Start YOLO11n FP16; INT8 later; CPU ONNX smoke path for CI; document hardware limits | < 25 FPS on 1 stream |
| R8 | **Security misconfig in agent container** | Low | Credibility | Container hardening checklist (docs/08-security.md); no cloud creds; egress allowlist | any egress beyond allowlist |
| R9 | **Prompt injection via payload strings** | Low | Agent misbehavior | Schema enums; escaping; harness policy (docs/08-security.md §4) | red-team fixture test |
| R10 | **Motivation/momentum** on long solo project | Medium | Project stall | Weekly demoable increments; public commit log; portfolio narrative per milestone | 2 weeks without merged milestone task |

## Rollback / Descope Positions

If time compresses, the project degrades gracefully in this order (each keeps a coherent story):

1. Drop multi-cloud Terraform to AWS-only (the PDF spec already exists).
2. Replace live agent path with replay-mode agent results (fixtures) — dashboard story intact.
3. Drop PPE classes (fine-tuning) — keep person/vehicle + spatial rules.
4. Drop tracking eval (MOTA/IDF1) — keep FPS/latency benchmarks.
