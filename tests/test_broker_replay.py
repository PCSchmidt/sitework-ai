from __future__ import annotations

import json
from pathlib import Path

import fakeredis
import pytest
from pipelines.broker import replay


@pytest.fixture
def client() -> fakeredis.FakeRedis:
    r = fakeredis.FakeRedis()
    # oldest -> newest: stream IDs must be strictly increasing
    r.xadd("s", {"payload": "a"}, id="1000-0")
    r.xadd("s", {"payload": "b"}, id="2000-0")
    r.xadd("s", {"payload": "c"}, id="3000-0")
    return r


def test_replay_range_returns_everything_by_default(client: fakeredis.FakeRedis) -> None:
    rows = list(replay.replay_range(client, "s"))
    assert [payload["payload"] for _id, payload in rows] == ["a", "b", "c"]


def test_replay_range_respects_count(client: fakeredis.FakeRedis) -> None:
    rows = list(replay.replay_range(client, "s", count=2))
    assert [payload["payload"] for _id, payload in rows] == ["a", "b"]


def test_replay_since_filters_to_entries_at_or_after_timestamp(client: fakeredis.FakeRedis) -> None:
    # entry "b" has id "2000-0" -> ts 2.0s; since=2.0 should include b and c, not a
    rows = list(replay.replay_since(client, "s", since_ts=2.0))
    assert [payload["payload"] for _id, payload in rows] == ["b", "c"]


def test_replay_returns_entry_ids_as_strings(client: fakeredis.FakeRedis) -> None:
    entry_id, _payload = next(replay.replay_range(client, "s", count=1))
    assert entry_id == "1000-0"
    assert isinstance(entry_id, str)


def test_main_writes_jsonl_to_out_file(
    client: fakeredis.FakeRedis, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(replay.redis.Redis, "from_url", classmethod(lambda cls, url: client))
    out_path = tmp_path / "out.jsonl"
    monkeypatch.setattr(
        "sys.argv",
        ["replay.py", "--stream", "s", "--out", str(out_path)],
    )
    replay.main()

    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    rows = [json.loads(line) for line in lines]
    assert [row["payload"] for row in rows] == ["a", "b", "c"]
    assert rows[0]["entry_id"] == "1000-0"


def test_main_respects_since_filter(
    client: fakeredis.FakeRedis, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(replay.redis.Redis, "from_url", classmethod(lambda cls, url: client))
    out_path = tmp_path / "out.jsonl"
    monkeypatch.setattr(
        "sys.argv",
        ["replay.py", "--stream", "s", "--since", "2.0", "--out", str(out_path)],
    )
    replay.main()

    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    rows = [json.loads(line) for line in lines]
    assert [row["payload"] for row in rows] == ["b", "c"]
