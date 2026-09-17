from __future__ import annotations

import json
from pathlib import Path

import av
import numpy as np
import pytest
from pipelines.schemas import (
    CalibrationQuality,
    Severity,
    TrackletFrame,
    TriggerEvent,
    TriggerMetrics,
)
from pipelines.vision.evidence import EvidenceCapture

VALID_QUALITY = CalibrationQuality(rms_px=1.0, valid=True)
IMAGE = np.zeros((32, 32, 3), dtype=np.uint8)


def _tracklet(ts: float, seq: int) -> TrackletFrame:
    return TrackletFrame(
        camera_id="cam1", frame_ts=ts, seq=seq, calibration_quality=VALID_QUALITY, tracks=[]
    )


def _trigger_event(event_id: str, trigger_ts: float) -> TriggerEvent:
    return TriggerEvent(
        event_id=event_id,
        trigger_ts=trigger_ts,
        camera_id="cam1",
        rule_id="test_rule",
        severity_hint=Severity.HIGH,
        metrics=TriggerMetrics(),
        involved_track_ids=[1],
        track_window_ref=f"incidents/{event_id}/tracks.jsonl",
        clip_ref=f"incidents/{event_id}/clip.mp4",
        cooldown_key="cam1:zone_intrusion:1",
        calibration_quality=VALID_QUALITY,
    )


def test_on_trigger_seeds_window_with_pre_trigger_buffer(tmp_path: Path) -> None:
    capture = EvidenceCapture(out_dir=tmp_path, pre_window_s=3.0, post_window_s=2.0)
    for ts in range(5):  # 0..4, buffered as they arrive
        capture.on_frame("cam1", IMAGE, _tracklet(float(ts), ts))

    event = _trigger_event("evt_1", trigger_ts=4.0)
    capture.on_trigger("cam1", IMAGE, _tracklet(4.0, 4), [event])

    window = capture._open_windows["evt_1"]
    # pre_window_s=3.0 -> frames with ts >= 4.0 - 3.0 = 1.0 are seeded: ts 1,2,3,4
    assert sorted(f.ts for f in window.buffered) == [1.0, 2.0, 3.0, 4.0]


def test_window_finalizes_and_writes_tracks_and_clip_after_post_window(tmp_path: Path) -> None:
    capture = EvidenceCapture(out_dir=tmp_path, pre_window_s=1.0, post_window_s=2.0)
    capture.on_frame("cam1", IMAGE, _tracklet(0.0, 0))
    event = _trigger_event("evt_1", trigger_ts=0.0)
    capture.on_trigger("cam1", IMAGE, _tracklet(0.0, 0), [event])

    # frames continue arriving after the trigger; window stays open until ts >= 2.0
    written = capture.on_frame("cam1", IMAGE, _tracklet(1.0, 1))
    assert written == []
    assert "evt_1" in capture._open_windows

    written = capture.on_frame("cam1", IMAGE, _tracklet(2.0, 2))
    assert len(written) == 2
    assert "evt_1" not in capture._open_windows

    tracks_path = tmp_path / "evt_1" / "tracks.jsonl"
    clip_path = tmp_path / "evt_1" / "clip.mp4"
    assert tracks_path.exists()
    assert clip_path.exists()

    lines = tracks_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3  # ts 0.0, 1.0, 2.0
    parsed = [json.loads(line) for line in lines]
    assert [row["frame_ts"] for row in parsed] == [0.0, 1.0, 2.0]


def test_clip_file_is_a_valid_video_with_expected_frame_count(tmp_path: Path) -> None:
    capture = EvidenceCapture(out_dir=tmp_path, pre_window_s=0.5, post_window_s=0.5)
    event = _trigger_event("evt_clip", trigger_ts=0.0)
    capture.on_trigger("cam1", IMAGE, _tracklet(0.0, 0), [event])
    capture.on_frame("cam1", IMAGE, _tracklet(0.0, 0))
    capture.on_frame("cam1", IMAGE, _tracklet(0.3, 1))
    # ts=0.6 is past end_ts=0.5: it triggers finalization but isn't itself included
    # in the window (only frames with ts <= end_ts are captured).
    capture.on_frame("cam1", IMAGE, _tracklet(0.6, 2))

    clip_path = tmp_path / "evt_clip" / "clip.mp4"
    assert clip_path.exists()
    with av.open(str(clip_path)) as container:
        stream = container.streams.video[0]
        frame_count = sum(1 for _ in container.decode(stream))
    assert frame_count == 2


def test_flush_all_finalizes_regardless_of_end_ts(tmp_path: Path) -> None:
    capture = EvidenceCapture(out_dir=tmp_path, pre_window_s=1.0, post_window_s=100.0)
    event = _trigger_event("evt_flush", trigger_ts=0.0)
    capture.on_trigger("cam1", IMAGE, _tracklet(0.0, 0), [event])
    capture.on_frame("cam1", IMAGE, _tracklet(0.0, 0))

    assert (tmp_path / "evt_flush" / "tracks.jsonl").exists() is False
    written = capture.flush_all()
    assert len(written) == 2
    assert (tmp_path / "evt_flush" / "tracks.jsonl").exists()


def test_on_trigger_is_idempotent_for_duplicate_event_id(tmp_path: Path) -> None:
    capture = EvidenceCapture(out_dir=tmp_path, pre_window_s=1.0, post_window_s=1.0)
    event = _trigger_event("evt_dup", trigger_ts=0.0)
    capture.on_trigger("cam1", IMAGE, _tracklet(0.0, 0), [event])
    capture.on_trigger(
        "cam1", IMAGE, _tracklet(0.0, 0), [event]
    )  # duplicate, should not reset window
    assert len(capture._open_windows) == 1


def test_rolling_buffer_evicts_frames_older_than_retention(tmp_path: Path) -> None:
    capture = EvidenceCapture(out_dir=tmp_path, pre_window_s=2.0, post_window_s=1.0)
    for ts in range(10):
        capture.on_frame("cam1", IMAGE, _tracklet(float(ts), ts))
    recent = capture._recent["cam1"]
    # retention defaults to pre_window_s=2.0; at ts=9 only ts>=7 should remain
    assert min(f.ts for f in recent) >= 7.0


@pytest.mark.parametrize("out_dir_name", ["nested/incident/dir"])
def test_finalize_creates_nested_out_dir(tmp_path: Path, out_dir_name: str) -> None:
    out_dir = tmp_path / out_dir_name
    capture = EvidenceCapture(out_dir=out_dir, pre_window_s=0.5, post_window_s=0.5)
    event = _trigger_event("evt_nested", trigger_ts=0.0)
    capture.on_trigger("cam1", IMAGE, _tracklet(0.0, 0), [event])
    capture.on_frame("cam1", IMAGE, _tracklet(0.0, 0))
    capture.on_frame("cam1", IMAGE, _tracklet(0.5, 1))
    assert (out_dir / "evt_nested" / "tracks.jsonl").exists()
