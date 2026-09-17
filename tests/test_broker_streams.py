from __future__ import annotations

import time

import fakeredis
import pytest
from pipelines.broker.streams import ConsumerGroupReader, ensure_group, trim_to_retention


@pytest.fixture
def client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis()


def test_trim_to_retention_drops_entries_older_than_window(client: fakeredis.FakeRedis) -> None:
    now = 1_000_000.0  # seconds
    old_ts_ms = int((now - 400) * 1000)  # 400s old
    recent_ts_ms = int((now - 10) * 1000)  # 10s old
    client.xadd("s", {"payload": "old"}, id=f"{old_ts_ms}-0")
    client.xadd("s", {"payload": "recent"}, id=f"{recent_ts_ms}-0")

    trim_to_retention(client, "s", retention_s=60, now=now)

    remaining = client.xrange("s")
    assert len(remaining) == 1
    assert remaining[0][1][b"payload"] == b"recent"


def test_trim_to_retention_keeps_everything_within_window(client: fakeredis.FakeRedis) -> None:
    now = 1_000_000.0
    for offset in (30, 10, 5):  # oldest -> newest: stream IDs must be strictly increasing
        ts_ms = int((now - offset) * 1000)
        client.xadd("s", {"payload": str(offset)}, id=f"{ts_ms}-0")

    trim_to_retention(client, "s", retention_s=60, now=now)

    assert client.xlen("s") == 3


def test_ensure_group_is_idempotent(client: fakeredis.FakeRedis) -> None:
    ensure_group(client, "s", "g")
    ensure_group(client, "s", "g")  # must not raise BUSYGROUP
    groups = client.xinfo_groups("s")
    assert len(groups) == 1


def test_ensure_group_creates_stream_if_missing(client: fakeredis.FakeRedis) -> None:
    assert not client.exists("brand_new_stream")
    ensure_group(client, "brand_new_stream", "g")
    assert client.exists("brand_new_stream")


class TestConsumerGroupReader:
    def test_read_returns_only_new_entries(self, client: fakeredis.FakeRedis) -> None:
        client.xadd("s", {"payload": "a"})
        reader = ConsumerGroupReader(client, "s", "g", "c1")
        first = reader.read(count=10, block_ms=None)
        assert len(first) == 1
        assert first[0].payload == {"payload": "a"}

        second = reader.read(count=10, block_ms=None)
        assert second == []

    def test_ack_removes_entry_from_pending(self, client: fakeredis.FakeRedis) -> None:
        client.xadd("s", {"payload": "a"})
        reader = ConsumerGroupReader(client, "s", "g", "c1")
        [entry] = reader.read(count=10, block_ms=None)

        pending_before = client.xpending("s", "g")
        assert pending_before["pending"] == 1

        reader.ack(entry.entry_id)
        pending_after = client.xpending("s", "g")
        assert pending_after["pending"] == 0

    def test_two_consumers_in_same_group_split_entries(self, client: fakeredis.FakeRedis) -> None:
        client.xadd("s", {"payload": "a"})
        client.xadd("s", {"payload": "b"})
        reader1 = ConsumerGroupReader(client, "s", "g", "c1")
        reader2 = ConsumerGroupReader(client, "s", "g", "c2", create_group=False)

        all_entries = reader1.read(count=10, block_ms=None) + reader2.read(count=10, block_ms=None)
        # both consumers pull from the same unread pointer; between them they see
        # each entry exactly once (no duplicate delivery within the group)
        assert len(all_entries) == 2

    def test_claim_stale_reclaims_unacked_entries(self, client: fakeredis.FakeRedis) -> None:
        client.xadd("s", {"payload": "a"})
        crashed = ConsumerGroupReader(client, "s", "g", "consumer_that_crashed")
        [entry] = crashed.read(count=10, block_ms=None)
        # never acked -- simulate the consumer dying before it could ack

        time.sleep(0.05)
        rescuer = ConsumerGroupReader(client, "s", "g", "rescuer", create_group=False)
        reclaimed = rescuer.claim_stale(min_idle_ms=10)

        assert len(reclaimed) == 1
        assert reclaimed[0].entry_id == entry.entry_id
        rescuer.ack(reclaimed[0].entry_id)
        assert client.xpending("s", "g")["pending"] == 0

    def test_claim_stale_ignores_recently_delivered_entries(
        self, client: fakeredis.FakeRedis
    ) -> None:
        client.xadd("s", {"payload": "a"})
        reader = ConsumerGroupReader(client, "s", "g", "c1")
        reader.read(count=10, block_ms=None)  # delivered just now, still "fresh"

        reclaimed = reader.claim_stale(min_idle_ms=60_000)
        assert reclaimed == []
