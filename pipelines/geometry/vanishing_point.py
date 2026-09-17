"""Single-view metrology: derive a ground-plane Homography from vanishing points.

`pipelines.geometry.homography.Homography.solve()` needs >= 4 measured
point correspondences (pixel <-> real-world meters) -- the "manual
calibration" workflow in docs/04 §3. That needs either a real site survey
or, as explored for the dock_north_01 demo clip, a clean multi-point
reference object with unambiguous ground-plane geometry visible from one
angle. Neither was available: the demo frame only shows two collinear
wheel-contact points on one side of a forklift, and a person's height is
an out-of-plane measurement a ground homography can't use directly.

This module is the alternative classical technique for exactly that case:
a scene with **structural parallel lines** (roof trusses, wall-floor
edges, a mast) instead of a clean reference object. It:

1. Estimates two vanishing points for orthogonal *ground-plane* directions
   and one for the *vertical* direction, each from >= 2 line segments
   assumed parallel in 3D (least-squares line intersection).
2. Recovers focal length from the orthogonality constraint between the two
   ground vanishing points (assumes zero skew, square pixels, principal
   point at the image center -- no other intrinsics are known here).
3. Builds the camera's rotation from the three (now-orthonormal) viewing
   directions, and combines it with one assumed scale anchor -- the
   camera's height above the ground plane -- to get the full ground
   homography.

The camera-height assumption is the method's one required "known
measurement," same role `Homography.solve()` fills with measured point
correspondences. It still can't be verified without a survey; treat any
resulting calibration as an engineering estimate, not a surveyed one, and
prefer `Homography.solve()` whenever real ground-truth points exist.
"""

from __future__ import annotations

import itertools
import math

import numpy as np

from pipelines.geometry.homography import Homography, Point

Line = tuple[Point, Point]


def vanishing_point(lines: list[Line]) -> Point:
    """Least-squares vanishing point of lines assumed parallel in 3D.

    Each line contributes its homogeneous line equation (cross product of
    its two homogeneous endpoints); the vanishing point is the point
    minimizing total squared distance to all lines, i.e. the right
    singular vector of the stacked line-equation matrix for its smallest
    singular value.
    """
    if len(lines) < 2:
        raise ValueError(f"need >= 2 line segments to estimate a vanishing point, got {len(lines)}")

    rows = []
    for (x1, y1), (x2, y2) in lines:
        p1 = np.array([x1, y1, 1.0])
        p2 = np.array([x2, y2, 1.0])
        rows.append(np.cross(p1, p2))
    a = np.stack(rows)

    _, _, vt = np.linalg.svd(a)
    v_h = vt[-1]
    if abs(v_h[2]) < 1e-9:
        raise ValueError("lines are parallel in the image (vanishing point at infinity)")
    return (float(v_h[0] / v_h[2]), float(v_h[1] / v_h[2]))


def estimate_focal_length(v1: Point, v2: Point, principal_point: Point) -> float:
    """Focal length (px) from two orthogonal vanishing points (zero skew, square pixels).

    Orthogonality constraint: (v1 - pp).(v2 - pp) + f^2 = 0, i.e. the rays
    to two vanishing points of perpendicular 3D directions are
    perpendicular through the camera center.
    """
    cx, cy = principal_point
    dot = (v1[0] - cx) * (v2[0] - cx) + (v1[1] - cy) * (v2[1] - cy)
    f_squared = -dot
    if f_squared <= 0:
        raise ValueError(
            f"orthogonality constraint gives f^2={f_squared:.1f} <= 0 -- "
            "vanishing points/principal point are inconsistent with an orthogonal pair "
            "(check the line picks and that both directions are truly perpendicular)"
        )
    return float(np.sqrt(f_squared))


def _direction(v: Point, principal_point: Point, f: float) -> np.ndarray:
    cx, cy = principal_point
    d = np.array([v[0] - cx, v[1] - cy, f])
    result: np.ndarray = d / np.linalg.norm(d)
    return result


def orthogonality_residual_deg(
    v_ground1: Point, v_ground2: Point, v_vertical: Point, principal_point: Point
) -> tuple[float, float]:
    """How far the vertical vanishing point is from truly perpendicular to each
    ground direction, in degrees, *before* `ground_homography_from_vanishing_points`
    silently corrects for it via SVD.

    The two ground vanishing points are orthogonal to each other by
    construction (that's what `estimate_focal_length` solves for), so only
    the vertical axis's angle to each of them is informative here. Near 0
    means the three vanishing points are consistent with genuinely
    orthogonal 3D directions -- i.e. the line picks were precise and the
    scene really is rectilinear. Several degrees or more is a real
    warning sign about the picks (or a lens-distortion/non-rectilinear
    scene violating the pinhole assumption), not just numerical noise;
    `calibrate_from_lines` converts this into a pixel-equivalent quality
    proxy comparable to the point-correspondence method's RMS gate.
    """
    f = estimate_focal_length(v_ground1, v_ground2, principal_point)
    r1 = _direction(v_ground1, principal_point, f)
    r2 = _direction(v_ground2, principal_point, f)
    r3 = _direction(v_vertical, principal_point, f)
    theta1 = math.degrees(math.asin(min(1.0, abs(float(r1 @ r3)))))
    theta2 = math.degrees(math.asin(min(1.0, abs(float(r2 @ r3)))))
    return (theta1, theta2)


def ground_homography_from_vanishing_points(
    v_ground1: Point,
    v_ground2: Point,
    v_vertical: Point,
    principal_point: Point,
    camera_height_m: float,
    ground_reference_px: Point,
) -> Homography:
    """Build a pixel->meters ground Homography from three vanishing points.

    `v_ground1`/`v_ground2` are vanishing points of two orthogonal
    ground-plane directions; `v_vertical` is the vanishing point of
    vertical lines. `camera_height_m` is the assumed camera height above
    the ground plane -- the method's one required scale anchor.

    A vanishing point encodes a 3D *direction*, not a signed ray: a set of
    parallel lines has one vanishing point regardless of which way along
    that direction is "positive." That leaves a real ambiguity in which
    way each of the three recovered axes points -- not just the vertical
    one, all three -- but only the sign combinations that keep
    `[r1, r2, r3]` a proper rotation (determinant +1, no mirroring) are
    physically valid camera orientations (exactly 4 of the 8 possible sign
    triples, depending on the raw triple's own handedness). Each valid one
    is resolved by picking whichever gives the smallest, most plausible
    reconstructed distance for `ground_reference_px` -- a pixel the caller
    knows is on the ground, e.g. near the bottom of the frame.
    """
    f = estimate_focal_length(v_ground1, v_ground2, principal_point)
    r1_raw = _direction(v_ground1, principal_point, f)
    r2_raw = _direction(v_ground2, principal_point, f)
    r3_raw = _direction(v_vertical, principal_point, f)

    k = np.array([[f, 0, principal_point[0]], [0, f, principal_point[1]], [0, 0, 1]])
    gx, gy = ground_reference_px

    # Exactly 4 of the 8 sign combinations give a proper (not mirrored) rotation;
    # which 4 depends on the raw triple's own handedness, so all 8 are tried and
    # filtered by determinant *sign*, not an exact +1 match -- real line picks are
    # never perfectly orthogonal (a few degrees off is normal), so each kept triple
    # is snapped to the nearest true rotation via SVD (standard orthogonal
    # Procrustes) rather than rejected for not already being exactly orthonormal.
    candidates: list[tuple[float, Homography]] = []
    for s1, s2, s3 in itertools.product((1, -1), repeat=3):
        r1_n, r2_n, r3_n = s1 * r1_raw, s2 * r2_raw, s3 * r3_raw
        raw = np.column_stack([r1_n, r2_n, r3_n])
        if np.linalg.det(raw) <= 0:
            continue  # mirrored, not a physically valid camera orientation
        u, _s, vt = np.linalg.svd(raw)
        rotation = u @ vt
        r1, r2, r3 = rotation[:, 0], rotation[:, 1], rotation[:, 2]

        t = -camera_height_m * r3
        h_world_to_image = k @ np.column_stack([r1, r2, t])
        try:
            h_image_to_world = np.linalg.inv(h_world_to_image)
        except np.linalg.LinAlgError:
            continue

        w = h_image_to_world @ np.array([gx, gy, 1.0])
        if abs(w[2]) < 1e-9:
            continue
        world_pt = np.array([w[0] / w[2], w[1] / w[2]])
        plausibility = float(
            np.linalg.norm(world_pt)
        )  # smaller = closer to camera base, more plausible
        candidates.append((plausibility, Homography(matrix=h_image_to_world)))

    if not candidates:
        raise ValueError(
            "could not construct a valid ground homography (degenerate vanishing points)"
        )
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


def calibrate_from_vanishing_points(
    ground_lines_1: list[Line],
    ground_lines_2: list[Line],
    vertical_lines: list[Line],
    principal_point: Point,
    camera_height_m: float,
    ground_reference_px: Point,
) -> Homography:
    """End-to-end: line picks -> vanishing points -> ground Homography."""
    v1 = vanishing_point(ground_lines_1)
    v2 = vanishing_point(ground_lines_2)
    v3 = vanishing_point(vertical_lines)
    return ground_homography_from_vanishing_points(
        v1, v2, v3, principal_point, camera_height_m, ground_reference_px
    )
