"""MOTA/IDF1 tracking evaluation (docs/09 §4, M5 -- docs/12-roadmap.md M5 item 1).

Runs the real detect+track path this project ships (`Detector` +
Ultralytics' built-in ByteTrack via `model.track(..., persist=True)`, the
same call `pipelines/vision/pipeline.py` makes -- this is not a separate
tracker implementation, it measures what actually runs in production)
against MOT17 sequences from the pinned HF mirror (`data/manifests/mot17.yaml`),
and scores it with `motmetrics` against MOTChallenge ground truth.

Mirror quirk (docs/09 §4, `data/manifests/mot17.yaml` notes): the mirror
ships one `gt/gt.txt` per *base* sequence under `ablation/`, not per
detector-variant folder like the official bundle -- `_sequence_dirs` reads
straight from `ablation/`, no resolution needed here.

MOT17 is pedestrian-only, so this scores person-class tracking specifically
(our detector's forklift/vehicle classes have no MOT17 ground truth to
compare against -- a real, disclosed scope limit, not an omission).

Usage:
    uv run python -m evaluation.eval_tracking \
        --sequences MOT17-02-FRCNN MOT17-04-FRCNN --max-frames 200
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

MOT17_ROOT = Path("data/raw/mot17/ablation")
GT_PEDESTRIAN_CLASS = 1


@dataclass
class SequenceResult:
    sequence: str
    frames: int
    mota: float
    idf1: float
    num_switches: int
    num_misses: int
    num_false_positives: int
    num_gt_ids: int
    num_pred_ids: int


def _load_gt(seq_dir: Path) -> pd.DataFrame:
    """MOTChallenge gt.txt: frame,id,bb_left,bb_top,w,h,conf,class,visibility.
    Standard MOT17 pedestrian evaluation keeps conf==1 (considered, not an
    ignore region) and class==1 (pedestrian) rows only -- verified against
    this mirror's own MOT17-02-FRCNN/gt.txt: conf=0 rows are exactly the
    non-pedestrian/ignore classes (2/4/7/8/9), conf=1 rows are all class=1."""
    cols = ["frame", "id", "x", "y", "w", "h", "conf", "cls", "vis"]
    df = pd.read_csv(seq_dir / "gt" / "gt.txt", header=None, names=cols)
    return df[(df["conf"] == 1) & (df["cls"] == GT_PEDESTRIAN_CLASS)]


def _run_tracker(
    seq_dir: Path, weights: str, device: str, imgsz: int, max_frames: int
) -> pd.DataFrame:
    """Runs the real `Detector` + Ultralytics ByteTrack (persist=True) across
    the sequence's frames, in the same call shape pipeline.py uses. Returns
    hypothesis rows in the same (frame, id, x, y, w, h) shape as `_load_gt`."""
    from pipelines.vision.detector import Detector

    detector = Detector(weights=weights, device=device, imgsz=imgsz)
    frame_paths = sorted((seq_dir / "img1").glob("*.jpg"))[:max_frames]

    rows: list[dict[str, object]] = []
    for i, frame_path in enumerate(frame_paths, start=1):
        result = detector.model.track(
            str(frame_path), device=device, imgsz=imgsz, verbose=False,
            persist=True, tracker="bytetrack.yaml",
        )[0]
        if result.boxes is None or result.boxes.id is None:
            continue
        names = result.names
        for box, cls_id, track_id in zip(
            result.boxes.xyxy.cpu().numpy(),
            result.boxes.cls.cpu().numpy().astype(int),
            result.boxes.id.cpu().numpy().astype(int),
            strict=True,
        ):
            if names[cls_id] != "person":
                continue
            x1, y1, x2, y2 = box
            rows.append(
                {"frame": i, "id": int(track_id), "x": float(x1), "y": float(y1),
                 "w": float(x2 - x1), "h": float(y2 - y1)}
            )
    return pd.DataFrame(rows, columns=["frame", "id", "x", "y", "w", "h"])


def _iou_dist_matrix(gt_boxes: np.ndarray, hyp_boxes: np.ndarray, max_iou: float) -> np.ndarray:
    """Reimplements `motmetrics.distances.iou_matrix` without its
    `np.asfarray` call -- removed in NumPy 2.0 (this project's numpy is 2.x,
    a real motmetrics 1.4.0/NumPy-2 incompatibility caught by actually
    running this against real data, not by inspection). Reuses motmetrics'
    own `boxiou` (unaffected -- no asfarray in it), only replacing the
    broken dtype-cast wrapper around it."""
    import motmetrics as mm

    if gt_boxes.size == 0 or hyp_boxes.size == 0:
        return np.empty((0, 0))
    objs = np.asarray(gt_boxes, dtype=float)
    hyps = np.asarray(hyp_boxes, dtype=float)
    iou = mm.distances.boxiou(objs[:, None], hyps[None, :])
    dist = 1 - iou
    return np.where(dist > max_iou, np.nan, dist)


def _score_sequence(
    gt: pd.DataFrame, hyp: pd.DataFrame, seq_name: str, n_frames: int
) -> SequenceResult:
    import motmetrics as mm

    acc = mm.MOTAccumulator(auto_id=False)
    for frame in range(1, n_frames + 1):
        gt_frame = gt[gt["frame"] == frame]
        hyp_frame = hyp[hyp["frame"] == frame]
        gt_boxes = gt_frame[["x", "y", "w", "h"]].to_numpy()
        hyp_boxes = hyp_frame[["x", "y", "w", "h"]].to_numpy()
        # max_iou=0.5: a hypothesis box must overlap a GT box by IoU >= 0.5 to
        # be eligible as a match candidate at all (standard MOTChallenge gate).
        dist = _iou_dist_matrix(gt_boxes, hyp_boxes, max_iou=0.5)
        acc.update(gt_frame["id"].tolist(), hyp_frame["id"].tolist(), dist, frameid=frame)

    mh = mm.metrics.create()
    summary = mh.compute(
        acc,
        metrics=["mota", "idf1", "num_switches", "num_misses", "num_false_positives"],
        name=seq_name,
    )
    row = summary.iloc[0]
    return SequenceResult(
        sequence=seq_name,
        frames=n_frames,
        mota=round(float(row["mota"]), 4),
        idf1=round(float(row["idf1"]), 4),
        num_switches=int(row["num_switches"]),
        num_misses=int(row["num_misses"]),
        num_false_positives=int(row["num_false_positives"]),
        num_gt_ids=int(gt["id"].nunique()) if not gt.empty else 0,
        num_pred_ids=int(hyp["id"].nunique()) if not hyp.empty else 0,
    )


def run(
    sequences: list[str], weights: str, device: str, imgsz: int, max_frames: int
) -> list[SequenceResult]:
    results = []
    for seq_name in sequences:
        seq_dir = MOT17_ROOT / seq_name
        if not seq_dir.exists():
            raise SystemExit(f"sequence not found: {seq_dir} (check data/manifests/mot17.yaml)")
        gt = _load_gt(seq_dir)
        n_frames = min(max_frames, int(gt["frame"].max()) if not gt.empty else max_frames)
        hyp = _run_tracker(seq_dir, weights, device, imgsz, n_frames)
        results.append(_score_sequence(gt, hyp, seq_name, n_frames))
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--sequences", nargs="+",
        default=["MOT17-02-FRCNN", "MOT17-04-FRCNN"],
        help="base sequence names under data/raw/mot17/ablation/",
    )
    ap.add_argument("--model", default="data/models/yolo11s.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument(
        "--max-frames", type=int, default=200,
        help="cap per sequence -- MOT17-04 alone is 1050 frames; full-length runs are opt-in",
    )
    ap.add_argument("--out", type=Path, default=Path("docs/mot17-results.jsonl"))
    args = ap.parse_args()

    results = run(args.sequences, args.model, args.device, args.imgsz, args.max_frames)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r.__dict__) + "\n")

    header = (
        f"{'sequence':<20} {'frames':>7} {'MOTA':>7} {'IDF1':>7} "
        f"{'switches':>9} {'misses':>7} {'FP':>6}"
    )
    print(header)
    for r in results:
        print(
            f"{r.sequence:<20} {r.frames:>7} {r.mota:>7.3f} {r.idf1:>7.3f} "
            f"{r.num_switches:>9} {r.num_misses:>7} {r.num_false_positives:>6}"
        )


if __name__ == "__main__":
    main()
