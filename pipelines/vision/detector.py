"""Detector wrapper (docs/04 section 2, ADR-003).

Baseline: YOLO11n via Ultralytics. The class mapping layer is where the
forklift strategy from spike-02 lands — until then, truck/bus map to the
heavy-vehicle bucket and `forklift` comes through only if the chosen
option (YOLO-World / fine-tune) provides it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# COCO classes of interest -> SiteWatch classes.
# spike-02 result (2026-09-16): the truck/bus -> heavy_vehicle proxy is the shipped
# forklift stand-in — it fires reliably on real footage, while YOLO-World and a
# synthetic-only fine-tune both failed. True `forklift` class returns at M5 via a
# real-frame fine-tune (Pictor-v3 + hand-labeled demo frames).
COCO_TO_SITEWATCH: dict[str, str] = {
    "person": "person",
    "bicycle": "vehicle",
    "car": "vehicle",
    "motorcycle": "vehicle",
    "bus": "heavy_vehicle",
    "truck": "heavy_vehicle",
    "forklift": "forklift",  # present only with open-vocab/fine-tuned weights
}


@dataclass(frozen=True)
class Detection:
    cls: str
    confidence: float
    bbox_px: tuple[float, float, float, float]  # x1, y1, x2, y2


class Detector:
    def __init__(
        self,
        weights: str = "yolo11n.pt",
        device: str = "cpu",
        confidence_gate: float = 0.4,
        imgsz: int = 640,
    ) -> None:
        from ultralytics import YOLO  # deferred: heavy import, CUDA init

        self.model = YOLO(weights)
        self.device = device
        self.confidence_gate = confidence_gate
        self.imgsz = imgsz

    def detect(self, frame: np.ndarray) -> list[Detection]:
        results = self.model.predict(
            frame, device=self.device, imgsz=self.imgsz, verbose=False
        )[0]
        out: list[Detection] = []
        names: dict[int, str] = results.names
        if results.boxes is None:
            return out
        for box, conf, cls_id in zip(
            results.boxes.xyxy.cpu().numpy(),
            results.boxes.conf.cpu().numpy(),
            results.boxes.cls.cpu().numpy().astype(int),
            strict=True,
        ):
            coco_name = names[cls_id]
            cls = COCO_TO_SITEWATCH.get(coco_name)
            if cls is None or conf < self.confidence_gate:
                continue
            out.append(
                Detection(
                    cls=cls,
                    confidence=float(conf),
                    bbox_px=(float(box[0]), float(box[1]), float(box[2]), float(box[3])),
                )
            )
        return out
