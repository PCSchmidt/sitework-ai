"""Class-mapping tests — no model download required (docs/09 section 1)."""

from __future__ import annotations

from pipelines.vision.detector import COCO_TO_SITEWATCH


def test_person_maps() -> None:
    assert COCO_TO_SITEWATCH["person"] == "person"


def test_heavy_vehicle_proxies() -> None:
    # spike-02 interim: truck/bus are the heavy-machinery proxy bucket
    assert COCO_TO_SITEWATCH["truck"] == "heavy_vehicle"
    assert COCO_TO_SITEWATCH["bus"] == "heavy_vehicle"


def test_forklift_passthrough_for_future_weights() -> None:
    # present only with open-vocab / fine-tuned weights (spike-02 decision)
    assert COCO_TO_SITEWATCH["forklift"] == "forklift"


def test_irrelevant_coco_classes_excluded() -> None:
    for cls in ("cat", "dog", "pizza", "toothbrush", "airplane"):
        assert cls not in COCO_TO_SITEWATCH
