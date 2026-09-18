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

## M5 — Precision × stream matrix (2026-09-18)

Scoped per docs/12-roadmap.md M5 item 1 (2 models × 2 precisions × 1-3 streams, "expand only if
the probe shows headroom" -- not docs/04 §5's full aspirational matrix with 11m/RT-DETR/INT8/mAP,
which stays out of scope here). Raw rows: `docs/benchmarks-m5.jsonl` (`evaluation/benchmark_models.py`).

**Real gap closed:** the M1/M2 roadmap checkboxes claimed a TensorRT FP16 export path existed
("`detector.py`: YOLO11s via Ultralytics → ONNX → TensorRT FP16 wrappers") -- checking the actual
code, it never did; `detector.py` only ever loaded plain `.pt` weights, and `tensorrt` wasn't
installed. Closed for real this session: installed `tensorrt` (11.3.0.99, matches the CUDA 13.0
driver) + `nvidia-modelopt[onnx]` (needed by Ultralytics' export path, not obvious from the docs),
exported real FP16 engines (`data/models/yolo11{n,s}.engine`, not committed -- gitignored,
machine/driver-version-specific artifacts). First export attempt failed on a Windows file-lock
(`Access is denied` removing a DLL mid-`uv pip install`); reran cleanly with the two installs
separated. Both exports succeeded end-to-end, no fallback to an FP16-autocast proxy needed.

### Single stream, imgsz 640, 1080p (worker_walking_aisle) -- FP32 (.pt) vs FP16 TensorRT (.engine)

GPU already warm/sustained-load at the start of this run (86-89°C, per the thermal-throttling
finding above), **not** a clean-boot measurement -- these are the honest floor, not spike-00's
best-case numbers.

| Model | Precision | FPS | p50 | p95 | VRAM peak* |
| --- | --- | --- | --- | --- | --- |
| YOLO11n | FP32 | 27.2 | 18.0 ms | 25.5 ms | 56 MB |
| YOLO11n | **FP16 TensorRT** | **36.4** (+34%) | 9.1 ms | 15.8 ms | 18 MB* |
| YOLO11s | FP32 | 23.3 | 20.7 ms | 44.0 ms | 94 MB |
| YOLO11s | **FP16 TensorRT** | **36.5** (+57%) | 9.4 ms | 16.0 ms | 18 MB* |

*\*VRAM peak for the `.engine` rows is `torch.cuda.max_memory_allocated()`, which only sees
PyTorch's own allocator -- TensorRT manages its activation/weight memory separately, so 18 MB
understates real usage. TensorRT's own build log reports actual context memory: ~95 MB (11n),
~142 MB (11s). Recorded as a known measurement gap rather than presented as a real 5x VRAM win,
which it isn't.*

**Finding:** TensorRT FP16 is a real, substantial single-stream win (34-57%), and both models
converge to ~36.4-36.5 FPS -- confirms spike-00's finding 1 that decode, not inference, is the
1080p bottleneck; once inference gets fast enough, the ceiling is the same for both models.

### Multi-stream, YOLO11s (the shipped default), 3 different 1080p clips, one OS process/stream

| Streams | Precision | Aggregate FPS | Per-stream FPS | Min-stream FPS | S2 (≥25 FPS/stream)? |
| --- | --- | --- | --- | --- | --- |
| 2 | FP32 | 32.0 | 21.9 / 20.0 | 20.0 | ✗ |
| 2 | FP16 TensorRT | 37.4 | 28.5 / 24.6 | 24.6 | ✗ (just under) |
| 3 | FP32 | 25.3 | 10.2 / 10.0 / 9.5 | 9.5 | ✗ |
| 3 | FP16 TensorRT | 28.0 | 13.2 / 11.0 / 10.9 | 10.9 | ✗ |

**Finding, and an honest negative result: S2 is not met today, even with TensorRT.** The 3-stream
numbers here (9.5-13.2 FPS/stream) are *worse* than spike-00's original FP32 3-stream measurement
(22-26 FPS, 2026-09-16) -- not a regression in the code, a difference in GPU thermal state. By the
time these multi-stream cells ran, the GPU had already been under continuous heavy load for over
an hour this session (TensorRT engine compilation, the single-stream matrix above); `sm_clock_mhz`
collapsed to 210-315 MHz by the end of each 3-stream run (vs. a 930 MHz nominal boost clock seen
earlier in the same session) -- a hard power/thermal clamp, confirmed by the
`gpu_thermal_before`/`gpu_thermal_after` snapshots in `docs/benchmarks-m5.jsonl`, not a code
regression. This is consistent with, and a more severe instance of, the throttling behavior the M2
supplementary run already documented above (~2x clean-boot-vs-sustained slowdown there; closer to
3-4x here under even longer sustained load plus 3 concurrent CUDA contexts instead of 1).
TensorRT still helps at every cell (+17% aggregate at 3 streams, +7% min-stream at 2 streams) --
it just isn't enough to overcome this specific laptop's thermal/power ceiling once three separate
processes are all issuing CUDA calls at once.

**Per PLAN.md §3's own fallback ("2 streams if the probe shows laptop-class hardware"): 2-stream
FP16 TensorRT (24.6 FPS min-stream) is the closest this hardware gets to the S2 floor, still just
short of it under today's sustained-load conditions.** Action items (carried forward, not
resolved here):

- Re-run this matrix after a genuine cold boot (not attempted this session -- would have meant
  discarding the single-stream comparison's already-hot GPU state, and re-establishing it is a
  separate session's work) to get a best-case reading alongside this worst-case one.
- docs/benchmarks.md's existing recommendation stands and is reinforced, not contradicted:
  production sizing (docs/10 cost model, M6 Terraform) should assume server-class GPUs with real
  sustained cooling. This laptop is a development/benchmarking rig, not the target deployment
  profile, and these numbers should not be read as "SiteWatch AI needs N GPUs" without that
  caveat.

## Tracking accuracy — MOTA/IDF1 on MOT17 (2026-09-18)

`evaluation/eval_tracking.py` (docs/09 §4): runs the real `Detector` + Ultralytics ByteTrack call
`pipelines/vision/pipeline.py` makes (not a separate tracker reimplementation) against 3 MOT17
"ablation" (train-with-ground-truth) sequences from the pinned HF mirror, 200 frames each (a
frame cap, not full-sequence -- MOT17-04 alone is 1050 frames; full-length runs are opt-in via
`--max-frames`), scored against MOTChallenge ground truth (class=pedestrian, conf=considered rows
only) with `motmetrics`. Model: YOLO11s FP32, `confidence_gate=0.4` (this project's shipped
default, not tuned for MOT17 specifically). Raw rows: `docs/mot17-results.jsonl`.

| Sequence | Frames | MOTA | IDF1 | ID switches | Misses | False positives | GT IDs | Pred IDs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MOT17-02-FRCNN | 200 | 0.158 | 0.321 | 22 | 5121 | 610 | 53 | 57 |
| MOT17-04-FRCNN | 200 | 0.259 | 0.458 | 5 | 5874 | 794 | 69 | 37 |
| MOT17-09-FRCNN | 200 | 0.459 | 0.612 | 16 | 737 | 460 | 22 | 44 |

**Honest read: these are low MOTA scores by MOT17-leaderboard standards** (competitive MOT17
entries score 60-80+ MOTA; a from-the-shelf COCO-pretrained detector with no MOT17-specific
fine-tuning or hyperparameter search is not competing in that category, and this harness doesn't
claim to). Misses dominate every sequence's error budget, especially MOT17-02/04 (dense street
crowds, many small/occluded/motion-blurred pedestrians at `confidence_gate=0.4` -- the same
threshold `detector.py` uses in production, deliberately not loosened just to inflate this table).
MOT17-09's much better numbers (0.459 MOTA, sparser scene, fewer simultaneous pedestrians) show
the same detector+tracker doing meaningfully better when the scene matches what it's actually
tuned for (industrial-site pedestrian counts, not train-station-density crowds) -- consistent with
this being a real property of the detector/scene match, not a broken harness (the harness's own
unit tests, `tests/test_eval_tracking.py`, verify a perfect-hypothesis input scores MOTA=IDF1=1.0).
**Not claimed:** that this detector is suitable for dense-crowd pedestrian tracking -- it was
never scoped to be; SiteWatch AI's actual demo scenes (dock/yard/aisle, a handful of people +
vehicles) are a very different distribution than MOT17's train-station crowds.

### M5 exit checklist (docs/12-roadmap.md)

- [x] Benchmark matrix: 2 models × 2 precisions × 1-3 streams, with GPU thermal/power recorded
      alongside every cell (this section)
- [x] MOTA/IDF1 harness -- built and run for real against MOT17 (above); honest low-MOTA result
      explained, not hidden
- [ ] Threshold calibration pass -- pending the expanded (30-fixture) agent-eval results,
      `docs/eval-m5-agent-slow-path.md`
- S2 status: **not met** under today's sustained-load conditions (honest negative result above);
  closest approach is 2-stream FP16 TensorRT. S2's fallback-to-2-streams clause still doesn't
  clear the FPS floor today, though it comes within ~0.4 FPS/stream of it.
