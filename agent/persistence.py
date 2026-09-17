"""Sync-callable Postgres persistence for agent/worker.py (docs/12 M4).

worker.py's main loop is synchronous (subprocess-driven RPC calls block);
each persist call opens a short-lived asyncpg pool via `asyncio.run` rather
than juggling a long-lived pool across the sync/async boundary -- incident
volume here is event-driven and low (one RPC session per trigger), so a
connection per persist call has no meaningful cost, and it keeps this module
trivial to reason about. The API server (`api/main.py`) is the one process
that needs a long-lived pool, for request concurrency; this doesn't.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, Protocol, TypeVar

from api import repository
from api.db import DEFAULT_DSN, create_pool
from pipelines.schemas import IncidentRecord

_T = TypeVar("_T")


def _run_sync(coro: Coroutine[Any, Any, _T]) -> _T:
    """Runs `coro` to completion, safely regardless of whether the calling
    thread already has a running event loop.

    Production `worker.py` calls this from a plain sync context (subprocess-
    driven, no asyncio at all) where a bare `asyncio.run(coro)` would be
    fine -- but tests exercise the same code path from inside an async test
    function (to also `await` repository reads against the same database),
    and `asyncio.run()` raises "cannot be called from a running event loop"
    in that case. Running in a dedicated thread sidesteps the restriction in
    both contexts identically, at the cost of a thread per persist call --
    trivial overhead for this worker's event-driven, one-incident-at-a-time
    write volume.
    """
    result: dict[str, Any] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=_runner)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result["value"]  # type: ignore[no-any-return]


class Persister(Protocol):
    def persist(self, record: IncidentRecord) -> None: ...

    def persist_crash(self, event_id: str) -> None: ...


class PostgresPersister:
    """Writes `IncidentRecord`s (and their embedded `agent_run` stats, when
    present) to Postgres. `persist_crash` logs a run that never produced a
    record at all -- docs/05 §7: failure visibility matters as much as
    success visibility for the cognitive plane's observability."""

    def __init__(self, dsn: str = DEFAULT_DSN) -> None:
        self.dsn = dsn

    def persist(self, record: IncidentRecord) -> None:
        _run_sync(self._persist(record))

    async def _persist(self, record: IncidentRecord) -> None:
        pool = await create_pool(self.dsn)
        try:
            await repository.upsert_incident(pool, record)
            if record.agent_run is not None:
                await repository.insert_agent_run(
                    pool, record.event_id, str(record.state), record.agent_run
                )
        finally:
            await pool.close()

    def persist_crash(self, event_id: str) -> None:
        _run_sync(self._persist_crash(event_id))

    async def _persist_crash(self, event_id: str) -> None:
        pool = await create_pool(self.dsn)
        try:
            await repository.insert_agent_run(pool, event_id, "crashed", None)
        finally:
            await pool.close()


class NullPersister:
    """Default when no `--postgres-dsn` is given -- worker.py still returns
    complete `IncidentRecord`s from `process_one`, just doesn't write them
    anywhere (matches pre-M4 behavior; used throughout the existing test
    suite so those tests stay offline)."""

    def persist(self, record: IncidentRecord) -> None:
        return

    def persist_crash(self, event_id: str) -> None:
        return
