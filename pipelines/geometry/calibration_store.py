"""Load a saved calibration (docs/04 §3) for pipeline use.

Pairs with `pipelines.geometry.calibrate`, which writes
`config/calibration/{camera_id}.json`. Kept separate so the vision pipeline
doesn't need argparse/CLI machinery to read a calibration back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pipelines.geometry.homography import Homography
from pipelines.schemas import CalibrationQuality

CALIBRATION_DIR = Path(__file__).resolve().parents[2] / "config" / "calibration"


@dataclass(frozen=True)
class Calibration:
    camera_id: str
    homography: Homography
    quality: CalibrationQuality


def load_calibration(camera_id: str, calibration_dir: Path = CALIBRATION_DIR) -> Calibration | None:
    """Returns None if no calibration file exists yet for this camera."""
    path = calibration_dir / f"{camera_id}.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    homography = Homography.from_dict({"matrix": data["homography_px_to_m"]})
    quality = CalibrationQuality.from_rms(float(data["rms_px"]))
    return Calibration(camera_id=camera_id, homography=homography, quality=quality)
