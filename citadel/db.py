"""Database abstraction — local SQLite and remote Turso backends."""

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Protocol, Sequence

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS rooms (
        name       TEXT PRIMARY KEY,
        tags       TEXT NOT NULL DEFAULT '[]',
        created_on TEXT NOT NULL,
        updated_on TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS entries (
        id         TEXT PRIMARY KEY,
        room       TEXT NOT NULL REFERENCES rooms(name),
        title      TEXT NOT NULL,
        summary    TEXT NOT NULL,
        detail     TEXT NOT NULL,
        tags       TEXT NOT NULL DEFAULT '[]',
        status     TEXT NOT NULL DEFAULT 'active',
        created_on TEXT NOT NULL,
        updated_on TEXT NOT NULL
    )""",
]


class Database(Protocol):
    async def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict]: ...
    async def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None: ...
    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None: ...
    async def batch(self, statements: list[tuple[str, Sequence[Any]]]) -> None: ...
    async def init_schema(self) -> None: ...
    async def close(self) -> None: ...


class LocalDatabase:
    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    async def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        def _run() -> list[dict]:
            with self._connect() as conn:
                return [dict(r) for r in conn.execute(sql, params).fetchall()]
        return await asyncio.to_thread(_run)

    async def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        def _run() -> dict | None:
            with self._connect() as conn:
                row = conn.execute(sql, params).fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(_run)

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.execute(sql, params)
        await asyncio.to_thread(_run)

    async def batch(self, statements: list[tuple[str, Sequence[Any]]]) -> None:
        def _run() -> None:
            with self._connect() as conn:
                for sql, params in statements:
                    conn.execute(sql, params)
        await asyncio.to_thread(_run)

    async def init_schema(self) -> None:
        def _run() -> None:
            with self._connect() as conn:
                for stmt in _SCHEMA:
                    conn.execute(stmt)
        await asyncio.to_thread(_run)

    async def close(self) -> None:
        pass


class TursoDatabase:
    def __init__(self, url: str, token: str) -> None:
        try:
            import libsql_client
        except ImportError as exc:
            raise RuntimeError(
                "libsql-client is required for Turso support: pip install libsql-client"
            ) from exc
        # libsql:// resolves to wss:// (WebSocket), which Turso rejects with a
        # 505. Rewrite to https:// to use the HTTP transport instead.
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        self._libsql = libsql_client
        self._url = url
        self._token = token
        self._client: Any = None  # created lazily — requires a running event loop

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._libsql.create_client(self._url, auth_token=self._token)
        return self._client

    def _to_dicts(self, rs: Any) -> list[dict]:
        return [dict(zip(rs.columns, row)) for row in rs.rows]

    def _stmt(self, sql: str, params: Sequence[Any]) -> Any:
        return self._libsql.Statement(sql, list(params))

    async def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        rs = await self._get_client().execute(self._stmt(sql, params))
        return self._to_dicts(rs)

    async def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        rows = await self.query(sql, params)
        return rows[0] if rows else None

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        await self._get_client().execute(self._stmt(sql, params))

    async def batch(self, statements: list[tuple[str, Sequence[Any]]]) -> None:
        await self._get_client().batch([self._stmt(sql, params) for sql, params in statements])

    async def init_schema(self) -> None:
        # DDL issued individually — batch rejects multi-statement DDL on some
        # Turso plans and the statements are idempotent anyway.
        for stmt in _SCHEMA:
            await self.execute(stmt)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()


def build_db(
    db_path: Path,
    turso_url: str | None,
    turso_token: str | None,
) -> LocalDatabase | TursoDatabase:
    if turso_url and turso_token:
        return TursoDatabase(turso_url, turso_token)
    return LocalDatabase(db_path)
