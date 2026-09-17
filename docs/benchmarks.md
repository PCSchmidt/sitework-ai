# Benchmarks

`evaluation/benchmark_models.py` output, per docs/04 §5. This is the **v1 single-stream**
deliverable that closes the M1 exit criterion (docs/12-roadmap.md). The full matrix (multi-model
x multi-precision x multi-stream x accuracy) is an M5 deliverable and will replace/extend this
file.

## v1 — Single stream, FP32, imgsz 640 (M1 scope)

### Canonical numbers (spike-00, cool GPU, clean boot — 2026-09-16)

Recorded in `docs/spikes/spike-00-gpu-benchmark.md` / `docs/spikes/spike-00-results.jsonl`.

| Model | Clip | Resolution | FPS | p50 | p95 | VRAM peak |
| --- | --- | --- | --- | --- | --- | --- |
| YOLO11n | worker_walking_aisle | 3840x2160 (native) | 8.3 | 19.8 ms | 96.8 ms | 56 MB |
| YOLO11n | worker_walking_aisle_1080p | 1920x1080 | 36.0 | 13.3 ms | 16.7 ms | 56 MB |
| **YOLO11s** | worker_walking_aisle_1080p | 1920x1080 | **35.0** | 13.3 ms | 16.6 ms | 94 MB |
| YOLO11n | forklift_workers_interaction | 3840x2160 (native) | 22.3 | 14.5 ms | 17.2 ms | 56 MB |
| **YOLO11s** | excavator_site_01_1080p | 1920x1080 | **31.8** | 13.2 ms | 15.9 ms | 94 MB |

All 1080p single-stream results clear the S2 floor (>=25 FPS); native-4K decode is the bottleneck,
not the GPU (see spike-00 finding 1) — confirms the decision to serve demo clips pre-transcoded to
1080p.

### Supplementary run — sustained-load / thermal-limited (this session, 2026-09-16)

Same script and clips, re-run to fill the one cell spike-00 didn't cover
(YOLO11s x forklift_workers_interaction_1080p), plus a same-conditions pass for the other two
clips as a cross-check. GPU had been running the 3-container Docker vision stack continuously for
~2 hours immediately beforehand (chassis temp 88C at start, settling to ~74-77C idle — well above
the ~40-50C idle baseline a cold boot would show). Results:

| Model | Clip | Resolution | FPS | p50 | p95 | VRAM peak |
| --- | --- | --- | --- | --- | --- | --- |
| YOLO11n | worker_walking_aisle_1080p | 1920x1080 | 15.7 | 32.3 ms | 54.4 ms | 56 MB |
| YOLO11n | forklift_workers_interaction_1080p | 1920x1080 | 15.5 | 29.6 ms | 44.1 ms | 56 MB |
| YOLO11n | excavator_site_01_1080p | 1920x1080 | 14.6 | 30.7 ms | 78.0 ms | 56 MB |
| YOLO11s | worker_walking_aisle_1080p | 1920x1080 | 16.8 | 30.4 ms | 49.3 ms | 94 MB |
| **YOLO11s** | **forklift_workers_interaction_1080p** | 1920x1080 | **15.5** | 30.8 ms | 41.3 ms | 94 MB |
| YOLO11s | excavator_site_01_1080p | 1920x1080 | 15.2 | 28.0 ms | 53.3 ms | 94 MB |

**Finding (new, M2 input):** under sustained multi-hour load this Ampere laptop GPU throttles to
roughly **half** its clean-boot single-stream throughput (~35 -> ~16 FPS, p50 latency roughly
doubling) even fully idle for 90s beforehand and with utilization/VRAM far under its ceiling —
consistent with power/thermal limiting (WDDM laptop power cap), not compute contention. This still
clears a relaxed single-stream floor but would **not** clear the 3-stream S2 target (>=25 FPS/
stream) under sustained conditions. Action items carried to M2/M5:
- Budget for TensorRT FP16 export headroom (docs/04 §2, ~2x speedup) to absorb thermal derating,
  not just to hit the cold-boot S2 number.
- Record GPU temperature/power state alongside FPS in the M5 benchmark matrix (docs/04 §5) —
  "FPS on this GPU" is underspecified without a thermal/duty-cycle qualifier for laptop-class
  hardware.
- Any production sizing (docs/10 cost model, M6 Terraform) should assume server-class (desktop/
  cloud) GPUs with adequate sustained cooling, not laptop thermal envelopes.

## M1 exit checklist

- [x] 1 stream >= 25 FPS on sample clip (35.0 FPS, YOLO11s, worker_walking_aisle_1080p, spike-00)
- [x] Tracklets in Redis (verified end-to-end in Docker, commit d64c7fe: 3 GPU workers publishing
      valid TrackletFrames, person/person/heavy_vehicle on dock_north_01)
- [x] Benchmark table v1 (this file)
- [x] spike-00 / spike-02 recorded (`docs/spikes/spike-00-gpu-benchmark.md`,
      `docs/spikes/spike-02-forklift-class.md`)

**M1 is closed.** Proceeding to M2 (spatial layer: homography/calibration + rule engine).
