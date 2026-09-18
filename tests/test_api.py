from __future__ import annotations

import json
from pathlib import Path

import pytest
from api import repository
from api.main import app
from fastapi.testclient import TestClient
from pipelines.schemas import Classification, IncidentRecord, IncidentState, Severity

from conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.integration


def _record(event_id: str = "evt_api_test") -> IncidentRecord:
    return IncidentRecord(
        event_id=event_id,
        camera_id="dock_north_01",
        trigger_ts=1000.0,
        severity=Severity.HIGH,
        state=IncidentState.CONFIRMED,
        classification=Classification.NEAR_MISS,
        narrative_md="Worker inside exclusion envelope.",
        rule_citations=["proximity_forklift_pedestrian"],
    )


@pytest.fixture
def client(pg_pool, monkeypatch: pytest.MonkeyPatch):
    # pg_pool already verified reachability + truncated tables; point the
    # app's own lifespan-created pool at the same database.
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    with TestClient(app) as c:
        yield c


def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_cameras_served_from_config(client: TestClient) -> None:
    resp = client.get("/api/v1/cameras")
    assert resp.status_code == 200
    ids = {c["id"] for c in resp.json()}
    assert "dock_north_01" in ids


def test_camera_health_unknown_camera_404(client: TestClient) -> None:
    resp = client.get("/api/v1/cameras/does_not_exist/health")
    assert resp.status_code == 404


def test_camera_health_known_camera(client: TestClient) -> None:
    resp = client.get("/api/v1/cameras/dock_north_01/health")
    assert resp.status_code == 200
    assert resp.json()["camera_id"] == "dock_north_01"


def test_zones_and_rules_served_from_config(client: TestClient) -> None:
    assert client.get("/api/v1/zones").status_code == 200
    rules_resp = client.get("/api/v1/rules")
    assert rules_resp.status_code == 200
    ids = {r["id"] for r in rules_resp.json()}
    assert "proximity_forklift_pedestrian" in ids


async def test_incident_list_and_get(client: TestClient, pg_pool) -> None:
    await repository.upsert_incident(pg_pool, _record())

    listed = client.get("/api/v1/incidents")
    assert listed.status_code == 200
    assert [i["event_id"] for i in listed.json()] == ["evt_api_test"]

    fetched = client.get("/api/v1/incidents/evt_api_test")
    assert fetched.status_code == 200
    assert fetched.json()["classification"] == "near_miss"

    missing = client.get("/api/v1/incidents/evt_nope")
    assert missing.status_code == 404


async def test_incident_list_filters_by_camera(client: TestClient, pg_pool) -> None:
    await repository.upsert_incident(pg_pool, _record("evt_x"))
    resp = client.get("/api/v1/incidents", params={"camera": "warehouse_aisle_01"})
    assert resp.json() == []


async def test_review_endpoint(client: TestClient, pg_pool) -> None:
    await repository.upsert_incident(pg_pool, _record())

    ok = client.post(
        "/api/v1/incidents/evt_api_test/review",
        json={"reviewer": "chris", "decision": "accepted", "note": "confirmed by cctv"},
    )
    assert ok.status_code == 200

    missing = client.post(
        "/api/v1/incidents/evt_nope/review", json={"reviewer": "chris", "decision": "accepted"}
    )
    assert missing.status_code == 404


async def test_kpis_endpoint(client: TestClient, pg_pool) -> None:
    await repository.upsert_incident(pg_pool, _record())
    resp = client.get("/api/v1/kpis", params={"window": 1e9})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_incidents"] == 1


def test_ws_ping_pong(client: TestClient) -> None:
    with client.websocket_connect("/live/ws") as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


async def test_ws_receives_incident_created_push(client: TestClient, pg_pool) -> None:
    with client.websocket_connect("/live/ws") as ws:
        await repository.upsert_incident(pg_pool, _record("evt_ws_push"))
        message = ws.receive_json()
    assert message["type"] == "incident.created"
    assert message["data"]["event_id"] == "evt_ws_push"


def test_evidence_tracks_404_when_missing(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("api.main.WORKSPACE_ROOT", tmp_path)
    resp = client.get("/api/v1/incidents/evt_missing/evidence/tracks")
    assert resp.status_code == 404


def test_evidence_tracks_returns_parsed_frames(
    client: TestClient, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("api.main.WORKSPACE_ROOT", tmp_path)
    incident_dir = tmp_path / "incidents" / "evt_evidence"
    incident_dir.mkdir(parents=True)
    (incident_dir / "tracks.jsonl").write_text(
        json.dumps({"camera_id": "dock_north_01", "frame_ts": 1.0}) + "\n", encoding="utf-8"
    )
    resp = client.get("/api/v1/incidents/evt_evidence/evidence/tracks")
    assert resp.status_code == 200
    assert resp.json() == [{"camera_id": "dock_north_01", "frame_ts": 1.0}]


def test_evidence_tracks_rejects_path_traversal(client: TestClient) -> None:
    resp = client.get("/api/v1/incidents/..%2F..%2Fetc/evidence/tracks")
    assert resp.status_code == 404


def test_evidence_clip_404_when_missing(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("api.main.WORKSPACE_ROOT", tmp_path)
    resp = client.get("/api/v1/incidents/evt_missing/evidence/clip")
    assert resp.status_code == 404


async def test_shift_report_renders_html(client: TestClient, pg_pool) -> None:
    await repository.upsert_incident(pg_pool, _record("evt_shift"))
    resp = client.get("/api/v1/shift-report", params={"from_ts": 0, "to_ts": 2_000_000_000})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "evt_shift" in resp.text


def test_shift_report_out_of_range_timestamp_does_not_500(client: TestClient) -> None:
    # 1e12 seconds since epoch is year 33658 -- datetime.fromtimestamp can't
    # represent it. A bad/typo'd query param should render a clean placeholder,
    # not crash the endpoint (real bug: this used to be an unhandled 500).
    resp = client.get("/api/v1/shift-report", params={"from_ts": 0, "to_ts": 1e12})
    assert resp.status_code == 200
    assert "out of range" in resp.text
