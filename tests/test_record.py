"""Showcase recorder helpers -- pipelines.vision.record (the GPU loop itself isn't unit-tested)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from pipelines.geometry.calibration_store import Calibration
from pipelines.geometry.level_camera import level_camera_homography
from pipelines.schemas import CalibrationQuality
from pipelines.vision.record import write_index, zone_polygon_px

# A level camera 1.4 m up looking down +Y, 1920x1080 frame, horizon at row 540.
CAL = Calibration(
    camera_id="cam",
    homography=level_camera_homography((960.0, 540.0), (960.0, 540.0), 1500.0, 1.4),
    quality=CalibrationQuality.from_rms(1.0),
)


def test_zone_polygon_round_trips_through_the_calibration() -> None:
    square_m = [(-1.0, 6.0), (1.0, 6.0), (1.0, 8.0), (-1.0, 8.0)]
    px = zone_polygon_px(square_m, CAL, (960.0, 1079.0))
    assert len(px) == 4 * 24  # densified edges, nothing behind the camera
    for x, y in px:
        gx, gy = CAL.homography.apply((x, y))
        assert -1.01 <= gx <= 1.01
        assert 5.99 <= gy <= 8.01
    assert px[0] == pytest.approx((960.0 - 1500.0 / 6.0, 540.0 + 1500.0 * 1.4 / 6.0), abs=0.1)


def test_zone_points_behind_the_camera_are_dropped() -> None:
    # spans from 5 m in front of the camera to 5 m behind it
    straddling = [(-1.0, -5.0), (1.0, -5.0), (1.0, 5.0), (-1.0, 5.0)]
    px = zone_polygon_px(straddling, CAL, (960.0, 1079.0))
    assert 0 < len(px) < 4 * 24
    assert all(y > 540.0 for _, y in px)  # every kept point projects below the horizon


def test_index_lists_cameras_with_events_first(tmp_path: Path) -> None:
    def write(camera_id: str, n_events: int, calibration: dict[str, object] | None) -> None:
        (tmp_path / camera_id).mkdir()
        payload = {
            "camera_id": camera_id,
            "name": camera_id.title(),
            "note": None,
            "duration_s": 10.0,
            "events": [{"t": float(i)} for i in range(n_events)],
            "calibration": calibration,
        }
        (tmp_path / camera_id / "showcase.json").write_text(json.dumps(payload), encoding="utf-8")

    write("a_quiet", 0, None)
    write("b_busy", 2, {"method": "level_camera", "valid": True, "rms_px": 1.2})
    write_index(tmp_path)
    rows = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert [r["camera_id"] for r in rows] == ["b_busy", "a_quiet"]
    assert rows[0]["calibration"] == {"method": "level_camera", "valid": True}
    assert rows[1]["calibration"] is None
    assert np.isclose(rows[0]["duration_s"], 10.0)
