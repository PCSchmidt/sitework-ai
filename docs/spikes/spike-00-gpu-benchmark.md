# Spike-00: GPU Benchmark Probe — RESULTS

**Status:** complete (2026-09-16) · **Owner:** solo dev · **Timebox:** 2 days → done in 1 session

## Hardware

| | |
| --- | --- |
| GPU | **NVIDIA RTX A4500 Laptop GPU** (Ampere, workstation) |
| VRAM | 16,384 MiB |
| Driver | 580.92 (CUDA 13.0 driver) |
| torch | 2.11.0+cu128 (CUDA-visible) |
| Detector | Ultralytics YOLO11, imgsz 640, batch 1 |

## Procedure

`evaluation/benchmark_models.py` (decode via PyAV + YOLO predict) on the three demo clips,
300 frames per run. Results appended to `docs/spikes/spike-00-results.jsonl` /
`spike-00-3stream-*.jsonl`.

## Results

### Single stream

| Model | Clip | Resolution | FPS | p50 | p95 | VRAM peak |
| --- | --- | --- | --- | --- | --- | --- |
| YOLO11n | worker_walking_aisle | 3840×2160 (native) | **8.3** | 19.8 ms | 96.8 ms | 56 MB |
| YOLO11n | worker_walking_aisle_1080p | 1920×1080 | **36.0** | 13.3 ms | 16.7 ms | 56 MB |
| **YOLO11s** | worker_walking_aisle_1080p | 1920×1080 | **35.0** | 13.3 ms | 16.6 ms | 94 MB |
| YOLO11n | forklift_workers_interaction | 3840×2160 (native) | 22.3 | 14.5 ms | 17.2 ms | 56 MB |
| YOLO11s | excavator_site_01_1080p | 1920×1080 | **31.8** | 13.2 ms | 15.9 ms | 94 MB |

### 3 concurrent streams (all YOLO11s, 1080p, separate processes)

| Stream | FPS | p50 |
| --- | --- | --- |
| worker_walking_aisle_1080p | 25.9 | 17.8 ms |
| forklift_workers_interaction_1080p | 23.0 | 18.3 ms |
| excavator_site_01_1080p | 22.4 | 18.5 ms |

## Findings

1. **Decode is the wall, not the GPU.** At native 4K, throughput collapses to 8–22 FPS while
   inference stays at p50 ~14–20 ms. At 1080p the GPU is barely loaded (56–94 MB VRAM peak).
   → **Demo clips are pre-transcoded to 1080p** (`assets/clips/*_1080p.mp4`); `make up` and
   `FrameSource` target 1080p, not native 4K.
2. **YOLO11s ≈ YOLO11n in speed at 1080p** (35.0 vs 36.0 FPS — both decode-bound) but 11s is
   meaningfully more accurate. → **Default detector is YOLO11s** (restores ADR-003's original
   choice; the 11n fallback stays available via config).
3. **3 concurrent streams land at 22–26 FPS**, right at the S2 boundary (≥25 FPS). GPU compute
   contention (p50 rises 13→18 ms under load) is the limiter.

## Decisions

- **S2:** kept as *≥3 concurrent streams at ≥25 FPS* but measured with **TensorRT FP16 export**
  (docs/04 §2: ~2× inference speedup). The PyTorch FP32 numbers above are the conservative floor;
  TensorRT is the production configuration and should lift the two sub-25 streams over the line.
  If TensorRT still yields < 25 FPS on any stream, S2 relaxes to 2 streams per PLAN.md §3 fallback.
- **Model:** YOLO11s FP16 TensorRT is the M2 default. INT8 evaluation stays on the M3 plan.
- **Follow-up task (M2):** `model.export(format="engine", half=True)` + benchmark rerun, recorded
  in `docs/benchmarks.md`.

## Later outcome (added 2026-09-26; the decisions above are left as written)

- The TensorRT FP16 export happened at **M5, not M2**: `tensorrt` wasn't actually installed
  until then. It delivered a 34–57% single-stream speedup, and 3 streams cleared 25 FPS (30.2 FPS
  min-stream) on an idle-recovered GPU but not under sustained thermal load (9.5–13.2 FPS/stream).
  Both results are published in docs/benchmarks.md.
- FP16 TensorRT is **not** the pipeline's runtime default: `pipeline.py` still loads the `.pt`
  weights, and only the benchmark harness loads `.engine` files.
- INT8 was never evaluated at any milestone.
