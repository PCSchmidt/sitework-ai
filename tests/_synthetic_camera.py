"""Shared synthetic pinhole camera fixture for vanishing-point tests.

Not a test module itself (no `test_*` functions) -- imported by
test_vanishing_point.py and test_calibrate.py so both exercise the same
known-ground-truth camera rather than duplicating it.

World: X=right, Y=depth (away from camera base), Z=up, ground plane at Z=0.
Camera: Xc=right, Yc=down (image convention), Zc=forward (optical axis).
Convention verified interactively before this fixture was written.
"""

from __future__ import annotations

import numpy as np

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


def theoretical_vp(direction: tuple[float, float, float]) -> tuple[float, float]:
    d_cam = R @ np.array(direction)
    v = K @ d_cam
    return (float(v[0] / v[2]), float(v[1] / v[2]))


# Ground-plane lines: varying X at fixed Y (direction 1, "lateral"), varying Y at
# fixed X (direction 2, "depth" -- like roof trusses receding from the camera).
GROUND_LINES_1 = [(project((0.0, y, 0.0)), project((5.0, y, 0.0))) for y in (3.0, 8.0, 15.0)]
GROUND_LINES_2 = [(project((x, 2.0, 0.0)), project((x, 20.0, 0.0))) for x in (-3.0, 0.0, 3.0)]
VERTICAL_LINES = [(project((x, 6.0, 0.0)), project((x, 6.0, 2.5))) for x in (-2.0, 0.0, 2.0)]
GROUND_REFERENCE_PX = project((0.0, 3.0, 0.0))  # a pixel known to be on the ground
# Deliberately imprecise (true value is (0.0, 3.0)) but correctly-signed -- models an
# operator's rough real-world guess, not a measurement (docs on
# ground_homography_from_vanishing_points). Also deliberately off the X=0 axis so
# tests exercising it aren't themselves symmetric under point-reflection.
GROUND_REFERENCE_EXPECTED_XY = (0.5, 2.0)
