"""asyncpg pool + schema init (docs/06 §6, M4).

One pool per process. `init_schema` runs `schema.sql` -- every statement in
it is idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE OR REPLACE
FUNCTION`), so calling it on every API startup is safe and keeps a fresh
Postgres instance (e.g. `docker compose up` on a clean volume) self-bootstrapping.
"""

from __future__ import annotations

from pathlib import Path

import asyncpg

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

DEFAULT_DSN = "postgresql://sitewatch:sitewatch@localhost:5432/sitewatch"


async def create_pool(dsn: str = DEFAULT_DSN) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=10)


async def init_schema(pool: asyncpg.Pool) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(sql)
