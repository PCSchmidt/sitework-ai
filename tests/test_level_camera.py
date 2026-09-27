"""Level-camera (one-point perspective) ground homography -- pipelines.geometry.level_camera."""

from __future__ import annotations

import numpy as np
import pytest
from pipelines.geometry.level_camera import (
    calibrate_level_camera,
    level_camera_homography,
    line_residuals_px,
)

from _synthetic_camera import (
    CAMERA_HEIGHT_M,
    GROUND_LINES_2,
    PRINCIPAL_POINT,
    F,
    project,
    theoretical_vp,
)

# The synthetic camera has zero roll (pitch 30 deg, yaw 20 deg), which is the
# level-camera model's one geometric assumption; GROUND_LINES_2 run along world Y.
GROUND_TRUTH = [(-3.0, 4.0), (0.0, 6.0), (2.5, 10.0), (-1.0, 18.0), (4.0, 7.5)]


def test_exact_inputs_recover_ground_coordinates() -> None:
    h = level_camera_homography(
        theoretical_vp((0.0, 1.0, 0.0)), PRINCIPAL_POINT, F, CAMERA_HEIGHT_M
    )
    for x, y in GROUND_TRUTH:
        gx, gy = h.apply(project((x, y, 0.0)))
        assert gx == pytest.approx(x, abs=1e-6)
        assert gy == pytest.approx(y, abs=1e-6)


def test_calibrate_from_traced_lines_matches_theory() -> None:
    h, vp, rms = calibrate_level_camera(GROUND_LINES_2, PRINCIPAL_POINT, F, CAMERA_HEIGHT_M)
    assert vp == pytest.approx(theoretical_vp((0.0, 1.0, 0.0)), abs=1e-6)
    assert rms == pytest.approx(0.0, abs=1e-6)
    gx, gy = h.apply(project((2.0, 9.0, 0.0)))
    assert (gx, gy) == pytest.approx((2.0, 9.0), abs=1e-6)


def test_camera_height_scales_all_distances() -> None:
    vp = theoretical_vp((0.0, 1.0, 0.0))
    a = level_camera_homography(vp, PRINCIPAL_POINT, F, CAMERA_HEIGHT_M)
    b = level_camera_homography(vp, PRINCIPAL_POINT, F, 2 * CAMERA_HEIGHT_M)
    px = project((1.5, 8.0, 0.0))
    assert np.allclose(np.array(b.apply(px)), 2 * np.array(a.apply(px)))


def test_noisy_lines_report_nonzero_residual() -> None:
    (p1, p2), *rest = GROUND_LINES_2
    noisy = [(p1, (p2[0] + 6.0, p2[1])), *rest]
    _, vp, rms = calibrate_level_camera(noisy, PRINCIPAL_POINT, F, CAMERA_HEIGHT_M)
    assert rms > 0.5
    assert rms == pytest.approx(
        float(np.sqrt(np.mean(np.square(line_residuals_px(noisy, vp))))), rel=1e-9
    )


def test_rejects_non_positive_assumptions() -> None:
    vp = theoretical_vp((0.0, 1.0, 0.0))
    with pytest.raises(ValueError):
        level_camera_homography(vp, PRINCIPAL_POINT, 0.0, CAMERA_HEIGHT_M)
    with pytest.raises(ValueError):
        level_camera_homography(vp, PRINCIPAL_POINT, F, -1.0)
