from __future__ import annotations

import os
import socket
import stat
import sys
import textwrap
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import pytest
from api.db import init_schema

_FAKE_SCRIPT = Path(__file__).parent / "_fake_prime_agent.py"

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://sitewatch:sitewatch@localhost:5432/sitewatch"
)


def _tcp_reachable(dsn: str, timeout: float = 0.3) -> bool:
    """Cheap pre-check so 20+ integration tests skip in well under a second
    when there's no local Postgres, instead of each waiting out asyncpg's
    own (much longer) connection-retry/backoff timeout."""
    parts = urlsplit(dsn)
    try:
        with socket.create_connection((parts.hostname, parts.port or 5432), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture
def fake_prime_agent_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Puts a stand-in `prime-agent` executable on PATH (tests/_fake_prime_agent.py).

    Real `prime-agent` isn't available in CI/most dev shells -- spike-01
    already validated the real CLI end to end (docs/spikes/spike-01-*); these
    tests validate PrimeAdapter/AgentWorker's own plumbing (timeout handling,
    file I/O, Band-3 gating) against a controllable stand-in instead.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    if sys.platform == "win32":
        wrapper = bin_dir / "prime-agent.cmd"
        wrapper.write_text(
            f'@"{sys.executable}" "{_FAKE_SCRIPT}" %*\r\n', encoding="utf-8"
        )
    else:
        wrapper = bin_dir / "prime-agent"
        wrapper.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/sh
                exec "{sys.executable}" "{_FAKE_SCRIPT}" "$@"
                """
            ),
            encoding="utf-8",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    return bin_dir


@pytest.fixture
async def pg_pool() -> AsyncIterator[asyncpg.Pool]:
    """Real Postgres pool for `@pytest.mark.integration` tests.

    Skips (not fails) if TEST_DATABASE_URL isn't reachable -- these tests are
    real integration coverage, not part of the offline default run every
    other test file in this repo sticks to (docs/09 §5 fixture-based/offline
    CI convention). `ci.yaml`'s python job runs a Postgres service container
    for this; a local `uv run pytest` without one just skips them.
    """
    if not _tcp_reachable(TEST_DATABASE_URL):
        pytest.skip(f"TEST_DATABASE_URL not reachable: {TEST_DATABASE_URL}")
    try:
        pool = await asyncpg.create_pool(
            dsn=TEST_DATABASE_URL, min_size=1, max_size=2, timeout=2
        )
    except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
        pytest.skip(f"TEST_DATABASE_URL not reachable: {exc}")
    await init_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE agent_runs, reviews, incidents RESTART IDENTITY CASCADE")
    try:
        yield pool
    finally:
        await pool.close()
