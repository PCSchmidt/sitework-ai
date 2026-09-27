"""Camera-motion compensation for calibrations made on one reference frame.

A calibration maps pixels of *one* view to ground meters. If the camera pans
or tilts (the dock_north_01 demo clip drifts up to ~65 px over 12 s), every
other frame's pixels are in a slightly different view, and ground points
drift with it. Since the background is far away and mostly static, the
frame -> reference-frame mapping is itself well modeled by an image
homography, estimated here from ORB feature matches with RANSAC (the same
idea as the camera-motion compensation step in trackers like BoT-SORT).

Composing it with the calibration (`Calibration.for_frame`) gives each frame
its own pixel -> ground homography. Moving objects (people, vehicles) are a
minority of matched features and fall out as RANSAC outliers.
"""

from __future__ import annotations

import cv2
import numpy as np

# Below this many RANSAC inliers the estimate is treated as unreliable and the
# caller falls back to the last good one (or identity).
MIN_INLIERS = 40


class MotionCompensator:
    def __init__(self, reference_bgr: np.ndarray, n_features: int = 4000) -> None:
        self._orb = cv2.ORB_create(n_features)  # type: ignore[attr-defined]
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        gray = cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2GRAY)
        self._ref_kp, self._ref_desc = self._orb.detectAndCompute(gray, None)
        self._last_good: np.ndarray = np.eye(3)

    def frame_to_reference(self, image_bgr: np.ndarray) -> np.ndarray:
        """3x3 homography mapping this frame's pixels onto the reference frame's.

        Falls back to the last good estimate when matching fails (too few
        features/inliers), so a single blurry frame doesn't snap geometry.
        """
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        kp, desc = self._orb.detectAndCompute(gray, None)
        if desc is None or self._ref_desc is None or len(kp) < MIN_INLIERS:
            return self._last_good
        matches = self._matcher.match(desc, self._ref_desc)
        if len(matches) < MIN_INLIERS:
            return self._last_good
        src = np.array([kp[m.queryIdx].pt for m in matches], dtype=np.float32)
        dst = np.array([self._ref_kp[m.trainIdx].pt for m in matches], dtype=np.float32)
        h, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
        if h is None or inliers is None or int(inliers.sum()) < MIN_INLIERS:
            return self._last_good
        self._last_good = h / h[2, 2]
        return self._last_good
