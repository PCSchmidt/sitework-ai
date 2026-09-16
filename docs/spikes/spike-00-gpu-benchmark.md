# Spike-00: GPU Benchmark Probe

**Status:** planned (first 2 days of M1) · **Owner:** solo dev · **Timebox:** 2 days

## Purpose

Success criterion S2 (≥3 streams @ ≥25 FPS) and the YOLO11n→11s upgrade decision depend on the
actual local GPU. This spike measures it before any commitment is made.

## Procedure

1. Record hardware: GPU model, VRAM, driver, CUDA, TensorRT versions (`nvidia-smi`, `pip list`).
2. Run `evaluation/benchmark_models.py` v1 against one demo clip:
   - YOLO11n FP16, batch 1: FPS, p50/p95 latency, peak VRAM.
   - YOLO11s FP16, batch 1: same.
   - If single-stream FPS ≥ 60: try 2 and 3 concurrent processes/streams.
3. Record results in the table below.

## Results (fill in during M1)

| Model | Precision | Streams | FPS/stream | Latency p50/p95 | VRAM peak |
| --- | --- | --- | --- | --- | --- |
| YOLO11n | FP16 | 1 | | | |
| YOLO11s | FP16 | 1 | | | |
| YOLO11n | FP16 | 3 | | | |

**Hardware:** _TBD_

## Decision rules

- 3 streams @ ≥25 FPS with YOLO11n → S2 stands as written; upgrade to 11s if 11s also meets it.
- 2 streams only → S2 relaxed to 2 streams (per PLAN.md §3 fallback); stay on YOLO11n.
- < 25 FPS single stream → trigger risk R7: drop to smaller input resolution before descoping.
