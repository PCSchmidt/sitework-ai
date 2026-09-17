"""Redis Streams broker hardening (docs/02 §2/§6, docs/12 M2).

M1 shipped `XADD ... MAXLEN ~N` (count-based, approximate) on every publish.
This module replaces that with the actual documented contract:

- **Time-based retention** (`trim_to_retention`, via `XTRIM ... MINID`):
  docs/02 §2 calls the broker a "short retention ring buffer (5 min) for
  agent context windows", and §6's failure-mode table says "Redis stream
  retention 1 h locally" for `trigger_events` while the agent is down.
  Count-based MAXLEN can't express either of those; MINID trimming can,
  because Redis stream IDs default to `{unix_ms}-{seq}`.
- **Consumer groups** (`ensure_group`, `ConsumerGroupReader`): the
  fire-and-forget XADD producer side doesn't change, but a reliable
  consumer (the M3 agent worker) needs XREADGROUP + XACK so a crashed
  consumer's in-flight entries aren't silently lost -- `claim_stale`
  reclaims them via XAUTOCLAIM, per docs/02 §6 "Broker down ... vision
  worker buffers ... reconnects" being matched on the consumer side too.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import redis
from redis.exceptions import ResponseError

# docs/02 §2: "short retention ring buffer (5 min) for agent context windows"
TRACKLET_RETENTION_S = 5 * 60
# docs/02 §6 failure-mode table: "Redis stream retention 1 h locally"
TRIGGER_RETENTION_S = 60 * 60

# Stream key naming (docs/06 §2). Defined here, not in pipelines.vision.pipeline
# (the fast-path producer that also uses them), so consumers that only need the
# key names -- agent/worker.py, evaluation/agent_eval.py -- don't have to import
# that module and pull in its torch/ultralytics dependency chain just for two
# string constants.
STREAM_KEY_PREFIX = "tracklets"
TRIGGER_STREAM_KEY = "trigger_events"


def _minid_for_retention(retention_s: float, now: float | None = None) -> str:
    now = now if now is not None else time.time()
    cutoff_ms = int((now - retention_s) * 1000)
    return f"{max(cutoff_ms, 0)}-0"


def trim_to_retention(
    client: redis.Redis, stream_key: str, retention_s: float, now: float | None = None
) -> int:
    """XTRIM the stream down to `retention_s` of history. Returns entries removed."""
    minid = _minid_for_retention(retention_s, now)
    result: int = client.xtrim(stream_key, minid=minid, approximate=True)
    return result


def ensure_group(client: redis.Redis, stream_key: str, group_name: str) -> None:
    """Idempotent `XGROUP CREATE ... MKSTREAM`: safe to call on every consumer start."""
    try:
        client.xgroup_create(stream_key, group_name, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


@dataclass(frozen=True)
class StreamEntry:
    entry_id: str
    payload: dict[str, str]


def _decode(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _decode_payload(fields: dict[Any, Any]) -> dict[str, str]:
    return {_decode(k): _decode(v) for k, v in fields.items()}


def _parse_xread_response(resp: Any) -> list[StreamEntry]:
    if not resp:
        return []
    entries: list[StreamEntry] = []
    for _stream_key, stream_entries in resp:
        for entry_id, fields in stream_entries:
            entries.append(StreamEntry(entry_id=_decode(entry_id), payload=_decode_payload(fields)))
    return entries


class ConsumerGroupReader:
    """XREADGROUP-based consumer: ack on success, reclaim stale pending on crash recovery.

    Pairs with a stream a producer XADDs into (e.g. `trigger_events`).
    Creates its consumer group on construction unless `create_group=False`.
    """

    def __init__(
        self,
        client: redis.Redis,
        stream_key: str,
        group_name: str,
        consumer_name: str,
        create_group: bool = True,
    ) -> None:
        self.client = client
        self.stream_key = stream_key
        self.group_name = group_name
        self.consumer_name = consumer_name
        if create_group:
            ensure_group(client, stream_key, group_name)

    def read(self, count: int = 10, block_ms: int | None = 1000) -> list[StreamEntry]:
        """New entries never delivered to any consumer in this group."""
        resp = self.client.xreadgroup(
            self.group_name,
            self.consumer_name,
            {self.stream_key: ">"},
            count=count,
            block=block_ms,
        )
        return _parse_xread_response(resp)

    def ack(self, entry_id: str) -> None:
        self.client.xack(self.stream_key, self.group_name, entry_id)

    def claim_stale(self, min_idle_ms: int, count: int = 10) -> list[StreamEntry]:
        """Reclaim entries idle >= min_idle_ms: another consumer died mid-processing."""
        _cursor, entries, _deleted = self.client.xautoclaim(
            self.stream_key,
            self.group_name,
            self.consumer_name,
            min_idle_time=min_idle_ms,
            count=count,
        )
        return [
            StreamEntry(entry_id=_decode(entry_id), payload=_decode_payload(fields))
            for entry_id, fields in entries
        ]
