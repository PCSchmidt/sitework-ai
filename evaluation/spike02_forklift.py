"""Spike-02: forklift-class detection strategy evaluation (docs/spikes/spike-02-forklift-class.md).

Test set: 30 HF warehouse val frames containing 'transporter' (forklift/AGV) with
RLE ground-truth masks + 10 negative frames (no transporter). Options evaluated:
  (a) YOLO-World open-vocab prompt 'forklift'
  (b) COCO truck/bus proxy mapping
Metric: detection recall vs RLE-mask bounding boxes (IoU >= 0.5), plus FPS on cuda:0.

Usage:
    uv run python evaluation/spike02_forklift.py --build-testset   # once
    uv run python evaluation/spike02_forklift.py --option proxy    # truck/bus
    uv run python evaluation/spike02_forklift.py --option yolo-world
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np

VAL_JSON = Path("data/raw/hf-warehouse/val.json")
VAL_IMAGES = Path("data/raw/hf-warehouse/val/images")
TESTSET = Path("data/raw/spike02-testset")
RESULTS = Path("docs/spikes/spike-02-results.jsonl")

FORKLIFT_WORD = "transporter"  # HF dataset's label for forklift/AGV
N_POS = 30
N_NEG = 10
IOU_THRESHOLD = 0.5


def build_testset() -> None:
    import av  # noqa: F401  (ensures image deps present)

    data = json.loads(VAL_JSON.read_text())
    rng = random.Random(42)

    pos = [d for d in data if any(FORKLIFT_WORD in c.get("value", "").lower()
                                  for c in d.get("conversations", []))]
    neg_pool = [d for d in data if not any(FORKLIFT_WORD in c.get("value", "").lower()
                                           for c in d.get("conversations", []))]
    pos = pos  # all 420 available; sample below
    rng.shuffle(pos)
    rng.shuffle(neg_pool)
    selected = pos[:N_POS] + neg_pool[:N_NEG]

    TESTSET.mkdir(parents=True, exist_ok=True)
    manifest = []
    for d in selected:
        img = d["image"]
        src = VAL_IMAGES / img
        if not src.exists():
            continue
        # RLE -> bbox via pycocotools (handles compressed-count strings correctly)
        from pycocotools import mask as mask_utils

        boxes = []
        for r in d.get("rle") or []:
            h, w = r["size"]
            mask = mask_utils.decode({"size": [h, w], "counts": r["counts"]})
            ys, xs = np.nonzero(mask)
            if len(xs):
                boxes.append([int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())])
        has_forklift = any(FORKLIFT_WORD in c.get("value", "").lower()
                           for c in d.get("conversations", []))
        manifest.append({"image": img, "is_forklift_frame": has_forklift, "gt_boxes": boxes})
    (TESTSET / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"test set: {len(manifest)} frames "
          f"({sum(m['is_forklift_frame'] for m in manifest)} forklift-positive)")


def evaluate(option: str, device: str, imgsz: int) -> None:
    manifest = json.loads((TESTSET / "manifest.json").read_text())
    model, class_ids = _load_model(option)

    tp = fp = fn = 0
    lat: list[float] = []
    for entry in manifest:
        img_path = VAL_IMAGES / entry["image"]
        import av

        with av.open(str(img_path)) as c:
            frame = next(c.decode(video=0)).to_ndarray(format="bgr24")
        t0 = time.perf_counter()
        res = model.predict(frame, device=device, imgsz=imgsz, verbose=False)[0]
        lat.append((time.perf_counter() - t0) * 1000)

        pred_boxes = []
        if res.boxes is not None:
            for box, cid in zip(res.boxes.xyxy.cpu().numpy(),
                                res.boxes.cls.cpu().numpy().astype(int), strict=True):
                if cid in class_ids:
                    pred_boxes.append(box)

        matched = _match(pred_boxes, entry["gt_boxes"])
        tp += matched
        fp += len(pred_boxes) - matched
        if entry["is_forklift_frame"]:
            fn += max(0, len(entry["gt_boxes"]) - matched)

    recall = tp / (tp + fn) if tp + fn else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    row = {
        "option": option,
        "device": device,
        "imgsz": imgsz,
        "recall@0.5": round(recall, 3),
        "precision@0.5": round(precision, 3),
        "fps": round(1000 / (sum(lat) / len(lat)), 1),
        "tp": tp, "fp": fp, "fn": fn,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    print(json.dumps(row, indent=2))


def _load_model(option: str):
    from ultralytics import YOLO, YOLOWorld

    if option == "proxy":
        model = YOLO("yolo11s.pt")
        coco = model.names
        ids = {i for i, n in coco.items() if n in ("truck", "bus")}
        return model, ids
    if option == "yolo-world":
        model = YOLOWorld("yolov8s-worldv2.pt")
        model.set_classes(["forklift"])
        return model, {0}
    raise SystemExit(f"unknown option {option}")


def _match(pred_boxes: list, gt_boxes: list) -> int:
    matched = 0
    used: set[int] = set()
    for gt in gt_boxes:
        for i, p in enumerate(pred_boxes):
            if i in used:
                continue
            if _iou(p, gt) >= IOU_THRESHOLD:
                used.add(i)
                matched += 1
                break
    return matched


def _iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-testset", action="store_true")
    ap.add_argument("--option", choices=["proxy", "yolo-world"])
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--imgsz", type=int, default=640)
    args = ap.parse_args()

    if args.build_testset:
        build_testset()
    elif args.option:
        evaluate(args.option, args.device, args.imgsz)
    else:
        ap.error("specify --build-testset or --option")


if __name__ == "__main__":
    main()
