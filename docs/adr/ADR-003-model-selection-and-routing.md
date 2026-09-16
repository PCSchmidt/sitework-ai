# ADR-003: Vision Model Choice and LLM Tier Routing

**Status:** Accepted

## Decision
- Vision baseline: **YOLO11n TensorRT FP16**; upgraded to **YOLO11s** (and INT8 quantization) only
  if the spike-00 GPU probe shows headroom — target hardware may be laptop-class. ByteTrack +
  Kalman. RT-DETR benchmarked for comparison; Grounding DINO/OWL-ViT restricted to research spikes
  (too slow for fast path). `forklift` (not a COCO class) is resolved by spike-02
  (YOLO-World open-vocab vs truck/bus proxy vs small fine-tune), measured on the demo clip in M1.
  Rationale: best FPS/accuracy/maturity on a modest local GPU; TensorRT export path well supported.
- LLM tiers: T1 flash-class (GLM-Flash / free endpoints) for all sub-agent execution; T2 free tier
  for heartbeats; T3 larger models only for escalations (2 failed T1 turns) and final shift
  synthesis. Routing via OpenAI-compatible base URL (OpenRouter/Z.ai/local vLLM) — compatible with
  prime-agent model configuration; per-incident budgets enforced by `--autonomous-*` flags.

## Consequences
+ Cents-per-incident economics; vendor-agnostic; vision upgrade path is a config change.
- Flash-class tool discipline is imperfect (markdown instead of executing REPL code): mitigated by
  strict harness policy, 2-strike escalation, and the Band-3 validation gate.
