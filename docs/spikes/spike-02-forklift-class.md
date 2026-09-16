# Spike-02: Forklift-Class Detection Strategy — RESULTS

**Status:** complete (2026-09-16) · **Owner:** solo dev · **Timebox:** 2 days → done in 1 session

## Question

`forklift` is not a COCO class. The flagship M2 demo (forklift–pedestrian proximity) needs a
forklift detector. Three options were evaluated with real measurements, not assumptions.

## Test setup

- **Synthetic eval set:** 40 frames from the HF PhysicalAI Warehouse val split (30
  forklift-positive by the dataset's "transporter" label, RLE masks → GT boxes, IoU ≥ 0.5).
  `data/raw/spike02-testset/manifest.json`; harness: `evaluation/spike02_forklift.py`.
- **Real-footage check:** `assets/clips/forklift_workers_interaction_1080p.mp4` (304 frames,
  real warehouse forklift + pedestrian).

## Results

| Option | Synthetic recall@0.5 | Synthetic precision@0.5 | Real clip | Verdict |
| --- | --- | --- | --- | --- |
| **(b) COCO truck/bus proxy** (YOLO11s) | 0.145 | 0.581 | `truck` fires 325× / 304 frames; `person` 662× | ✅ **works on real footage** |
| (a) YOLO-World "forklift" (yolov8s-worldv2) | **0.000** | — | — | ❌ dead on this distribution |
| (c) Fine-tune YOLO11s on synthetic HF frames (20 ep) | mAP50 0.247 (weak) | precision 0.222 | **0 / 304 frames** | ❌ fails sim2real |

## The counterintuitive finding

The "hacky proxy" the docs warned against is the only option that works **on the demo's actual
domain** (real footage): a real forklift reads as `truck` to COCO YOLO. The fine-tune failed
because Omniverse-synthetic forklifts don't look like real ones — a clean sim2real gap, confirmed
empirically (0/304 frames). The proxy's poor 14.5% recall on *synthetic* frames is the mirror
image: synthetic AGVs don't look like trucks. Each approach fails in the other's domain; the demo
runs on real footage, so the proxy wins **for now**.

## Decision

**Ship option (b) for M1–M4**, with guardrails:
- Class `heavy_vehicle` (truck/bus) is the forklift stand-in; per-camera confidence gates in
  `config/cameras.yaml` absorb false positives; the zone engine filters off-zone noise
  (e.g. `traffic light` fired 24× on the clip — irrelevant outside zones).
- The `forklift` passthrough in `pipelines/vision/detector.py` stays for a future true class.

**Deferred to M5 (real fine-tune, done right):** label *real* frames (our own Pexels clips via
the calibration tooling + Pictor-v3) rather than synthetic renders. Mendeley machinery set remains
the excavator-class label source (its download was corrupt on Mendeley's end 2026-09-16; retry at
M5 — not needed for the M2 demo).

## Recorded risk

Sim2real: any model trained only on synthetic data is presumed non-deployable on real footage
until validated on a real clip. This spike is the standing evidence; reference it before any
future synthetic-only training proposal.
