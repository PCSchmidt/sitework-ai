from __future__ import annotations

import json
from pathlib import Path

import pytest
from pipelines.geometry.calibrate import (
    CalibrationError,
    calibrate,
    load_correspondences,
    main,
)
from pipelines.schemas import RMS_GATE_PX

CLEAN_ROWS = [
    {"image_px": [0.0, 0.0], "world_m": [0.0, 0.0]},
    {"image_px": [100.0, 0.0], "world_m": [10.0, 0.0]},
    {"image_px": [100.0, 80.0], "world_m": [10.0, 8.0]},
    {"image_px": [0.0, 80.0], "world_m": [0.0, 8.0]},
    # 5th point: a homography has 8 DOF, so exactly 4 correspondences always
    # fit exactly (RMS == 0 regardless of noise). Over-determine with a 5th
    # consistent point so the noisy-point tests get a real residual.
    {"image_px": [50.0, 40.0], "world_m": [5.0, 4.0]},
]


def _write_points(tmp_path: Path, rows: list[dict[str, list[float]]]) -> Path:
    path = tmp_path / "points.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_load_correspondences_round_trips(tmp_path: Path) -> None:
    path = _write_points(tmp_path, CLEAN_ROWS)
    image_pts, world_pts = load_correspondences(path)
    assert image_pts[1] == (100.0, 0.0)
    assert world_pts[1] == (10.0, 0.0)


def test_load_correspondences_rejects_too_few_points(tmp_path: Path) -> None:
    path = _write_points(tmp_path, CLEAN_ROWS[:3])
    with pytest.raises(CalibrationError, match=">= 4"):
        load_correspondences(path)


def test_load_correspondences_rejects_malformed_row(tmp_path: Path) -> None:
    bad_rows = [*CLEAN_ROWS[:3], {"image_px": [1.0, 2.0]}]  # missing world_m
    path = _write_points(tmp_path, bad_rows)
    with pytest.raises(CalibrationError, match="malformed"):
        load_correspondences(path)


def test_calibrate_passes_gate_for_clean_correspondences() -> None:
    image_pts, world_pts = [tuple(r["image_px"]) for r in CLEAN_ROWS], [
        tuple(r["world_m"]) for r in CLEAN_ROWS
    ]
    record = calibrate("dock_north_01", image_pts, world_pts)  # type: ignore[arg-type]
    assert record["valid"] is True
    assert record["rms_px"] < RMS_GATE_PX
    assert record["camera_id"] == "dock_north_01"
    assert len(record["homography_px_to_m"]) == 3


def test_calibrate_fails_gate_for_noisy_correspondences() -> None:
    image_pts = [tuple(r["image_px"]) for r in CLEAN_ROWS]
    world_pts = [tuple(r["world_m"]) for r in CLEAN_ROWS]
    world_pts[4] = (world_pts[4][0] + 5.0, world_pts[4][1] - 3.0)  # gross outlier
    record = calibrate("dock_north_01", image_pts, world_pts)  # type: ignore[arg-type]
    assert record["valid"] is False
    assert record["rms_px"] > RMS_GATE_PX


def test_main_writes_calibration_file_and_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    points_path = _write_points(tmp_path, CLEAN_ROWS)
    out_dir = tmp_path / "calibration"
    monkeypatch.setattr(
        "sys.argv",
        [
            "calibrate.py",
            "--camera-id",
            "dock_north_01",
            "--points",
            str(points_path),
            "--out-dir",
            str(out_dir),
        ],
    )
    main()  # should not raise: clean points pass the gate
    out_file = out_dir / "dock_north_01.json"
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["valid"] is True
    assert data["camera_id"] == "dock_north_01"


def test_main_exits_nonzero_when_gate_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    noisy_rows = [dict(r) for r in CLEAN_ROWS]
    noisy_rows[4] = {"image_px": [50.0, 40.0], "world_m": [15.0, 5.0]}
    points_path = _write_points(tmp_path, noisy_rows)
    out_dir = tmp_path / "calibration"
    monkeypatch.setattr(
        "sys.argv",
        [
            "calibrate.py",
            "--camera-id",
            "dock_north_01",
            "--points",
            str(points_path),
            "--out-dir",
            str(out_dir),
        ],
    )
    with pytest.raises(SystemExit, match="FAILED quality gate"):
        main()
    # still written for auditability, per the tool's contract
    assert (out_dir / "dock_north_01.json").exists()
