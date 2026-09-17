"""Manual homography calibration tool (docs/04 §3).

Solves a pixel -> ground-plane-meters homography from >= 4 point
correspondences and writes `config/calibration/{camera_id}.json` with the
matrix, the RMS reprojection error, and the hard quality gate
(`valid = rms_px <= RMS_GATE_PX`, docs/06 §3).

Correspondences are supplied as a JSON file (`--points`) rather than
collected via interactive frame-clicking: this keeps the tool scriptable and
testable, and clicking is just one way to produce the same file. Format:

    [
      {"image_px": [x, y], "world_m": [x, y]},
      ...
    ]

Usage:
    uv run python -m pipelines.geometry.calibrate \
        --camera-id dock_north_01 \
        --points config/calibration/dock_north_01.points.json \
        --out-dir config/calibration
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from pipelines.geometry.homography import Homography, Point
from pipelines.schemas import RMS_GATE_PX, CalibrationQuality


class CalibrationError(ValueError):
    """Raised when the supplied correspondences can't produce a calibration."""


def load_correspondences(path: Path) -> tuple[list[Point], list[Point]]:
    with path.open("r", encoding="utf-8") as fh:
        rows = json.load(fh)
    if not isinstance(rows, list) or len(rows) < 4:
        raise CalibrationError(f"{path} must contain a JSON list with >= 4 correspondences")
    image_pts: list[Point] = []
    world_pts: list[Point] = []
    for i, row in enumerate(rows):
        try:
            image_pts.append((float(row["image_px"][0]), float(row["image_px"][1])))
            world_pts.append((float(row["world_m"][0]), float(row["world_m"][1])))
        except (KeyError, IndexError, TypeError) as exc:
            raise CalibrationError(f"{path} row {i} malformed: {row!r}") from exc
    return image_pts, world_pts


def calibrate(camera_id: str, image_pts: list[Point], world_pts: list[Point]) -> dict[str, object]:
    homography = Homography.solve(image_pts, world_pts)
    rms_px = homography.rms_px(image_pts, world_pts)
    quality = CalibrationQuality.from_rms(rms_px)
    return {
        "camera_id": camera_id,
        "created_at": datetime.now(UTC).isoformat(),
        "homography_px_to_m": homography.to_dict()["matrix"],
        "points": [
            {"image_px": list(img), "world_m": list(world)}
            for img, world in zip(image_pts, world_pts, strict=True)
        ],
        "rms_px": round(rms_px, 4),
        "valid": quality.valid,
        "rms_gate_px": RMS_GATE_PX,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--camera-id", required=True)
    ap.add_argument("--points", type=Path, required=True, help="JSON correspondences file")
    ap.add_argument("--out-dir", type=Path, default=Path("config/calibration"))
    args = ap.parse_args()

    image_pts, world_pts = load_correspondences(args.points)
    record = calibrate(args.camera_id, image_pts, world_pts)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"{args.camera_id}.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)

    print(json.dumps({k: v for k, v in record.items() if k != "points"}, indent=2))
    if not record["valid"]:
        raise SystemExit(
            f"calibration for {args.camera_id} FAILED quality gate: "
            f"rms_px={record['rms_px']} > {RMS_GATE_PX} (written anyway to {out_path}, "
            "but rules requiring metric distance will degrade to zone-only)"
        )


if __name__ == "__main__":
    main()
