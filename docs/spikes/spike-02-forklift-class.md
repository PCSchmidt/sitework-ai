# Spike-02: Forklift-Class Detection Strategy

**Status:** planned (parallel with M1) · **Owner:** solo dev · **Timebox:** 2 days

## Purpose

`forklift` is not a COCO class, but the flagship M2 demo is a forklift–pedestrian proximity event.
Shipping the demo on the truck/bus proxy without measuring it risks a broken flagship scenario
(see plan review, "forklift demo paradox"). This spike picks the strategy with data.

## Options

| Option | Approach | Risk |
| --- | --- | --- |
| A | YOLO-World open-vocab detection (`forklift` prompt) | FPS hit on laptop GPU; prompt sensitivity |
| B | COCO truck/bus proxy with documented mapping | Systematic false negatives on real forklifts |
| C | Small fine-tune of YOLO11n on Mendeley machinery frames + HF warehouse forklift crops (~500–1k images) | Time cost; labeling effort |

## Procedure

1. Extract 20–30 labeled forklift frames from the chosen demo clip(s) as the test set.
2. Evaluate each option: recall@0.5 IoU on forklift, FPS impact, false positives on trucks.
3. Pick the option with recall ≥ 0.8 and acceptable FPS (fits spike-00 budget).

## Decision (fill in during M1)

- **Chosen option:** _TBD_
- **Measured recall / FPS:** _TBD_
- **Rationale:** _TBD_
