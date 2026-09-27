"""Load a saved calibration (docs/04 §3) for pipeline use.

Pairs with `pipelines.geometry.calibrate`, which writes
`config/calibration/{camera_id}.json`. Kept separate so the vision pipeline
doesn't need argparse/CLI machinery to read a calibration back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from pipelines.geometry.homography import Homography
from pipelines.schemas import CalibrationQuality

CALIBRATION_DIR = Path(__file__).resolve().parents[2] / "config" / "calibration"


@dataclass(frozen=True)
class Calibration:
    camera_id: str
    homography: Homography
    quality: CalibrationQuality
    # Frame the calibration was made on (`reference_image` in the JSON, relative
    # to the calibration dir). Present only for cameras that move: callers then
    # compensate each frame back onto it (pipelines.geometry.motion).
    reference_image: Path | None = None

    def for_frame(self, frame_to_reference: np.ndarray) -> Calibration:
        """This calibration applied to a frame whose pixels map onto the
        reference frame's via `frame_to_reference` (3x3)."""
        return replace(
            self, homography=Homography(matrix=self.homography.matrix @ frame_to_reference)
        )


def load_calibration(camera_id: str, calibration_dir: Path = CALIBRATION_DIR) -> Calibration | None:
    """Returns None if no calibration file exists yet for this camera."""
    path = calibration_dir / f"{camera_id}.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    homography = Homography.from_dict({"matrix": data["homography_px_to_m"]})
    quality = CalibrationQuality.from_rms(float(data["rms_px"]))
    reference = data.get("reference_image")
    return Calibration(
        camera_id=camera_id,
        homography=homography,
        quality=quality,
        reference_image=calibration_dir / reference if reference else None,
    )
