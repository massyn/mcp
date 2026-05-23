"""Relay execution engine — SQL file loading, Jinja rendering, and DB backends."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid as _uuid_lib

import frontmatter
from jinja2 import Environment, StrictUndefined

_log = logging.getLogger("relay.engine")


# ---------------------------------------------------------------------------
# Database backends
# ---------------------------------------------------------------------------

class _LocalDB:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def execute_steps(self, steps: list[str], transaction: bool) -> Any:
        import sqlite3

        def _run() -> Any:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.isolation_level = None
            try:
                if transaction:
                    conn.execute("BEGIN")
                last_result: Any = None
                for sql in steps:
                    sql = sql.strip()
                    if not sql:
                        continue
                    cursor = conn.execute(sql)
                    if cursor.description:
                        last_result = [dict(r) for r in cursor.fetchall()]
                    else:
                        last_result = {"rows_affected": cursor.rowcount}
                if transaction:
                    conn.execute("COMMIT")
                return last_result
            except Exception:
                if transaction:
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:
                        pass
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(_run)


class _TursoDB:
    def __init__(self, url: str, token: str) -> None:
        try:
            import libsql_client
        except ImportError as exc:
            raise RuntimeError(
                "libsql-client is required for Turso support: pip install libsql-client"
            ) from exc
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        self._libsql = libsql_client
        self._url = url
        self._token = token
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._libsql.create_client(self._url, auth_token=self._token)
        return self._client

    def _rs_to_result(self, rs: Any) -> Any:
        if rs is None:
            return None
        if rs.columns:
            return [dict(zip(rs.columns, row)) for row in rs.rows]
        return {"rows_affected": getattr(rs, "rows_affected", 0)}

    async def execute_steps(self, steps: list[str], transaction: bool) -> Any:
        client = self._get_client()
        valid = [s for s in steps if s.strip()]
        if not valid:
            return None
        if transaction:
            results = await client.batch(valid)
            return self._rs_to_result(results[-1]) if results else None
        last_rs = None
        for sql in valid:
            last_rs = await client.execute(sql)
        return self._rs_to_result(last_rs)


def build_db(
    db_type: str,
    db_path: Path,
    turso_url: str | None = None,
    turso_token: str | None = None,
) -> Any:
    if db_type == "turso":
        if not turso_url or not turso_token:
            raise RuntimeError("DB_TYPE=turso requires TURSO_URL and TURSO_TOKEN")
        return _TursoDB(turso_url, turso_token)
    return _LocalDB(db_path)


# ---------------------------------------------------------------------------
# Jinja environment
# ---------------------------------------------------------------------------

def make_jinja_env() -> Environment:
    def _sql_escape(value: Any) -> Any:
        if isinstance(value, str):
            return value.replace("'", "''")
        return value

    env = Environment(
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
        finalize=_sql_escape,
    )
    env.globals["now"] = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    env.globals["uuid"] = lambda: str(_uuid_lib.uuid4())
    return env


# ---------------------------------------------------------------------------
# SQL file loading and rendering
# ---------------------------------------------------------------------------

def load_sql_files(sql_dir: Path) -> list[dict]:
    tools = []
    for path in sorted(sql_dir.glob("*.sql")):
        try:
            post = frontmatter.load(str(path))
            meta = post.metadata
            steps = [s.strip() for s in post.content.split("\n---\n") if s.strip()]
            tools.append({"meta": meta, "steps": steps, "path": path})
        except Exception as exc:
            _log.warning("Skipping %s — parse error: %s", path.name, exc)
    return tools


def render_steps(steps: list[str], jinja_env: Environment, params: dict) -> list[str]:
    return [jinja_env.from_string(step).render(**params) for step in steps]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class Engine:
    """Executes named SQL file tools and ad-hoc queries against a DB backend."""

    def __init__(self, db: Any, jinja_env: Environment | None = None) -> None:
        self._db = db
        self._jinja = jinja_env or make_jinja_env()
        self._tools: dict[str, dict] = {}
        self._startup: list[dict] = []

    def load(self, sql_dir: Path) -> None:
        """Register SQL files from a directory. Later loads can override earlier ones."""
        for tool in load_sql_files(sql_dir):
            name = tool["meta"].get("name", tool["path"].stem)
            if tool["meta"].get("run_on_startup", False):
                self._startup.append(tool)
            else:
                self._tools[name] = tool

    async def run_startup(self) -> None:
        for tool in self._startup:
            name = tool["meta"].get("name", tool["path"].stem)
            try:
                rendered = render_steps(tool["steps"], self._jinja, {})
                await self._db.execute_steps(rendered, tool["meta"].get("transaction", False))
                _log.info("Startup: %s — OK", name)
            except Exception as exc:
                _log.error("Startup: %s — FAILED: %s", name, exc)

    async def execute(self, tool_name: str, **params: Any) -> Any:
        """Run a named tool. Returns raw Python result (list of dicts or dict)."""
        tool = self._tools[tool_name]
        meta = tool["meta"]
        param_defs: dict = meta.get("parameters") or {}

        full_params = dict(params)
        for pname, pdef in param_defs.items():
            if pname not in full_params:
                full_params[pname] = pdef.get("default", None)

        for k, v in full_params.items():
            if isinstance(v, (list, dict)):
                full_params[k] = json.dumps(v)

        rendered = render_steps(tool["steps"], self._jinja, full_params)
        return await self._db.execute_steps(rendered, meta.get("transaction", False))

    async def query(self, sql_template: str, **params: Any) -> list[dict]:
        """Run an ad-hoc Jinja SQL template. Returns list of row dicts."""
        rendered = self._jinja.from_string(sql_template).render(**params)
        result = await self._db.execute_steps([rendered], False)
        return result if isinstance(result, list) else []
