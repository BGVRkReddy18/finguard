"""Read-only database access (connects as the least-privilege ``finguard_ro`` role)."""
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


class Database:
    def __init__(self, url: str):
        self.pool = AsyncConnectionPool(url, min_size=1, max_size=5, open=False, kwargs={"row_factory": dict_row})

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
