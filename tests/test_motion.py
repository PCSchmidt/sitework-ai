"""Camera-motion compensation -- pipelines.geometry.motion."""

from __future__ import annotations

import cv2
import numpy as np
from pipelines.geometry.calibration_store import Calibration
from pipelines.geometry.homography import Homography
from pipelines.geometry.motion import MotionCompensator
from pipelines.schemas import CalibrationQuality


def _textured_scene(seed: int = 0) -> np.ndarray:
    """A 640x480 BGR image with plenty of corners for ORB to match."""
    rng = np.random.default_rng(seed)
    img = np.full((480, 640, 3), 128, np.uint8)
    for _ in range(250):
        x, y = int(rng.integers(0, 600)), int(rng.integers(0, 440))
        w, h = int(rng.integers(8, 40)), int(rng.integers(8, 40))
        color = tuple(int(c) for c in rng.integers(0, 255, 3))
        cv2.rectangle(img, (x, y), (x + w, y + h), color, -1)
    return img


def _shift(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderValue=(128, 128, 128))


def test_recovers_a_camera_pan_as_a_translation() -> None:
    ref = _textured_scene()
    moved = _shift(ref, 12.0, -7.0)  # content moved right/up => frame px map back left/down
    h = MotionCompensator(ref).frame_to_reference(moved)
    px = h @ np.array([300.0, 200.0, 1.0])
    assert np.allclose(px[:2] / px[2], [288.0, 207.0], atol=0.5)


def test_featureless_frame_falls_back_to_last_good_estimate() -> None:
    ref = _textured_scene()
    mc = MotionCompensator(ref)
    good = mc.frame_to_reference(_shift(ref, 5.0, 0.0))
    blank = np.full_like(ref, 128)
    assert np.array_equal(mc.frame_to_reference(blank), good)


def test_calibration_for_frame_composes_motion_before_ground_projection() -> None:
    cal = Calibration(
        camera_id="cam",
        homography=Homography(matrix=np.diag([0.01, 0.01, 1.0])),
        quality=CalibrationQuality.from_rms(1.0),
    )
    frame_to_ref = np.array([[1.0, 0, -12.0], [0, 1.0, 7.0], [0, 0, 1.0]])
    # a point at (312, 193) in the moved frame is (300, 200) in the reference frame
    assert cal.for_frame(frame_to_ref).homography.apply((312.0, 193.0)) == (3.0, 2.0)
