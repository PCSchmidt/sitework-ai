from __future__ import annotations

import numpy as np
import pytest
from pipelines.geometry.homography import Homography

# A simple similarity mapping used across tests: world = 0.1 * image (px -> m),
# i.e. 10 px/m, no rotation. Easy to hand-verify.
IMAGE_PTS = [(0.0, 0.0), (100.0, 0.0), (100.0, 80.0), (0.0, 80.0)]
WORLD_PTS = [(0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0)]

# A homography has 8 DOF, so exactly 4 correspondences always fit *exactly*
# (RMS == 0 regardless of "noise" in a point) -- over-determine with a 5th
# point to get a meaningful least-squares residual for the noise tests.
IMAGE_PTS_5 = [*IMAGE_PTS, (50.0, 40.0)]
WORLD_PTS_5 = [*WORLD_PTS, (5.0, 4.0)]


def test_solve_recovers_exact_scale_mapping() -> None:
    h = Homography.solve(IMAGE_PTS, WORLD_PTS)
    for img, world in zip(IMAGE_PTS, WORLD_PTS, strict=True):
        got = h.apply(img)
        assert got == pytest.approx(world, abs=1e-9)


def test_rms_px_zero_for_exact_correspondences() -> None:
    h = Homography.solve(IMAGE_PTS, WORLD_PTS)
    assert h.rms_px(IMAGE_PTS, WORLD_PTS) == pytest.approx(0.0, abs=1e-6)


def test_rms_px_positive_when_one_point_is_noisy() -> None:
    noisy_world = list(WORLD_PTS_5)
    noisy_world[4] = (noisy_world[4][0] + 2.0, noisy_world[4][1] - 1.5)
    h = Homography.solve(IMAGE_PTS_5, noisy_world)
    assert h.rms_px(IMAGE_PTS_5, noisy_world) > 0.5


def test_apply_on_interior_point() -> None:
    h = Homography.solve(IMAGE_PTS, WORLD_PTS)
    assert h.apply((50.0, 40.0)) == pytest.approx((5.0, 4.0), abs=1e-9)


def test_solve_requires_at_least_four_points() -> None:
    with pytest.raises(ValueError, match=">= 4"):
        Homography.solve(IMAGE_PTS[:3], WORLD_PTS[:3])


def test_solve_requires_matching_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        Homography.solve(IMAGE_PTS, WORLD_PTS[:3])


def test_to_dict_from_dict_round_trip() -> None:
    h = Homography.solve(IMAGE_PTS, WORLD_PTS)
    restored = Homography.from_dict(h.to_dict())
    assert np.allclose(h.matrix, restored.matrix)
    assert restored.apply((50.0, 40.0)) == pytest.approx((5.0, 4.0), abs=1e-9)
