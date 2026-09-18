# 04 — Data Sources & Model Selection

## 1. Datasets

Dataset selection was validated hands-on in M1-prep (2026-09-16). The original candidate list
(S2TLD, MOCS, AI City tracklets) did not survive verification — recorded in `docs/11-risks.md`
R2 history. **Actual sources, downloaded and manifested in `data/manifests/`:**

| Dataset | Content | Use in project | License |
| --- | --- | --- | --- |
| **Mendeley rz8723t6d7 v2** ("AI Dataset for Object Detection at Construction Sites") | 87,766 annotated 1080p frames, 856k objects, 12 machinery classes (excavator, bulldozer, crane…), 6 months real site footage | Machinery ground truth (detection evals); M5 fine-tune source | **CC BY 4.0** — redistributable with attribution |
| **NVIDIA PhysicalAI Spatial Intelligence Warehouse** (HF) | Synthetic Omniverse RGB-D stills, warehouse scenes w/ forklifts + spatial QA | spike-02 forklift-class test set (stills) | **CC-BY-4.0** (gated: free HF account) |
| **Pexels demo clips** (7 selected) | Stock video: forklift/worker interaction, walkway, excavator site, PPE | Demo feeds (MediaMTX loop) + S2 multi-stream benchmarks | **Pexels License** — free use, redistributable |
| **MOT17** (via `Lekim89/MOT17` HF mirror) | Pedestrian tracking ground truth | MOTA/IDF1 baseline regression (M5) | research-only (eval only); motchallenge.net is EOL, mirror is the practical source |
| **Pictor-v3 (Pictor PPE)** | 1,472 images, worker/hat/vest annotations | M5 PPE fine-tune | research, citation required; GDrive download |
| **Ehsaanali construction-activity repo** | 15 real excavation clips | local-only supplement if Pexels excavator clips prove too short | ⚠️ no LICENSE — local use only, never committed |

**Dropped after verification:** S2TLD-Construction (unverifiable provenance; name collides with
an unrelated traffic-light dataset), MOCS (source link dead), AI City Challenge (2025 Track 3 is
synthetic VLM stills, not tracklets; no forklift telemetry video — not what the original plan
assumed), Macgence Kaggle listing (marketing page, no actual data).

**Demo clip set (selected, see `data/manifests/pexels-demo-clips.yaml`):** 3 clips map 1:1 to the
cameras in `config/cameras.yaml` — forklift/pedestrian interaction (dock), worker walking aisle
(warehouse), excavator site (yard) — plus one PPE spare. These map to the compound rules in
`config/zones.yaml`.

## 2. Vision Model Strategy

### Detection

| Candidate | Why | Default? |
| --- | --- | --- |
| **YOLO11s** | COCO-pretrained person/vehicle classes; ~35 FPS at 1080p on the RTX A4500 — same as 11n (decode-bound), with better accuracy (spike-00) | **Yes** — settled by spike-00 (2026-09-16) |
| YOLO11n | Fallback if a smaller/faster model is ever needed | No (available via config) |
| YOLO11m + PPE fine-tune | Adds helmet/vest classes (Pictor PPE) | Milestone M5 optional |
| RT-DETR (quantized) | Transformer accuracy at edges of crowd; slower | Benchmark comparison only |
| Grounding DINO / OWL-ViT | Zero-shot class discovery for rare machinery | Research spike only; too slow for fast path |

Pipeline: COCO classes {person, forklift*, truck, bus→heavy-vehicle mapping} at M1; fine-tuned PPE
classes originally planned for M5. `forklift` is not a native COCO class — **spike-02 resolved
this (2026-09-16): the truck/bus → heavy_vehicle proxy ships for M1+** (YOLO-World scored 0%
recall; a synthetic-only fine-tune failed sim2real on real footage — 0/304 frames). **Neither the
real-frame forklift fine-tune nor the PPE classifier landed at M5** (M5 closed 2026-09-18 with its
actual scope -- benchmark matrix, eval-set expansion, threshold calibration -- see
`docs/12-roadmap.md`'s M5 entry); both stay real, disclosed gaps, not yet re-scoped to a specific
milestone, rather than a silently-dropped promise. The truck/bus proxy remains the shipped
default. Full evidence: `docs/spikes/spike-02-forklift-class.md`.

### Tracking

- **ByteTrack** (default): strong association under occlusion, no ReID model needed, CPU-cheap.
- **BoT-SORT** (optional): better camera-motion compensation; benchmark only.
- Per-track **Kalman filter** (constant-velocity model) for smoothed position/velocity; covariance
  forwarded with telemetry as evidence quality.

### Quantization & Runtime

| Precision | Expectation | Status |
| --- | --- | --- |
| FP32 (PyTorch) | Baseline accuracy | Shipped since M1, correctness reference |
| **FP16 TensorRT** | ~2× speed, <0.5 mAP drop | **Real, built at M5** (not M2 as originally planned -- `tensorrt` was never actually installed until then, a real doc/reality gap the M5 pass closed and measured: 34-57% single-stream speedup, 3-stream min-stream FPS 30.2 idle-recovered / 9.5-13.2 sustained-load, `docs/benchmarks.md`). Not yet wired as `pipeline.py`'s runtime default -- the M5 benchmark harness loads `.engine` files explicitly via `--model`, but `Detector`'s own default weights path is still the `.pt` file |
| INT8 TensorRT | ~3–4× speed, ~1–2 mAP drop (calibrate) | **Not built.** Originally planned as an M3 default; never implemented at any milestone through M6 -- a real, disclosed gap, not a broken promise nobody noticed |

Export path: Ultralytics `model.export(format='engine', half=True|int8=True)` → benchmark in
`evaluation/benchmark_models.py`. FP16 export verified working this way (M5); INT8 (`int8=True`)
has not been attempted.

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
| Metrics | FPS/stream, end-to-end latency p50/p95, VRAM, mAP@50 (machinery classes on Mendeley, PPE classes where labeled), MOTA/IDF1 (MOT17) |
| Hardware | record GPU model, driver, TensorRT version, batch size |

Publication standard: every number reproducible via `make eval` with fixed seeds and pinned weights.

## 6. LLM Models (see ADR-003 for full rationale)

| Tier | Class | Use |
| --- | --- | --- |
| T1 worker | GLM-Flash class (OpenRouter/Z.ai) or local Ollama Qwen2.5-Coder | All sub-agent execution: kinematic verification, compliance drafts |
| T2 monitor | free/flash tier | Heartbeats, stream health triage |
| T3 synthesis | larger GLM/DeepSeek class | Final shift reports, escalations after 2 failed sub-agent turns |
