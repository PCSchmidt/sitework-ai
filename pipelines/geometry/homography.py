"""Pixel <-> ground-plane homography (docs/04 §3).

Solves the direct linear transform (DLT) for a planar homography from >= 4
point correspondences (image px -> ground-plane meters), and reports the RMS
reprojection error used as the hard calibration quality gate
(`RMS_GATE_PX` in pipelines.schemas, valid = rms_px <= 2.0).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

Point = tuple[float, float]


@dataclass(frozen=True)
class Homography:
    """3x3 homography mapping image pixels -> ground-plane meters."""

    matrix: np.ndarray  # (3, 3)

    @classmethod
    def solve(cls, image_pts: list[Point], world_pts: list[Point]) -> Homography:
        """DLT solve for H such that world_pts ~ H @ [image_pts; 1] (homogeneous).

        Requires >= 4 non-collinear correspondences. Uses SVD on the DLT
        design matrix (per-point, 2 rows) and takes the singular vector for
        the smallest singular value, per the standard planar-homography DLT.
        """
        if len(image_pts) != len(world_pts):
            raise ValueError("image_pts and world_pts must have the same length")
        if len(image_pts) < 4:
            raise ValueError(f"homography needs >= 4 point correspondences, got {len(image_pts)}")

        a_rows = []
        for (x, y), (u, v) in zip(image_pts, world_pts, strict=True):
            a_rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
            a_rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
        a = np.asarray(a_rows, dtype=np.float64)

        _, _, vt = np.linalg.svd(a)
        h = vt[-1].reshape(3, 3)
        if abs(h[2, 2]) > 1e-12:
            h = h / h[2, 2]
        return cls(matrix=h)

    def apply(self, point: Point) -> Point:
        """Project one image-pixel point through H to ground-plane meters."""
        x, y = point
        vec = self.matrix @ np.array([x, y, 1.0])
        w = vec[2]
        if abs(w) < 1e-12:
            raise ZeroDivisionError("homography projected point to infinity (degenerate H)")
        return (float(vec[0] / w), float(vec[1] / w))

    def apply_many(self, points: list[Point]) -> list[Point]:
        return [self.apply(p) for p in points]

    def reprojection_errors_px(self, image_pts: list[Point], world_pts: list[Point]) -> list[float]:
        """Reprojection error in *pixels*: invert H, map world_pts back to image space."""
        h_inv = Homography(matrix=np.linalg.inv(self.matrix))
        errors = []
        for (x, y), world in zip(image_pts, world_pts, strict=True):
            rx, ry = h_inv.apply(world)
            errors.append(float(np.hypot(rx - x, ry - y)))
        return errors

    def rms_px(self, image_pts: list[Point], world_pts: list[Point]) -> float:
        errors = self.reprojection_errors_px(image_pts, world_pts)
        return float(np.sqrt(np.mean(np.square(errors))))

    def to_dict(self) -> dict[str, list[list[float]]]:
        return {"matrix": self.matrix.tolist()}

    @classmethod
    def from_dict(cls, data: dict[str, list[list[float]]]) -> Homography:
        return cls(matrix=np.asarray(data["matrix"], dtype=np.float64))
