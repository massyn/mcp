"""Relay — SQL definition files become MCP tools."""

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import uuid as _uuid_lib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from inspect import Parameter, Signature
from pathlib import Path
from typing import Any, Optional

import frontmatter
import yaml
from dotenv import load_dotenv
from jinja2 import Environment, StrictUndefined
from mcp.server.fastmcp import FastMCP

_log = logging.getLogger("relay")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class _LocalDB:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def execute_steps(self, steps: list[str], transaction: bool) -> Any:
        def _run() -> Any:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.isolation_level = None  # autocommit; transactions managed manually
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


def _build_db(
    db_type: str,
    db_path: Path,
    turso_url: str | None,
    turso_token: str | None,
) -> Any:
    if db_type == "turso":
        if not turso_url or not turso_token:
            raise RuntimeError("DB_TYPE=turso requires TURSO_URL and TURSO_TOKEN")
        return _TursoDB(turso_url, turso_token)
    return _LocalDB(db_path)


# ---------------------------------------------------------------------------
# Jinja environment
# ---------------------------------------------------------------------------

def _make_jinja_env() -> Environment:
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
# SQL file loading
# ---------------------------------------------------------------------------

def _load_sql_files(sql_dir: Path) -> list[dict]:
    tools = []
    for path in sorted(sql_dir.glob("*.sql")):
        try:
            post = frontmatter.load(str(path))
            meta = post.metadata
            steps = [s.strip() for s in post.content.split("\n---\n") if s.strip()]
            tools.append({"meta": meta, "steps": steps, "path": path})
            _log.debug("Loaded %s (%d steps)", path.name, len(steps))
        except Exception as exc:
            _log.warning("Skipping %s — parse error: %s", path.name, exc)
    return tools


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _render_steps(steps: list[str], jinja_env: Environment, params: dict) -> list[str]:
    return [jinja_env.from_string(step).render(**params) for step in steps]


async def _execute_tool(
    tool_def: dict, db: Any, jinja_env: Environment, params: dict
) -> str:
    meta = tool_def["meta"]
    transaction = meta.get("transaction", False)
    param_defs: dict = meta.get("parameters") or {}

    # Fill defaults for optional parameters not supplied by the caller
    full_params = dict(params)
    for pname, pdef in param_defs.items():
        if pname not in full_params:
            full_params[pname] = pdef.get("default", None)

    # Normalise list/dict values to JSON strings — the MCP client may deserialise
    # JSON arrays before they reach us, even when the parameter is typed as string.
    for k, v in full_params.items():
        if isinstance(v, (list, dict)):
            full_params[k] = json.dumps(v)

    try:
        rendered = _render_steps(tool_def["steps"], jinja_env, full_params)
        result = await db.execute_steps(rendered, transaction)
        return json.dumps(result if result is not None else {"status": "ok"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Dynamic tool registration
# ---------------------------------------------------------------------------

_PYTHON_TYPES: dict[str, type] = {"string": str, "integer": int, "boolean": bool}


def _make_tool_fn(tool_def: dict, db: Any, jinja_env: Environment):
    meta = tool_def["meta"]
    param_defs: dict = meta.get("parameters") or {}

    sig_params = []
    for pname, pdef in param_defs.items():
        ptype = _PYTHON_TYPES.get(pdef.get("type", "string"), str)
        required = pdef.get("required", True)
        # String parameters also accept list — MCP clients may deserialise JSON
        # arrays before delivery, and we normalise them to strings in _execute_tool.
        if ptype is str:
            annotation = str | list if required else str | list | None
        else:
            annotation = ptype if required else Optional[ptype]
        default = Parameter.empty if required else pdef.get("default", None)
        sig_params.append(
            Parameter(pname, Parameter.POSITIONAL_OR_KEYWORD, default=default, annotation=annotation)
        )

    async def _handler(**kwargs):
        for pname, pdef in param_defs.items():
            if pdef.get("required", True) and kwargs.get(pname) is None:
                return json.dumps({"error": f"Missing required parameter: {pname}"})
        return await _execute_tool(tool_def, db, jinja_env, kwargs)

    _handler.__signature__ = Signature(sig_params)
    _handler.__name__ = meta.get("name", tool_def["path"].stem)
    _handler.__doc__ = meta.get("description", "")
    return _handler


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _resolve_config(args: argparse.Namespace) -> dict:
    code_dir = args.code or os.environ.get("RELAY_CODE")
    if not code_dir:
        raise RuntimeError(
            "Code directory is required: pass --code or set RELAY_CODE environment variable"
        )
    code_path = Path(code_dir).expanduser().resolve()
    if not code_path.is_dir():
        raise RuntimeError(f"Code directory not found: {code_path}")

    load_dotenv(code_path / ".env")

    turso_url = os.environ.get("TURSO_URL")
    db_type = os.environ.get("DB_TYPE", "turso" if turso_url else "sqlite").lower()
    db_path_env = os.environ.get("DB_PATH")
    db_path = (
        Path(db_path_env).expanduser().resolve()
        if db_path_env
        else Path.home() / ".relay" / "relay.db"
    )
    return {
        "code_path": code_path,
        "db_type": db_type,
        "db_path": db_path,
        "turso_url": turso_url,
        "turso_token": os.environ.get("TURSO_TOKEN"),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Relay — SQL definition files become MCP tools"
    )
    parser.add_argument("--code", help="Code directory (overrides RELAY_CODE)")
    parser.add_argument(
        "--debug", action="store_true", help="Debug mode: run one tool and exit"
    )
    parser.add_argument("--tool", help="Tool name to invoke in debug mode")
    parser.add_argument(
        "--params", default="{}", help="JSON parameters for debug mode"
    )
    args = parser.parse_args()

    cfg = _resolve_config(args)
    code_path: Path = cfg["code_path"]
    db = _build_db(cfg["db_type"], cfg["db_path"], cfg["turso_url"], cfg["turso_token"])
    jinja_env = _make_jinja_env()

    index_path = code_path / "index.yaml"
    if not index_path.exists():
        raise RuntimeError(f"index.yaml not found in {code_path}")
    with open(index_path, encoding="utf-8") as f:
        index = yaml.safe_load(f)
    server_name: str = index.get("name", "relay")
    system_prompt: str = index.get("system_prompt", "")

    sql_dir = code_path / "sql"
    if not sql_dir.is_dir():
        raise RuntimeError(f"sql/ directory not found in {code_path}")

    all_defs = _load_sql_files(sql_dir)
    startup_defs = [d for d in all_defs if d["meta"].get("run_on_startup", False)]
    tool_defs = [d for d in all_defs if not d["meta"].get("run_on_startup", False)]

    if args.debug:
        if not args.tool:
            parser.error("--debug requires --tool")
        params = json.loads(args.params)
        target = next(
            (d for d in tool_defs if d["meta"].get("name") == args.tool), None
        )
        if not target:
            available = [d["meta"].get("name") for d in tool_defs]
            raise RuntimeError(
                f"Tool not found: {args.tool}. Available: {available}"
            )
        print(f"\n=== Front matter ===\n{yaml.dump(target['meta'], default_flow_style=False).strip()}")
        # Fill defaults and normalise values before rendering the preview
        _pdefs = target["meta"].get("parameters") or {}
        full_params = dict(params)
        for _pn, _pd in _pdefs.items():
            if _pn not in full_params:
                full_params[_pn] = _pd.get("default", None)
        for _k, _v in full_params.items():
            if isinstance(_v, (list, dict)):
                full_params[_k] = json.dumps(_v)
        rendered = _render_steps(target["steps"], jinja_env, full_params)
        for i, sql in enumerate(rendered, 1):
            print(f"\n=== Step {i} ===\n{sql.strip()}")

        # Run startup files first so the schema exists
        for d in startup_defs:
            rendered_startup = _render_steps(d["steps"], jinja_env, {})
            asyncio.run(db.execute_steps(rendered_startup, d["meta"].get("transaction", False)))

        result = asyncio.run(_execute_tool(target, db, jinja_env, params))
        print(f"\n=== Result ===\n{result}")
        return

    @asynccontextmanager
    async def _lifespan(app):
        for d in startup_defs:
            name = d["meta"].get("name", d["path"].stem)
            try:
                rendered = _render_steps(d["steps"], jinja_env, {})
                await db.execute_steps(rendered, d["meta"].get("transaction", False))
                _log.info("Startup: %s — OK", name)
            except Exception as exc:
                _log.error("Startup: %s — FAILED: %s", name, exc)
        yield

    mcp = FastMCP(server_name, instructions=system_prompt, lifespan=_lifespan)

    for d in tool_defs:
        name = d["meta"].get("name", d["path"].stem)
        try:
            fn = _make_tool_fn(d, db, jinja_env)
            mcp.add_tool(fn)
            _log.info("Registered tool: %s", name)
        except Exception as exc:
            _log.warning("Skipping tool %s — registration error: %s", name, exc)

    mcp.run()


if __name__ == "__main__":
    main()
