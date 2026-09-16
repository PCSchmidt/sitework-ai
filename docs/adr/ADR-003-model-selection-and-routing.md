# ADR-003: Vision Model Choice and LLM Tier Routing

**Status:** Accepted

## Decision
- Vision default: **YOLO11s** (TensorRT FP16 from M2). Settled by spike-00 (2026-09-16): on the
  RTX A4500 at 1080p, 11s matches 11n throughput (35.0 vs 36.0 FPS — both decode-bound) with better
  accuracy, so the larger model is free. 11n remains available via config. ByteTrack + Kalman.
  RT-DETR benchmarked for comparison; Grounding DINO/OWL-ViT restricted to research spikes
  (too slow for fast path).
- Forklift class (not in COCO): **ships as the truck/bus → heavy_vehicle proxy for M1–M4.**
  spike-02 (2026-09-16) measured all three options — YOLO-World open-vocab scored 0% recall, a
  synthetic-only fine-tune failed sim2real (0/304 detections on real footage), and the proxy fires
  on every frame of the real interaction clip. True `forklift` class via real-frame fine-tune is
  deferred to M5 (docs/spikes/spike-02-forklift-class.md).
  Rationale: best FPS/accuracy/maturity on a modest local GPU; TensorRT export path well supported.
- LLM tiers: T1 flash-class (GLM-Flash / free endpoints) for all sub-agent execution; T2 free tier
  for heartbeats; T3 larger models only for escalations (2 failed T1 turns) and final shift
  synthesis. Routing via OpenAI-compatible base URL (OpenRouter/Z.ai/local vLLM) — compatible with
  prime-agent model configuration; per-incident budgets enforced by `--autonomous-*` flags.

## Consequences
+ Cents-per-incident economics; vendor-agnostic; vision upgrade path is a config change.
- Flash-class tool discipline is imperfect (markdown instead of executing REPL code): mitigated by
  strict harness policy, 2-strike escalation, and the Band-3 validation gate.
