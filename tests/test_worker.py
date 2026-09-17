from __future__ import annotations

from pathlib import Path

import fakeredis
import pytest
from agent.worker import AgentWorker
from pipelines.schemas import CalibrationQuality, IncidentState, Track, TrackletFrame, TrackState

_STATE = TrackState(cov_trace=0.01, age_frames=10, hits=10)
_CAL = CalibrationQuality(rms_px=1.0, valid=True)


def _track(track_id: int, x: float) -> Track:
    return Track(
        track_id=track_id,
        cls="person" if track_id == 42 else "forklift",
        confidence=0.9,
        bbox_px=(0, 0, 10, 10),
        ground_point_m=(x, 0.0),
        state=_STATE,
    )


def _golden_frames() -> list[TrackletFrame]:
    person_x = [5.0, 3.0, 1.2, 1.6]
    ts = [998.0, 999.0, 1000.0, 1001.0]
    return [
        TrackletFrame(
            camera_id="dock_north_01",
            frame_ts=t,
            seq=i,
            calibration_quality=_CAL,
            tracks=[_track(42, person_x[i]), _track(77, 0.0)],
        )
        for i, t in enumerate(ts)
    ]


def _seed_evidence(evidence_root: Path, event_id: str) -> None:
    event_dir = evidence_root / event_id
    event_dir.mkdir(parents=True)
    with (event_dir / "tracks.jsonl").open("w", encoding="utf-8") as fh:
        for frame in _golden_frames():
            fh.write(frame.model_dump_json() + "\n")


def _event_payload(event_id: str = "evt_test") -> dict[str, str]:
    from pipelines.schemas import Severity, TriggerEvent, TriggerMetrics

    event = TriggerEvent(
        event_id=event_id,
        trigger_ts=1000.0,
        camera_id="dock_north_01",
        rule_id="proximity_forklift_pedestrian",
        severity_hint=Severity.HIGH,
        metrics=TriggerMetrics(min_distance_m=1.2, duration_s=2.0, closing_speed_mps=1.8),
        involved_track_ids=[42, 77],
        track_window_ref=f"incidents/{event_id}/tracks.jsonl",
        cooldown_key=f"dock_north_01:proximity:{event_id}",
        calibration_quality=_CAL,
    )
    return {"payload": event.model_dump_json()}


@pytest.fixture
def worker(tmp_path: Path, fake_prime_agent_on_path) -> AgentWorker:
    client = fakeredis.FakeRedis()
    return AgentWorker(
        redis_client=client,
        workspace_root=tmp_path / "workspace",
        evidence_root=tmp_path / "evidence",
        consumer_name="test-consumer",
        prompt_timeout_s=10,
    )


def test_confirmed_when_agent_and_band3_agree(
    worker: AgentWorker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PRIME_AGENT_MODE", "run_incident")
    _seed_evidence(tmp_path / "evidence", "evt_test")
    from pipelines.schemas import TriggerEvent

    event = TriggerEvent.model_validate_json(_event_payload()["payload"])

    record = worker.process_one(event)

    assert record.state == IncidentState.CONFIRMED
    assert record.classification == "near_miss"
    assert record.verified_kinematics is not None
    assert abs(record.verified_kinematics.verified_min_distance_m - 1.2) < 1e-6
    assert record.rejection_reason is None


def test_needs_review_when_band3_rejects_agent_output(
    worker: AgentWorker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PRIME_AGENT_MODE", "wrong_answer")
    _seed_evidence(tmp_path / "evidence", "evt_test")
    from pipelines.schemas import TriggerEvent

    event = TriggerEvent.model_validate_json(_event_payload()["payload"])

    record = worker.process_one(event)

    assert record.state == IncidentState.NEEDS_REVIEW
    assert record.rejection_reason is not None
    assert "Band-3" in record.rejection_reason


def test_needs_review_when_no_result_written(
    worker: AgentWorker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PRIME_AGENT_MODE", "no_result")
    _seed_evidence(tmp_path / "evidence", "evt_test")
    from pipelines.schemas import TriggerEvent

    event = TriggerEvent.model_validate_json(_event_payload()["payload"])

    record = worker.process_one(event)

    assert record.state == IncidentState.NEEDS_REVIEW
    assert "no result.json" in record.rejection_reason


def test_needs_review_when_prime_agent_times_out(
    worker: AgentWorker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PRIME_AGENT_MODE", "hang")
    worker.prompt_timeout_s = 1.5
    _seed_evidence(tmp_path / "evidence", "evt_test")
    from pipelines.schemas import TriggerEvent

    event = TriggerEvent.model_validate_json(_event_payload()["payload"])

    record = worker.process_one(event)

    assert record.state == IncidentState.NEEDS_REVIEW
    assert "supervisory timeout" in record.rejection_reason


def test_needs_review_when_evidence_missing(worker: AgentWorker, tmp_path: Path) -> None:
    from pipelines.schemas import TriggerEvent

    event = TriggerEvent.model_validate_json(_event_payload("evt_missing")["payload"])
    record = worker.process_one(event)

    assert record.state == IncidentState.NEEDS_REVIEW
    assert "evidence window missing" in record.rejection_reason


def test_run_forever_processes_and_acks_queued_entry(
    tmp_path: Path, fake_prime_agent_on_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PRIME_AGENT_MODE", "run_incident")
    client = fakeredis.FakeRedis()
    from pipelines.vision.pipeline import TRIGGER_STREAM_KEY

    client.xadd(TRIGGER_STREAM_KEY, _event_payload())
    _seed_evidence(tmp_path / "evidence", "evt_test")

    w = AgentWorker(
        redis_client=client,
        workspace_root=tmp_path / "workspace",
        evidence_root=tmp_path / "evidence",
        consumer_name="c1",
        prompt_timeout_s=10,
    )
    for entry in w.reader.read(count=10, block_ms=None):
        w._handle(entry.entry_id, entry.payload)

    assert client.xpending(TRIGGER_STREAM_KEY, "agent-worker")["pending"] == 0
    assert (tmp_path / "workspace" / "incidents" / "evt_test" / "result.json").exists()
