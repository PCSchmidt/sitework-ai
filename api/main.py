"""FastAPI delivery plane (docs/06 §4-5, M4).

REST surface backed by Postgres (`api/repository.py`) for incidents/reviews/
kpis, and directly by `config/*.yaml` (already the validated source of truth,
`pipelines/config/loader.py`) for cameras/zones/rules -- no second, driftable
copy of config in the database.

WS incident push uses Postgres LISTEN/NOTIFY (`api/schema.sql`'s
`incidents_notify` trigger) rather than an in-process queue, because
`agent/worker.py` and this API are separate processes -- NOTIFY is the one
mechanism that reaches across that boundary without adding a second broker.
`frame.ticker` (live track positions, docs/06 §5) isn't wired yet: bridging
Redis's per-camera tracklet streams to WS is real remaining work, not done
in this pass.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pipelines.config.loader import load_cameras, load_rules, load_zones
from pydantic import BaseModel

from api import repository
from api.db import DEFAULT_DSN, create_pool, init_schema

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks connected `/live/ws` clients for the incident-push broadcast."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def broadcast(self, message: dict[str, object]) -> None:
        dead = []
        for client in self._clients:
            try:
                await client.send_json(message)
            except Exception:
                dead.append(client)
        for client in dead:
            self._clients.discard(client)


async def _push_incident_update(
    pool: asyncpg.Pool, manager: ConnectionManager, payload: str
) -> None:
    data = json.loads(payload)
    record = await repository.get_incident(pool, data["event_id"])
    if record is None:
        return
    event_type = "incident.created" if data["op"] == "INSERT" else "incident.updated"
    await manager.broadcast({"type": event_type, "data": record.model_dump(mode="json")})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    dsn = os.environ.get("DATABASE_URL", DEFAULT_DSN)
    pool = await create_pool(dsn)
    await init_schema(pool)
    app.state.pool = pool
    manager = ConnectionManager()
    app.state.manager = manager

    listen_conn = await asyncpg.connect(dsn=dsn)
    # Keeps a strong reference to each fire-and-forget broadcast task -- an
    # unreferenced asyncio.Task can be garbage-collected mid-run.
    background_tasks: set[asyncio.Task[None]] = set()

    def _on_notify(_conn: object, _pid: int, _channel: str, payload: str) -> None:
        task = asyncio.create_task(_push_incident_update(pool, manager, payload))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    await listen_conn.add_listener("incident_change", _on_notify)
    app.state.listen_conn = listen_conn
    try:
        yield
    finally:
        await listen_conn.close()
        await pool.close()


app = FastAPI(title="SiteWatch AI API", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/cameras")
def cameras() -> list[dict[str, object]]:
    return [c.model_dump() for c in load_cameras().cameras]


@app.get("/api/v1/cameras/{camera_id}/health")
def camera_health(camera_id: str) -> dict[str, object]:
    cams = {c.id: c for c in load_cameras().cameras}
    if camera_id not in cams:
        raise HTTPException(status_code=404, detail="unknown camera")
    # Stream Watchdog sub-agent (docs/05 §1) lands at M5; until then this
    # reports config presence only, not live stream health.
    return {"camera_id": camera_id, "status": "unknown", "watchdog": "not yet wired (M5)"}


@app.get("/api/v1/zones")
def zones() -> list[dict[str, object]]:
    return [z.model_dump() for z in load_zones().zones]


@app.get("/api/v1/rules")
def rules() -> list[dict[str, object]]:
    return [r.model_dump(mode="json") for r in load_rules().rules]


@app.get("/api/v1/incidents")
async def list_incidents(
    request: Request,
    from_ts: float | None = None,
    to_ts: float | None = None,
    severity: str | None = None,
    camera: str | None = None,
    state: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, object]]:
    pool: asyncpg.Pool = request.app.state.pool
    records = await repository.list_incidents(
        pool,
        ts_from=from_ts,
        ts_to=to_ts,
        severity=severity,
        camera_id=camera,
        state=state,
        limit=limit,
        offset=offset,
    )
    return [r.model_dump(mode="json") for r in records]


@app.get("/api/v1/incidents/{event_id}")
async def get_incident(event_id: str, request: Request) -> dict[str, object]:
    pool: asyncpg.Pool = request.app.state.pool
    record = await repository.get_incident(pool, event_id)
    if record is None:
        raise HTTPException(status_code=404, detail="unknown incident")
    return record.model_dump(mode="json")


class ReviewRequest(BaseModel):
    reviewer: str
    decision: str
    note: str | None = None


@app.post("/api/v1/incidents/{event_id}/review")
async def review_incident(
    event_id: str, body: ReviewRequest, request: Request
) -> dict[str, str]:
    pool: asyncpg.Pool = request.app.state.pool
    ok = await repository.insert_review(pool, event_id, body.reviewer, body.decision, body.note)
    if not ok:
        raise HTTPException(status_code=404, detail="unknown incident")
    return {"status": "recorded"}


@app.get("/api/v1/kpis")
async def kpis(request: Request, window: float = 24.0) -> dict[str, object]:
    pool: asyncpg.Pool = request.app.state.pool
    return await repository.kpis(pool, window_hours=window)


@app.websocket("/live/ws")
async def live_ws(websocket: WebSocket) -> None:
    manager: ConnectionManager = websocket.app.state.manager
    await manager.connect(websocket)
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            # "subscribe {camera_ids}" (docs/06 §5) is a no-op until
            # frame.ticker exists -- every client gets every incident push.
    except WebSocketDisconnect:
        manager.disconnect(websocket)
