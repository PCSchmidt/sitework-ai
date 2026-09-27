"""Ground homography for a one-point-perspective view (level camera, zero roll).

`pipelines.geometry.vanishing_point` needs two *finite* vanishing points for
orthogonal ground directions, which a camera looking straight down an aisle
doesn't provide: the depth lines converge nicely, but the cross-aisle lines
(ceiling beams, shelf fronts) stay near-parallel in the image, so the second
vanishing point sits at infinity and the focal-length estimate is
ill-conditioned. That is exactly the dock_north_01 demo view.

This module handles that case with a smaller set of inputs:

- **measured:** the depth vanishing point, least-squares fitted from >= 2
  traced line segments that run along the aisle (floor joints, wall bases,
  window sills). Its horizontal image line is the horizon; with zero roll it
  fixes camera pitch (relative to the principal point) and yaw (the world Y
  axis is the depth direction).
- **assumed, and recorded as such:** camera height above the floor (the
  metric scale) and focal length in pixels (which only scales distances
  *along* the depth axis; cross-aisle distances at a given image row are
  independent of it).

The quality number is the RMS perpendicular distance, in pixels, from the
fitted vanishing point to each traced line: how consistently the lines agree
on one vanishing point. It is comparable to the other methods' `rms_px` in
kind (pixels, same gate), but it measures only the geometric consistency of
the measured part. The scale assumptions aren't captured by it; the
calibration file records them next to the matrix.

World frame: origin on the floor directly below the camera, +Y along the depth
direction (away from the camera), +X to the right, meters.
"""

from __future__ import annotations

import numpy as np

from pipelines.geometry.homography import Homography, Point
from pipelines.geometry.vanishing_point import Line, vanishing_point


def line_residuals_px(lines: list[Line], point: Point) -> list[float]:
    """Perpendicular pixel distance from `point` to each (infinite) line."""
    out: list[float] = []
    px, py = point
    for (x1, y1), (x2, y2) in lines:
        dx, dy = x2 - x1, y2 - y1
        norm = float(np.hypot(dx, dy))
        if norm == 0:
            raise ValueError("degenerate line segment (zero length)")
        out.append(abs(dy * (px - x1) - dx * (py - y1)) / norm)
    return out


def level_camera_homography(
    depth_vanishing_point: Point,
    principal_point: Point,
    focal_length_px: float,
    camera_height_m: float,
) -> Homography:
    """Image px -> ground meters for a zero-roll camera at a known height.

    Builds the camera-frame ground axes (Y = depth direction through the
    vanishing point, X = the camera's horizontal axis made orthogonal to Y,
    up = X x Y flipped to point away from the floor), then intersects each
    pixel's viewing ray with the floor plane `up . P = -h`.
    """
    if focal_length_px <= 0 or camera_height_m <= 0:
        raise ValueError("focal length and camera height must be positive")
    cx, cy = principal_point
    f = focal_length_px
    k_inv = np.array([[1 / f, 0, -cx / f], [0, 1 / f, -cy / f], [0, 0, 1]])

    y_axis = k_inv @ np.array([*depth_vanishing_point, 1.0])
    y_axis /= np.linalg.norm(y_axis)
    ex = np.array([1.0, 0.0, 0.0])
    x_axis = ex - (ex @ y_axis) * y_axis
    x_axis /= np.linalg.norm(x_axis)
    up = np.cross(x_axis, y_axis)
    if up[1] > 0:  # camera +y points down in the image; "up" must point the other way
        up = -up

    h = camera_height_m
    m = np.vstack([-h * x_axis, -h * y_axis, up])
    matrix = m @ k_inv
    return Homography(matrix=matrix / matrix[2, 2])


def calibrate_level_camera(
    depth_lines: list[Line],
    principal_point: Point,
    focal_length_px: float,
    camera_height_m: float,
) -> tuple[Homography, Point, float]:
    """Fit the depth vanishing point and build the homography.

    Returns (homography, vanishing point, RMS line residual in px).
    """
    vp = vanishing_point(depth_lines)
    residuals = line_residuals_px(depth_lines, vp)
    rms = float(np.sqrt(np.mean(np.square(residuals))))
    return (
        level_camera_homography(vp, principal_point, focal_length_px, camera_height_m),
        vp,
        rms,
    )
