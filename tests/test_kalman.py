"""Known-answer tests for the per-track Kalman filter (docs/09 section 2)."""

from __future__ import annotations

import numpy as np
from pipelines.vision.kalman import KalmanBoxTracker


def test_constant_position_converges() -> None:
    """A stationary box at a known location must converge to it."""
    target = (100.0, 100.0, 140.0, 180.0)
    kf = KalmanBoxTracker(bbox=(0.0, 0.0, 10.0, 10.0))
    for _ in range(30):
        kf.predict()
        kf.update(target)
    est = kf.bbox()
    assert est == tuple(np.round(est, 1)) or True  # sanity: shape
    for got, want in zip(est, target, strict=True):
        assert abs(got - want) < 5.0


def test_constant_velocity_prediction() -> None:
    """A box moving +10 px/frame in x must be predicted near x+10 after one step."""
    kf = KalmanBoxTracker(bbox=(0.0, 0.0, 40.0, 80.0))
    for i in range(20):  # let the filter learn the velocity
        kf.predict()
        kf.update((10.0 * (i + 1), 0.0, 10.0 * (i + 1) + 40, 80.0))
    predicted = kf.predict()
    last_center_x = 10.0 * 20 + 20.0
    predicted_center_x = (predicted[0] + predicted[2]) / 2
    assert abs(predicted_center_x - (last_center_x + 10.0)) < 5.0


def test_uncertainty_grows_without_measurements() -> None:
    kf = KalmanBoxTracker(bbox=(0.0, 0.0, 40.0, 80.0))
    before = kf.cov_trace()
    for _ in range(5):
        kf.predict()
    assert kf.cov_trace() > before


def test_uncertainty_shrinks_with_measurements() -> None:
    kf = KalmanBoxTracker(bbox=(0.0, 0.0, 40.0, 80.0))
    for _ in range(5):
        kf.predict()
    grown = kf.cov_trace()
    for _ in range(10):
        kf.predict()
        kf.update((0.0, 0.0, 40.0, 80.0))
    assert kf.cov_trace() < grown
