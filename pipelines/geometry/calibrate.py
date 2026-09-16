"""Manual homography calibration tool (docs/04 §3). Implemented in M2.

Planned CLI: click >= 4 known ground points, solve DLT homography, write
config/calibration/{camera_id}.json with RMS reprojection error. Hard gate:
valid = rms_px <= 2.0. Persists annotated click screenshot + per-point RMS
for auditability.
"""

from __future__ import annotations


def main() -> None:
    raise SystemExit("calibration tool lands in M2 (see docs/12-roadmap.md)")


if __name__ == "__main__":
    main()
