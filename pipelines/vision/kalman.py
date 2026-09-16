"""Per-track Kalman state estimation (docs/04 section 2, Tracking).

Constant-velocity model on bbox center + size:
  state x = [cx, cy, w, h, vx, vy, vw, vh]^T
The covariance trace is forwarded in telemetry as evidence quality
(TrackState.cov_trace in pipelines/schemas).
"""

from __future__ import annotations

import numpy as np


class KalmanBoxTracker:
    _NDIM = 4
    _DIM_X = 8

    def __init__(self, bbox: tuple[float, float, float, float], dt: float = 1.0) -> None:
        x1, y1, x2, y2 = bbox
        self.dt = dt
        self.x = np.zeros((self._DIM_X, 1))
        self.x[:4, 0] = [(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1]

        # state transition (constant velocity)
        self.F = np.eye(self._DIM_X)
        for i in range(self._NDIM):
            self.F[i, i + self._NDIM] = dt

        # measurement: observe [cx, cy, w, h]
        self.H = np.zeros((self._NDIM, self._DIM_X))
        self.H[: self._NDIM, : self._NDIM] = np.eye(self._NDIM)

        # covariances (defaults from the ByteTrack/Kalman literature)
        self.P = np.eye(self._DIM_X) * 10.0
        self.P[4:, 4:] *= 1000.0  # high initial velocity uncertainty
        self.Q = np.eye(self._DIM_X) * 0.01
        self.Q[4:, 4:] *= 0.1
        self.R = np.eye(self._NDIM) * 1.0

        self.hits = 1
        self.age = 0

    def predict(self) -> tuple[float, float, float, float]:
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        self.age += 1
        return self.bbox()

    def update(self, bbox: tuple[float, float, float, float]) -> None:
        x1, y1, x2, y2 = bbox
        z = np.array([(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1]).reshape(-1, 1)
        y = z - self.H @ self.x
        s = self.H @ self.P @ self.H.T + self.R
        k = self.P @ self.H.T @ np.linalg.inv(s)
        self.x = self.x + k @ y
        self.P = (np.eye(self._DIM_X) - k @ self.H) @ self.P
        self.hits += 1

    def bbox(self) -> tuple[float, float, float, float]:
        cx, cy, w, h = (float(self.x[i, 0]) for i in range(4))
        return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    def velocity_pxs(self) -> tuple[float, float]:
        return (float(self.x[4, 0]) / self.dt, float(self.x[5, 0]) / self.dt)

    def cov_trace(self) -> float:
        return float(np.trace(self.P[:4, :4]))
