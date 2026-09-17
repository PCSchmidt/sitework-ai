from __future__ import annotations

import numpy as np
import pytest
from pipelines.geometry.vanishing_point import (
    calibrate_from_vanishing_points,
    estimate_focal_length,
    ground_homography_from_vanishing_points,
    vanishing_point,
)

# Synthetic pinhole camera (verified interactively before writing this module):
# World: X=right, Y=depth (away from camera base), Z=up, ground plane at Z=0.
# Camera: Xc=right, Yc=down (image convention), Zc=forward (optical axis).
F = 800.0
PRINCIPAL_POINT = (320.0, 240.0)
CAMERA_HEIGHT_M = 4.0
PITCH_DEG = 30.0
YAW_DEG = 20.0  # without yaw, world-X lines run exactly horizontal in the image and
# never converge -- a real degenerate case, but not what a real oblique photo looks like.

_R0 = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)
_theta = np.radians(PITCH_DEG)
_RX = np.array(
    [[1, 0, 0], [0, np.cos(_theta), -np.sin(_theta)], [0, np.sin(_theta), np.cos(_theta)]]
)
_psi = np.radians(YAW_DEG)
_RZ = np.array([[np.cos(_psi), -np.sin(_psi), 0], [np.sin(_psi), np.cos(_psi), 0], [0, 0, 1]])
R = _R0 @ _RX @ _RZ
K = np.array([[F, 0, PRINCIPAL_POINT[0]], [0, F, PRINCIPAL_POINT[1]], [0, 0, 1]])
C = np.array([0.0, 0.0, CAMERA_HEIGHT_M])
T = -R @ C


def project(world_pt: tuple[float, float, float]) -> tuple[float, float]:
    cam = R @ np.array(world_pt) + T
    img = K @ cam
    return (float(img[0] / img[2]), float(img[1] / img[2]))


def _theoretical_vp(direction: tuple[float, float, float]) -> tuple[float, float]:
    d_cam = R @ np.array(direction)
    v = K @ d_cam
    return (float(v[0] / v[2]), float(v[1] / v[2]))


# Ground-plane lines: varying X at fixed Y (direction 1, "lateral"), varying Y at
# fixed X (direction 2, "depth" -- like roof trusses receding from the camera).
GROUND_LINES_1 = [
    (project((0.0, y, 0.0)), project((5.0, y, 0.0))) for y in (3.0, 8.0, 15.0)
]
GROUND_LINES_2 = [
    (project((x, 2.0, 0.0)), project((x, 20.0, 0.0))) for x in (-3.0, 0.0, 3.0)
]
VERTICAL_LINES = [
    (project((x, 6.0, 0.0)), project((x, 6.0, 2.5))) for x in (-2.0, 0.0, 2.0)
]
GROUND_REFERENCE_PX = project((0.0, 3.0, 0.0))  # a pixel known to be on the ground


def test_vanishing_point_recovers_ground_lateral_direction() -> None:
    expected = _theoretical_vp((1.0, 0.0, 0.0))
    got = vanishing_point(GROUND_LINES_1)
    assert got == pytest.approx(expected, abs=0.5)


def test_vanishing_point_recovers_ground_depth_direction() -> None:
    expected = _theoretical_vp((0.0, 1.0, 0.0))
    got = vanishing_point(GROUND_LINES_2)
    assert got == pytest.approx(expected, abs=0.5)


def test_vanishing_point_recovers_vertical_direction() -> None:
    expected = _theoretical_vp((0.0, 0.0, 1.0))
    got = vanishing_point(VERTICAL_LINES)
    assert got == pytest.approx(expected, abs=0.5)


def test_vanishing_point_requires_at_least_two_lines() -> None:
    with pytest.raises(ValueError, match=">= 2"):
        vanishing_point([GROUND_LINES_1[0]])


def test_vanishing_point_rejects_lines_parallel_in_image() -> None:
    # two identical (image-parallel, never converging) lines -> VP at infinity
    line = ((0.0, 0.0), (10.0, 0.0))
    parallel = ((0.0, 5.0), (10.0, 5.0))
    with pytest.raises(ValueError, match="infinity"):
        vanishing_point([line, parallel])


def test_estimate_focal_length_recovers_known_f() -> None:
    v1 = vanishing_point(GROUND_LINES_1)
    v2 = vanishing_point(GROUND_LINES_2)
    f = estimate_focal_length(v1, v2, PRINCIPAL_POINT)
    assert f == pytest.approx(F, rel=0.02)


def test_estimate_focal_length_rejects_non_orthogonal_pair() -> None:
    # two vanishing points on the same side of the principal point in both axes
    # (not a valid orthogonal ground/ground or ground/vertical pair)
    with pytest.raises(ValueError, match="f\\^2"):
        estimate_focal_length((400.0, 300.0), (500.0, 350.0), PRINCIPAL_POINT)


def test_ground_homography_round_trip_recovers_world_points() -> None:
    v1 = vanishing_point(GROUND_LINES_1)
    v2 = vanishing_point(GROUND_LINES_2)
    v3 = vanishing_point(VERTICAL_LINES)
    homography = ground_homography_from_vanishing_points(
        v1, v2, v3, PRINCIPAL_POINT, CAMERA_HEIGHT_M, GROUND_REFERENCE_PX
    )

    for world_xy in [(0.0, 5.0), (3.0, 8.0), (-2.0, 12.0), (1.5, 20.0)]:
        px = project((world_xy[0], world_xy[1], 0.0))
        recovered = homography.apply(px)
        assert recovered == pytest.approx(world_xy, abs=0.15)


def test_ground_homography_tolerates_imprecise_real_world_line_picks() -> None:
    """Regression test for a real bug found calibrating an actual phone photo.

    Hand-picked pixel coordinates off a real image are never perfectly
    precise -- the resulting vanishing-point triple is a few degrees off
    true orthogonality, not exact. An earlier version of this function
    rejected any triple whose determinant wasn't within 1e-3 of exactly
    +-1, which silently raised "degenerate vanishing points" on real
    (merely noisy, not actually degenerate) data. The fix projects onto
    the nearest true rotation (SVD) instead of demanding exact
    orthonormality; this perturbs each vanishing point by a few pixels,
    the rough size of a real manual pick's error, and checks the method
    still produces *a* homography rather than raising.
    """
    rng = np.random.default_rng(0)

    def jitter(p: tuple[float, float], scale: float = 3.0) -> tuple[float, float]:
        return (p[0] + rng.normal(0, scale), p[1] + rng.normal(0, scale))

    jittered_lines_1 = [
        (jitter(a), jitter(b)) for a, b in GROUND_LINES_1
    ]
    jittered_lines_2 = [
        (jitter(a), jitter(b)) for a, b in GROUND_LINES_2
    ]
    jittered_vertical = [
        (jitter(a), jitter(b)) for a, b in VERTICAL_LINES
    ]

    homography = calibrate_from_vanishing_points(
        jittered_lines_1,
        jittered_lines_2,
        jittered_vertical,
        PRINCIPAL_POINT,
        CAMERA_HEIGHT_M,
        GROUND_REFERENCE_PX,
    )
    # still roughly in the right ballpark despite the noise -- not exact,
    # just no longer an outright failure to produce anything at all.
    px = project((2.0, 10.0, 0.0))
    recovered = homography.apply(px)
    assert recovered == pytest.approx((2.0, 10.0), abs=2.0)


def test_calibrate_from_vanishing_points_end_to_end() -> None:
    homography = calibrate_from_vanishing_points(
        GROUND_LINES_1,
        GROUND_LINES_2,
        VERTICAL_LINES,
        PRINCIPAL_POINT,
        CAMERA_HEIGHT_M,
        GROUND_REFERENCE_PX,
    )
    px = project((2.0, 10.0, 0.0))
    recovered = homography.apply(px)
    assert recovered == pytest.approx((2.0, 10.0), abs=0.15)


def test_ground_homography_sensitive_to_wrong_camera_height() -> None:
    """Sanity check the method actually uses camera_height_m as a real scale anchor."""
    v1 = vanishing_point(GROUND_LINES_1)
    v2 = vanishing_point(GROUND_LINES_2)
    v3 = vanishing_point(VERTICAL_LINES)
    correct = ground_homography_from_vanishing_points(
        v1, v2, v3, PRINCIPAL_POINT, CAMERA_HEIGHT_M, GROUND_REFERENCE_PX
    )
    wrong = ground_homography_from_vanishing_points(
        v1, v2, v3, PRINCIPAL_POINT, CAMERA_HEIGHT_M * 2, GROUND_REFERENCE_PX
    )
    px = project((2.0, 10.0, 0.0))
    correct_pt = correct.apply(px)
    wrong_pt = wrong.apply(px)
    # doubling the assumed camera height should roughly double the recovered scale
    assert wrong_pt[1] == pytest.approx(correct_pt[1] * 2, rel=0.05)
