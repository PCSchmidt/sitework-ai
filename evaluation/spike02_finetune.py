"""Spike-02 fine-tune: build a YOLO dataset from HF warehouse frames and train YOLO11s.

Source: data/raw/hf-warehouse val split — 1,835 PNGs, QA entries carry RLE masks.
The dataset's forklift/AGV label is "transporter" (confirmed 2026-09-16: 1,038 mentions,
401 positive frames). RLE masks become YOLO bbox labels; classes = {transporter}.

  build   → data/raw/spike02-finetune/  (images/, labels/, forklift.yaml)
  train   → YOLO11s fine-tune on cuda:0 → data/models/forklift-yolo11s.pt
  validate→ real footage check on assets/clips/forklift_workers_interaction_1080p.mp4
            (sim2real gap test — the actual question this spike answers)

Usage:
    uv run python evaluation/spike02_finetune.py build
    uv run python evaluation/spike02_finetune.py train --epochs 20
    uv run python evaluation/spike02_finetune.py validate
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

import numpy as np

VAL_JSON = Path("data/raw/hf-warehouse/val.json")
VAL_IMAGES = Path("data/raw/hf-warehouse/val/images")
OUT = Path("data/raw/spike02-finetune")
MODEL_OUT = Path("data/models/forklift-yolo11s.pt")
REAL_CLIP = Path("assets/clips/forklift_workers_interaction_1080p.mp4")

FORKLIFT_WORD = "transporter"
TRAIN_FRAC = 0.85
SEED = 42


def build() -> None:
    from pycocotools import mask as mask_utils

    data = json.loads(VAL_JSON.read_text())
    rng = random.Random(SEED)
    rng.shuffle(data)

    for split in ("train", "val"):
        (OUT / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUT / "labels" / split).mkdir(parents=True, exist_ok=True)

    n_train = int(len(data) * TRAIN_FRAC)
    written = 0
    for i, entry in enumerate(data):
        img = entry["image"]
        src = VAL_IMAGES / img
        if not src.exists():
            continue
        split = "train" if i < n_train else "val"
        h, w = _image_size(entry)

        boxes = []
        for r in entry.get("rle") or []:
            mh, mw = r["size"]
            mask = mask_utils.decode({"size": [mh, mw], "counts": r["counts"]})
            ys, xs = np.nonzero(mask)
            if len(xs) < 50:  # skip specks
                continue
            # Only label frames the QA text identifies as containing a transporter.
            # (We cannot attribute individual RLE masks to classes, so we label the
            # largest region on transporter-positive frames as the forklift.)
            boxes.append([int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())])

        is_pos = any(FORKLIFT_WORD in c.get("value", "").lower()
                     for c in entry.get("conversations", []))
        shutil.copy2(src, OUT / "images" / split / img)
        label_path = (OUT / "labels" / split / img).with_suffix(".txt")
        if is_pos and boxes:
            x1, y1, x2, y2 = max(boxes, key=lambda b: (b[2]-b[0]) * (b[3]-b[1]))
            cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
            bw, bh = (x2 - x1) / w, (y2 - y1) / h
            label_path.write_text(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
        else:
            label_path.write_text("")  # negative frame
        written += 1

    (OUT / "forklift.yaml").write_text(
        f"path: {OUT.resolve().as_posix()}\n"
        "train: images/train\nval: images/val\n"
        "names:\n  0: forklift\n"
    )
    print(f"dataset: {written} frames -> {OUT}")


def _image_size(entry: dict) -> tuple[int, int]:
    rles = entry.get("rle") or []
    if rles:
        return int(rles[0]["size"][0]), int(rles[0]["size"][1])
    return 1080, 1920  # dataset default per card


def train(epochs: int, device: str, imgsz: int) -> None:
    from ultralytics import YOLO

    model = YOLO("yolo11s.pt")
    model.train(
        data=str(OUT / "forklift.yaml"),
        epochs=epochs,
        imgsz=imgsz,
        device=device,
        project=str(OUT / "runs"),
        name="forklift",
        seed=SEED,
        verbose=False,
    )
    best = OUT / "runs" / "forklift" / "weights" / "best.pt"
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, MODEL_OUT)
    print(f"trained model -> {MODEL_OUT}")


def validate(device: str, imgsz: int) -> None:
    """The real question: does the synthetic-trained model fire on real footage?"""
    import av
    from ultralytics import YOLO

    model = YOLO(str(MODEL_OUT))
    detections = 0
    frames = 0
    confs: list[float] = []
    with av.open(str(REAL_CLIP)) as container:
        for packet in container.demux(video=0):
            for frame in packet.decode():
                img = frame.to_ndarray(format="bgr24")
                res = model.predict(img, device=device, imgsz=imgsz, verbose=False)[0]
                frames += 1
                if res.boxes is not None and len(res.boxes):
                    detections += 1
                    confs.extend(float(c) for c in res.boxes.conf.cpu().numpy())

    rate = detections / frames if frames else 0.0
    row = {
        "clip": str(REAL_CLIP),
        "frames": frames,
        "frames_with_forklift_detection": detections,
        "detection_rate": round(rate, 3),
        "mean_confidence": round(float(np.mean(confs)), 3) if confs else None,
    }
    print("SIM2REAL:", json.dumps(row, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["build", "train", "validate"])
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--imgsz", type=int, default=640)
    args = ap.parse_args()

    if args.command == "build":
        build()
    elif args.command == "train":
        train(args.epochs, args.device, args.imgsz)
    else:
        validate(args.device, args.imgsz)


if __name__ == "__main__":
    main()
