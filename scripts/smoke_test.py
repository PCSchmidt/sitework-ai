"""Demo smoke test (docs/09 §6, M4 exit criterion S1).

Injects a synthetic `TriggerEvent` into the real `trigger_events` Redis
stream, drives it through `AgentWorker` (agent stubbed by default via the
same `tests/_fake_prime_agent.py` stand-in the test suite uses -- pass
`--real-agent` to drive the actual `prime-agent` CLI instead), asserts the
resulting incident lands in Postgres, and -- best-effort, since it requires
`uvicorn api.main:app` already running -- asserts the WS push is observed.

Usage:
    docker compose up -d redis postgres          # or your own instances
    uv run python -m api.main &                  # or: uvicorn api.main:app
    uv run python -m scripts.smoke_test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import redis
from agent.persistence import PostgresPersister
from agent.worker import AgentWorker
from pipelines.broker.streams import TRIGGER_STREAM_KEY
from pipelines.schemas import (
    CalibrationQuality,
    Severity,
    Track,
    TrackletFrame,
    TrackState,
    TriggerEvent,
    TriggerMetrics,
)

_FAKE_AGENT_SCRIPT = Path(__file__).parent.parent / "tests" / "_fake_prime_agent.py"


def _put_stub_agent_on_path(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        wrapper = bin_dir / "prime-agent.cmd"
        wrapper.write_text(f'@"{sys.executable}" "{_FAKE_AGENT_SCRIPT}" %*\r\n', encoding="utf-8")
    else:
        wrapper = bin_dir / "prime-agent"
        wrapper.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/sh
                exec "{sys.executable}" "{_FAKE_AGENT_SCRIPT}" "$@"
                """
            ),
            encoding="utf-8",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]
    os.environ["FAKE_PRIME_AGENT_MODE"] = "run_incident"


def _build_event_and_evidence(event_id: str, evidence_root: Path) -> TriggerEvent:
    cal = CalibrationQuality(rms_px=1.0, valid=True)
    state = TrackState(cov_trace=0.01, age_frames=10, hits=10)
    person_x = [5.0, 3.0, 1.2, 1.6]
    ts = [998.0, 999.0, 1000.0, 1001.0]
    frames = [
        TrackletFrame(
            camera_id="dock_north_01",
            frame_ts=t,
            seq=i,
            calibration_quality=cal,
            tracks=[
                Track(
                    track_id=42,
                    cls="person",
                    confidence=0.9,
                    bbox_px=(0, 0, 10, 10),
                    ground_point_m=(person_x[i], 0.0),
                    state=state,
                ),
                Track(
                    track_id=77,
                    cls="forklift",
                    confidence=0.9,
                    bbox_px=(0, 0, 10, 10),
                    ground_point_m=(0.0, 0.0),
                    state=state,
                ),
            ],
        )
        for i, t in enumerate(ts)
    ]
    event_dir = evidence_root / event_id
    event_dir.mkdir(parents=True, exist_ok=True)
    with (event_dir / "tracks.jsonl").open("w", encoding="utf-8") as fh:
        for frame in frames:
            fh.write(frame.model_dump_json() + "\n")

    return TriggerEvent(
        event_id=event_id,
        trigger_ts=1000.0,
        camera_id="dock_north_01",
        rule_id="proximity_forklift_pedestrian",
        severity_hint=Severity.HIGH,
        metrics=TriggerMetrics(min_distance_m=1.2, duration_s=2.0, closing_speed_mps=1.8),
        involved_track_ids=[42, 77],
        track_window_ref=f"incidents/{event_id}/tracks.jsonl",
        cooldown_key=f"dock_north_01:proximity:{event_id}",
        calibration_quality=cal,
    )


async def _connect_ws(ws_url: str) -> object | None:
    """Connects *before* the trigger fires -- Postgres NOTIFY (and this
    broadcast) is fire-and-forget, not queued, so a WS client that connects
    after the incident is persisted would never see the push (a real
    ordering bug this smoke test's first draft had)."""
    try:
        import websockets
    except ImportError:
        print("SKIP  websockets not installed -- cannot observe WS push")
        return None
    try:
        return await websockets.connect(ws_url, open_timeout=3)
    except (OSError, websockets.exceptions.WebSocketException) as exc:
        print(f"SKIP  could not reach {ws_url} ({exc}) -- is this repo's API server running?")
        return None


async def _wait_for_incident_created(ws: object, event_id: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)  # type: ignore[attr-defined]
        except TimeoutError:
            break
        msg = json.loads(raw)
        if msg.get("type") == "incident.created" and msg["data"]["event_id"] == event_id:
            return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--redis-url", default="redis://localhost:6379")
    ap.add_argument("--postgres-dsn", default="postgresql://sitewatch:sitewatch@localhost:5432/sitewatch")
    ap.add_argument("--ws-url", default="ws://localhost:8000/live/ws")
    ap.add_argument("--real-agent", action="store_true", help="drive the real prime-agent CLI")
    args = ap.parse_args()

    event_id = f"evt_smoke_{int(time.time())}"
    asyncio.run(_run(args, event_id))


async def _run(args: argparse.Namespace, event_id: str) -> None:
    from api import db, repository

    print(f"[1/5] building synthetic TriggerEvent {event_id} ...")
    print("[2/5] connecting WS before the trigger fires (NOTIFY is not queued) ...")
    ws = await _connect_ws(args.ws_url)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        evidence_root = tmp_path / "evidence"
        event = _build_event_and_evidence(event_id, evidence_root)

        if not args.real_agent:
            _put_stub_agent_on_path(tmp_path / "bin")

        print(f"[3/5] XADD-ing to {TRIGGER_STREAM_KEY} and driving AgentWorker ...")
        client = redis.Redis.from_url(args.redis_url)
        client.xadd(TRIGGER_STREAM_KEY, {"payload": event.model_dump_json()})

        worker = AgentWorker(
            redis_client=client,
            workspace_root=tmp_path / "workspace",
            evidence_root=evidence_root,
            consumer_name="smoke-test",
            prompt_timeout_s=150,
            persister=PostgresPersister(dsn=args.postgres_dsn),
        )
        entries = worker.reader.read(count=10, block_ms=5000)
        found = [e for e in entries if event_id in e.payload.get("payload", "")]
        if not found:
            raise SystemExit(f"FAIL  {event_id} never appeared on {TRIGGER_STREAM_KEY}")

        # The WS listener has to be running concurrently with (not after)
        # the worker's persist call, for the same NOTIFY-isn't-queued reason.
        ws_task = (
            asyncio.ensure_future(_wait_for_incident_created(ws, event_id, timeout_s=10.0))
            if ws is not None
            else None
        )
        for entry in found:
            await asyncio.to_thread(worker._handle, entry.entry_id, entry.payload)

    print("[4/5] checking Postgres for the confirmed incident ...")
    pool = await db.create_pool(args.postgres_dsn)
    try:
        record = await repository.get_incident(pool, event_id)
        if record is None:
            raise SystemExit(f"FAIL  no incident row for {event_id}")
        print(f"      incident.state={record.state} classification={record.classification}")
    finally:
        await pool.close()

    print("[5/5] checking WS incident.created push (best-effort) ...")
    observed = await ws_task if ws_task is not None else False
    if ws is not None:
        await ws.close()  # type: ignore[attr-defined]
    print(f"      WS push observed: {observed}")

    print(f"\nPASS  {event_id}: broker -> worker -> Postgres" + (" -> WS" if observed else ""))


if __name__ == "__main__":
    main()
