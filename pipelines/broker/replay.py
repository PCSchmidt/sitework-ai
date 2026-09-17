"""Stream replay tooling (docs/12 M2): dump/reprocess a Redis stream's history.

For local dev and backfill -- e.g. replaying `trigger_events` since a given
time into a fresh agent-worker consumer group once it exists (M3), or
dumping `tracklets:{camera_id}` for offline debugging -- without a live
camera feed. Reads via XRANGE, independent of any consumer group, so it
never disturbs group offsets or pending-entry state.

Usage:
    uv run python -m pipelines.broker.replay --stream trigger_events
    uv run python -m pipelines.broker.replay --stream tracklets:dock_north_01 \
        --since 1789640000 --out replay.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator

import redis

from pipelines.broker.streams import _decode, _decode_payload


def replay_range(
    client: redis.Redis,
    stream_key: str,
    start: str = "-",
    end: str = "+",
    count: int | None = None,
) -> Iterator[tuple[str, dict[str, str]]]:
    """Yield (entry_id, payload) for entries in [start, end] (Redis XRANGE syntax)."""
    entries = client.xrange(stream_key, min=start, max=end, count=count) or []
    for entry_id, fields in entries:
        if entry_id is None or fields is None:
            continue
        yield _decode(entry_id), _decode_payload(fields)


def replay_since(
    client: redis.Redis, stream_key: str, since_ts: float, count: int | None = None
) -> Iterator[tuple[str, dict[str, str]]]:
    """Yield (entry_id, payload) for entries published at/after `since_ts` (unix seconds)."""
    start_id = f"{int(since_ts * 1000)}-0"
    yield from replay_range(client, stream_key, start=start_id, count=count)


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay a Redis stream's history (docs/12 M2)")
    ap.add_argument("--stream", required=True, help="e.g. trigger_events, tracklets:dock_north_01")
    ap.add_argument("--redis", default="redis://localhost:6379")
    ap.add_argument("--since", type=float, default=None, help="unix ts; default: full history")
    ap.add_argument("--count", type=int, default=None)
    ap.add_argument("--out", type=argparse.FileType("w", encoding="utf-8"), default=None)
    args = ap.parse_args()

    client = redis.Redis.from_url(args.redis)
    rows = (
        replay_since(client, args.stream, args.since, args.count)
        if args.since is not None
        else replay_range(client, args.stream, count=args.count)
    )

    out = args.out
    n = 0
    for entry_id, payload in rows:
        line = json.dumps({"entry_id": entry_id, **payload})
        if out:
            print(line, file=out)
        else:
            print(line)
        n += 1
    if out:
        out.close()
    print(f"replayed {n} entries from {args.stream}", file=sys.stderr)


if __name__ == "__main__":
    main()
