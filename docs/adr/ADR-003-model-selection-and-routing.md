# ADR-003: Vision Model Choice and LLM Tier Routing

**Status:** Accepted

## Decision
- Vision default: **YOLO11s TensorRT (FP16 -> INT8)**; ByteTrack + Kalman. RT-DETR benchmarked for
  comparison; Grounding DINO/OWL-ViT restricted to research spikes (too slow for fast path).
  Rationale: best FPS/accuracy/maturity on a modest local GPU; TensorRT export path well supported.
- LLM tiers: T1 flash-class (GLM-Flash / free endpoints) for all sub-agent execution; T2 free tier
  for heartbeats; T3 larger models only for escalations (2 failed T1 turns) and final shift
  synthesis. Routing via OpenAI-compatible base URL (OpenRouter/Z.ai/local vLLM) — compatible with
  prime-agent model configuration; per-incident budgets enforced by `--autonomous-*` flags.

## Consequences
+ Cents-per-incident economics; vendor-agnostic; vision upgrade path is a config change.
- Flash-class tool discipline is imperfect (markdown instead of executing REPL code): mitigated by
  strict harness policy, 2-strike escalation, and the Band-3 validation gate.
