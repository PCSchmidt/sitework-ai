# 04 — Data Sources & Model Selection

## 1. Datasets

All primary datasets are research/permissive datasets. **Pin exact versions at download time and
record license + URL + SHA256 in `data/manifests/`.** Keep a 3-clip fallback set in `assets/clips/`
so the demo never breaks if an upstream dataset disappears.

| Dataset | Content | Use in project | License note |
| --- | --- | --- | --- |
| **S2TLD / S2TLD-Construction** | ~100 h multi-camera CCTV, heavy machinery + ground workers | Demo clips, detection fine-tune classes (excavator, loader, truck, person) | Verify before redistribution; typically research-only |
| **MOCS (Moving Objects in Construction Sites)** | Heavy machinery under occlusion, lighting change | Tracker stress test, occlusion evaluation | Research |
| **Pictor PPE / CHV (Construction Hazard Video)** | PPE compliance, near-misses, swing-radius incidents | PPE classifier head; compound-rule demo scenarios | Research (Pictor-v3) |
| **AI City Challenge (warehouse/logistics tracks)** | Forklift telemetry, dock monitoring, ground-truth tracklets | MOTA/IDF1 quantitative tracking eval | Competition license; request access early |
| **MOT17/MOT20** | Pedestrian tracking ground truth | Baseline tracker regression tests | CC BY-NC-SA (evaluation only) |
| **Fallback set (3 clips)** | Warehouse / construction / dock, 2–4 min each | One-command demo determinism | Self-produced or clearly licensed |

**Selection for demo:** 3 clips minimum — (1) forklift near pedestrian walkway, (2) excavator swing
radius with workers, (3) PPE violation at dock. These map 1:1 to the compound rules in
`config/zones.yaml`.

## 2. Vision Model Strategy

### Detection

| Candidate | Why | Default? |
| --- | --- | --- |
| **YOLO11n** | COCO-pretrained person/vehicle classes; excellent FPS on modest/laptop GPU; TensorRT export well-trodden | **Yes** (baseline until spike-00 GPU probe; YOLO11s is the upgrade target if headroom allows) |
| YOLO11m + PPE fine-tune | Adds helmet/vest classes (Pictor PPE) | Milestone M5 optional |
| RT-DETR (quantized) | Transformer accuracy at edges of crowd; slower | Benchmark comparison only |
| Grounding DINO / OWL-ViT | Zero-shot class discovery for rare machinery | Research spike only; too slow for fast path |

Pipeline: COCO classes {person, forklift*, truck, bus→heavy-vehicle mapping} at M1; fine-tuned PPE
classes at M5. `forklift` is not a native COCO class — this is decided by **spike-02
(`docs/spikes/spike-02-forklift-class.md`) early in M1**, which measures three options on the demo
clip: (a) YOLO-World open-vocab detection, (b) truck/bus proxy mapping, (c) small fine-tune on
S2TLD/AI City forklift crops. The flagship M2 proximity demo must not ship on a proxy that fails
on the demo footage.

### Tracking

- **ByteTrack** (default): strong association under occlusion, no ReID model needed, CPU-cheap.
- **BoT-SORT** (optional): better camera-motion compensation; benchmark only.
- Per-track **Kalman filter** (constant-velocity model) for smoothed position/velocity; covariance
  forwarded with telemetry as evidence quality.

### Quantization & Runtime

| Precision | Expectation | Plan |
| --- | --- | --- |
| FP32 (PyTorch) | Baseline accuracy | M1 only, for correctness reference |
| **FP16 TensorRT** | ~2× speed, <0.5 mAP drop | Default from M2 |
| **INT8 TensorRT** | ~3–4× speed, ~1–2 mAP drop (calibrate) | Default from M3; PTQ with 500 representative frames |

Export path: Ultralytics `model.export(format='engine', half=True|int8=True)` → benchmark in
`evaluation/benchmark_models.py`.

## 3. Calibration & Homography

- **Manual calibration tool** (`pipelines/geometry/calibrate.py`): click ≥ 4 known ground points in
  a frame, enter their metric coordinates from a site plan (or measured tape distances); solves DLT
  homography H (3×3, px→meters). Saves to `config/calibration/{camera_id}.json` with reprojection
  error (RMS px) which becomes the **calibration quality metric** forwarded in telemetry.
- Ground point for a track: bottom-center of bbox projected through H. Velocity in m/s from Kalman
  state in ground coordinates.
- **Hard quality gate:** `calibration_quality.valid = (rms_px ≤ 2.0)`. Rules that require metric
  distance (proximity, speed, wrong_way) declare `min_calibration_quality` and degrade to
  zone-only semantics when calibration is invalid.
- Known limits (document in report UI): height above ground misestimates ground point; assume ≤ 0.3 m
  error with good calibration (RMS < 2 px); rules include `min_calibration_quality` gate.

## 4. Fast-Path Rule Engine (Deterministic)

Rules are config-declared (`config/zones.yaml`), evaluated per frame pair/track:

| Rule family | Semantics (deterministic) |
| --- | --- |
| `zone_intrusion` | track ground point ∈ polygon for ≥ `dwell_s` seconds while zone `active` |
| `proximity` | min distance(worker, vehicle) < `radius_m` for ≥ `duration_s` |
| `ppe_absence` | PPE class absent on person track inside `ppe_required_zones` |
| `speed` | track ground speed > `limit_mps` inside polygon |
| `wrong_way` | velocity vector vs polygon lane direction |

Compound example (the flagship): `worker WITHOUT helmet inside active excavator swing radius for
> 3.0 s` = `ppe_absence ∧ zone_intrusion ∧ vehicle_state=active`. Trigger dedup: same rule+tracks
not re-fired within `cooldown_s` (default 120 s).

## 5. Benchmark Matrix (deliverable)

`evaluation/benchmark_models.py` produces `docs/benchmarks.md`:

| Axis | Values |
| --- | --- |
| Models | YOLO11n, YOLO11s, YOLO11m, RT-DETR (if feasible) |
| Precision | FP32, FP16, INT8 |
| Streams | 1, 2, 3, 4 concurrent |
| Metrics | FPS/stream, end-to-end latency p50/p95, VRAM, mAP@50 (PPE classes where labeled), MOTA/IDF1 (AI City / MOT clips) |
| Hardware | record GPU model, driver, TensorRT version, batch size |

Publication standard: every number reproducible via `make eval` with fixed seeds and pinned weights.

## 6. LLM Models (see ADR-003 for full rationale)

| Tier | Class | Use |
| --- | --- | --- |
| T1 worker | GLM-Flash class (OpenRouter/Z.ai) or local Ollama Qwen2.5-Coder | All sub-agent execution: kinematic verification, compliance drafts |
| T2 monitor | free/flash tier | Heartbeats, stream health triage |
| T3 synthesis | larger GLM/DeepSeek class | Final shift reports, escalations after 2 failed sub-agent turns |
