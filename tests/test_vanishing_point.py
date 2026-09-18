from __future__ import annotations

import numpy as np
import pytest
from pipelines.geometry.vanishing_point import (
    calibrate_from_vanishing_points,
    estimate_focal_length,
    ground_homography_from_vanishing_points,
    orthogonality_residual_deg,
    vanishing_point,
)

from _synthetic_camera import (
    CAMERA_HEIGHT_M,
    GROUND_LINES_1,
    GROUND_LINES_2,
    GROUND_REFERENCE_EXPECTED_XY,
    GROUND_REFERENCE_PX,
    PRINCIPAL_POINT,
    VERTICAL_LINES,
    F,
    project,
)
from _synthetic_camera import theoretical_vp as _theoretical_vp


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


def test_orthogonality_residual_near_zero_for_exact_synthetic_data() -> None:
    v1 = vanishing_point(GROUND_LINES_1)
    v2 = vanishing_point(GROUND_LINES_2)
    v3 = vanishing_point(VERTICAL_LINES)
    theta1, theta2 = orthogonality_residual_deg(v1, v2, v3, PRINCIPAL_POINT)
    assert theta1 == pytest.approx(0.0, abs=0.1)
    assert theta2 == pytest.approx(0.0, abs=0.1)


def test_orthogonality_residual_grows_with_a_bad_vertical_pick() -> None:
    v1 = vanishing_point(GROUND_LINES_1)
    v2 = vanishing_point(GROUND_LINES_2)
    # a vertical line family that isn't actually vertical in 3D
    bad_vertical = [((100.0, 100.0), (300.0, 400.0)), ((500.0, 50.0), (600.0, 500.0))]
    v3_bad = vanishing_point(bad_vertical)
    theta1, theta2 = orthogonality_residual_deg(v1, v2, v3_bad, PRINCIPAL_POINT)
    assert max(theta1, theta2) > 5.0


def test_ground_homography_round_trip_recovers_world_points() -> None:
    v1 = vanishing_point(GROUND_LINES_1)
    v2 = vanishing_point(GROUND_LINES_2)
    v3 = vanishing_point(VERTICAL_LINES)
    homography = ground_homography_from_vanishing_points(
        v1,
        v2,
        v3,
        PRINCIPAL_POINT,
        CAMERA_HEIGHT_M,
        GROUND_REFERENCE_PX,
        GROUND_REFERENCE_EXPECTED_XY,
    )

    for world_xy in [(0.0, 5.0), (3.0, 8.0), (-2.0, 12.0), (1.5, 20.0)]:
        px = project((world_xy[0], world_xy[1], 0.0))
        recovered = homography.apply(px)
        assert recovered == pytest.approx(world_xy, abs=0.15)


def test_ground_homography_sign_disambiguation_not_decided_by_a_symmetric_tie() -> None:
    """Regression test for a real cross-platform CI failure (2026-09-18).

    The sign ambiguity here is really two independent ambiguities: which way
    is "up" (resolved by requiring `ground_reference_px`'s ray to hit the
    ground in front of the camera, not behind it -- exact, no heuristic
    needed), and which way is "positive" in the ground plane's own X/Y axes
    (a 180-degree in-plane rotation about the now-fixed vertical axis, which
    leaves every camera-observable fact identical -- no single pixel's depth
    can resolve it). The old code tried to resolve *both* with one heuristic,
    "pick whichever reconstructs `ground_reference_px` closest to the
    origin" -- mathematically blind to the second ambiguity
    (`‖(x,y)‖ == ‖(-x,-y)‖` always), so it was silently decided by sub-ulp
    floating-point noise on *every* calibration, not just an edge case:
    green locally, `(-3.0)` recovered where `(3.0)` was expected on CI's
    BLAS. Fixed by adding `ground_reference_expected_xy` -- an operator's
    rough real-world guess -- and disambiguating against that instead of the
    origin.
    """
    v1 = vanishing_point(GROUND_LINES_1)
    v2 = vanishing_point(GROUND_LINES_2)
    v3 = vanishing_point(VERTICAL_LINES)
    homography = ground_homography_from_vanishing_points(
        v1,
        v2,
        v3,
        PRINCIPAL_POINT,
        CAMERA_HEIGHT_M,
        GROUND_REFERENCE_PX,
        GROUND_REFERENCE_EXPECTED_XY,
    )
    recovered = homography.apply(GROUND_REFERENCE_PX)
    # GROUND_REFERENCE_PX = project((0.0, 3.0, 0.0)) -- the mirrored (wrong)
    # solution recovers (0.0, -3.0) instead, which is *farther* from
    # GROUND_REFERENCE_EXPECTED_XY = (0.5, 2.0) than the correct one.
    assert recovered == pytest.approx((0.0, 3.0), abs=0.15), f"recovered {recovered}, mirror picked"


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

    jittered_lines_1 = [(jitter(a), jitter(b)) for a, b in GROUND_LINES_1]
    jittered_lines_2 = [(jitter(a), jitter(b)) for a, b in GROUND_LINES_2]
    jittered_vertical = [(jitter(a), jitter(b)) for a, b in VERTICAL_LINES]

    homography = calibrate_from_vanishing_points(
        jittered_lines_1,
        jittered_lines_2,
        jittered_vertical,
        PRINCIPAL_POINT,
        CAMERA_HEIGHT_M,
        GROUND_REFERENCE_PX,
        GROUND_REFERENCE_EXPECTED_XY,
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
        GROUND_REFERENCE_EXPECTED_XY,
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
        v1,
        v2,
        v3,
        PRINCIPAL_POINT,
        CAMERA_HEIGHT_M,
        GROUND_REFERENCE_PX,
        GROUND_REFERENCE_EXPECTED_XY,
    )
    wrong = ground_homography_from_vanishing_points(
        v1,
        v2,
        v3,
        PRINCIPAL_POINT,
        CAMERA_HEIGHT_M * 2,
        GROUND_REFERENCE_PX,
        GROUND_REFERENCE_EXPECTED_XY,
    )
    px = project((2.0, 10.0, 0.0))
    correct_pt = correct.apply(px)
    wrong_pt = wrong.apply(px)
    # doubling the assumed camera height should roughly double the recovered scale
    assert wrong_pt[1] == pytest.approx(correct_pt[1] * 2, rel=0.05)
