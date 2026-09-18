"""Manual homography calibration tool (docs/04 §3).

Two methods, both writing the same `config/calibration/{camera_id}.json`
shape (matrix, a quality metric, and the hard gate
`valid = rms_px <= RMS_GATE_PX`, docs/06 §3):

- **points** (default): solves a pixel -> ground-plane-meters homography
  from >= 4 measured point correspondences (`pipelines.geometry.homography`).
  Needs a real site survey or an unambiguous multi-point reference object.
- **vanishing_point**: single-view metrology from structural parallel lines
  (`pipelines.geometry.vanishing_point`) for scenes without a clean
  reference object but with visible orthogonal structure (e.g. two
  baseboards meeting at a room corner). Needs one assumed scale anchor
  (camera height) instead of measured points; its `rms_px` is a *derived*
  pixel-equivalent proxy (focal length x orthogonality residual in
  radians), not a literal point-reprojection error -- comparable to the
  points method's gate, but not the same kind of measurement.

Correspondences/lines are supplied as JSON files rather than collected
interactively (clicking/tracing is just one way to produce the same file):

    # --points file
    [{"image_px": [x, y], "world_m": [x, y]}, ...]

    # --lines file
    {
      "ground_lines_1": [[[x1, y1], [x2, y2]], ...],
      "ground_lines_2": [[[x1, y1], [x2, y2]], ...],
      "vertical_lines": [[[x1, y1], [x2, y2]], ...],
      "principal_point": [cx, cy],
      "ground_reference_px": [x, y],
      "ground_reference_expected_xy": [x_m, y_m]
    }

`ground_reference_expected_xy` is the operator's own *rough* real-world estimate of
where `ground_reference_px` sits (e.g. "about 1m ahead, roughly centered") -- it only
needs to be roughly in the right direction, not measured; it resolves an in-plane
180-degree sign ambiguity that no amount of precision on the lines/vanishing points
themselves can (`ground_homography_from_vanishing_points`'s docstring, point 2).

Usage:
    uv run python -m pipelines.geometry.calibrate \
        --camera-id dock_north_01 \
        --points config/calibration/dock_north_01.points.json \
        --out-dir config/calibration

    uv run python -m pipelines.geometry.calibrate \
        --method vanishing_point --camera-id dining_room_01 \
        --lines config/calibration/dining_room_01.lines.json \
        --camera-height 1.2 --out-dir config/calibration
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from pipelines.geometry.homography import Homography, Point
from pipelines.geometry.vanishing_point import (
    Line,
    calibrate_from_vanishing_points,
    estimate_focal_length,
    orthogonality_residual_deg,
    vanishing_point,
)
from pipelines.schemas import RMS_GATE_PX, CalibrationQuality


class CalibrationError(ValueError):
    """Raised when the supplied correspondences/lines can't produce a calibration."""


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
        "method": "points",
        "homography_px_to_m": homography.to_dict()["matrix"],
        "points": [
            {"image_px": list(img), "world_m": list(world)}
            for img, world in zip(image_pts, world_pts, strict=True)
        ],
        "rms_px": round(rms_px, 4),
        "valid": quality.valid,
        "rms_gate_px": RMS_GATE_PX,
    }


def load_lines(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    required = {
        "ground_lines_1",
        "ground_lines_2",
        "vertical_lines",
        "principal_point",
        "ground_reference_px",
        "ground_reference_expected_xy",
    }
    missing = required - data.keys()
    if missing:
        raise CalibrationError(f"{path} missing required key(s): {sorted(missing)}")
    return data  # type: ignore[no-any-return]


def _parse_lines(rows: list[list[list[float]]]) -> list[Line]:
    return [((float(a[0]), float(a[1])), (float(b[0]), float(b[1]))) for a, b in rows]


def calibrate_from_lines(
    camera_id: str,
    ground_lines_1: list[Line],
    ground_lines_2: list[Line],
    vertical_lines: list[Line],
    principal_point: Point,
    camera_height_m: float,
    ground_reference_px: Point,
    ground_reference_expected_xy: Point,
) -> dict[str, object]:
    homography = calibrate_from_vanishing_points(
        ground_lines_1,
        ground_lines_2,
        vertical_lines,
        principal_point,
        camera_height_m,
        ground_reference_px,
        ground_reference_expected_xy,
    )
    v1 = vanishing_point(ground_lines_1)
    v2 = vanishing_point(ground_lines_2)
    v3 = vanishing_point(vertical_lines)
    f = estimate_focal_length(v1, v2, principal_point)
    theta1, theta2 = orthogonality_residual_deg(v1, v2, v3, principal_point)
    residual_deg = max(theta1, theta2)
    # pixel-equivalent of the angular residual, so it's comparable to the
    # points method's literal reprojection RMS (same gate, different measurement).
    rms_px = f * math.radians(residual_deg)
    quality = CalibrationQuality.from_rms(rms_px)
    return {
        "camera_id": camera_id,
        "created_at": datetime.now(UTC).isoformat(),
        "method": "vanishing_point",
        "homography_px_to_m": homography.to_dict()["matrix"],
        "camera_height_m_assumed": camera_height_m,
        "orthogonality_residual_deg": round(residual_deg, 3),
        "focal_length_px": round(f, 1),
        "rms_px": round(rms_px, 4),
        "valid": quality.valid,
        "rms_gate_px": RMS_GATE_PX,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--camera-id", required=True)
    ap.add_argument("--method", choices=["points", "vanishing_point"], default="points")
    ap.add_argument("--points", type=Path, help="JSON correspondences file (--method points)")
    ap.add_argument("--lines", type=Path, help="JSON lines file (--method vanishing_point)")
    ap.add_argument(
        "--camera-height", type=float, help="assumed camera height, meters (vanishing_point)"
    )
    ap.add_argument("--out-dir", type=Path, default=Path("config/calibration"))
    args = ap.parse_args()

    if args.method == "points":
        if args.points is None:
            ap.error("--method points requires --points")
        image_pts, world_pts = load_correspondences(args.points)
        record = calibrate(args.camera_id, image_pts, world_pts)
    else:
        if args.lines is None or args.camera_height is None:
            ap.error("--method vanishing_point requires --lines and --camera-height")
        data = load_lines(args.lines)
        record = calibrate_from_lines(
            args.camera_id,
            _parse_lines(data["ground_lines_1"]),  # type: ignore[arg-type]
            _parse_lines(data["ground_lines_2"]),  # type: ignore[arg-type]
            _parse_lines(data["vertical_lines"]),  # type: ignore[arg-type]
            (float(data["principal_point"][0]), float(data["principal_point"][1])),  # type: ignore[index]
            args.camera_height,
            (float(data["ground_reference_px"][0]), float(data["ground_reference_px"][1])),  # type: ignore[index]
            (
                float(data["ground_reference_expected_xy"][0]),  # type: ignore[index]
                float(data["ground_reference_expected_xy"][1]),  # type: ignore[index]
            ),
        )

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
