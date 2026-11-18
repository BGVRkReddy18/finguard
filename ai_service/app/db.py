"""Read-only database access (connects as the least-privilege ``finguard_ro`` role)."""
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


class Database:
    def __init__(self, url: str, min_size: int = 1, max_idle: float = 600):
        # min_size=0 + short max_idle lets a serverless database (e.g. Neon) suspend between visits
        # check: validate each connection before handing it out. Serverless Postgres (Neon) closes
        # connections when it suspends; without this, the next query fails on a dead connection.
        self.pool = AsyncConnectionPool(url, min_size=min_size, max_size=5, max_idle=max_idle, open=False,
                                        check=AsyncConnectionPool.check_connection,
                                        kwargs={"row_factory": dict_row})

    async def open(self) -> None:
        await self.pool.open()

    async def close(self) -> None:
        await self.pool.close()

    async def fetch(self, sql: str, params: tuple | dict | None = None) -> list[dict[str, Any]]:
        async with self.pool.connection() as conn:
            # Belt and braces: read-only transaction even though the role already defaults to it
            await conn.execute("SET TRANSACTION READ ONLY")
            cur = await conn.execute(sql, params)
            return await cur.fetchall()
