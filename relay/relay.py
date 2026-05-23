"""Relay — SQL definition files become MCP tools."""

import argparse
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from inspect import Parameter, Signature
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from engine import Engine, build_db, load_sql_files, make_jinja_env, render_steps

_log = logging.getLogger("relay")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ---------------------------------------------------------------------------
# Dynamic tool registration
# ---------------------------------------------------------------------------

_PYTHON_TYPES: dict[str, type] = {"string": str, "integer": int, "boolean": bool}


def _make_tool_fn(tool_def: dict, engine: Engine):
    meta = tool_def["meta"]
    param_defs: dict = meta.get("parameters") or {}
    tool_name: str = meta.get("name", tool_def["path"].stem)

    sig_params = []
    for pname, pdef in param_defs.items():
        ptype = _PYTHON_TYPES.get(pdef.get("type", "string"), str)
        required = pdef.get("required", True)
        # String parameters also accept list — MCP clients may deserialise JSON
        # arrays before delivery; engine.execute normalises them to strings.
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
        result = await engine.execute(tool_name, **kwargs)
        return json.dumps(result if result is not None else {"status": "ok"})

    _handler.__signature__ = Signature(sig_params)
    _handler.__name__ = tool_name
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
    db = build_db(cfg["db_type"], cfg["db_path"], cfg["turso_url"], cfg["turso_token"])
    jinja_env = make_jinja_env()

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

    engine = Engine(db, jinja_env)
    engine.load(sql_dir)

    all_defs = load_sql_files(sql_dir)
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
        _pdefs = target["meta"].get("parameters") or {}
        full_params = dict(params)
        for _pn, _pd in _pdefs.items():
            if _pn not in full_params:
                full_params[_pn] = _pd.get("default", None)
        for _k, _v in full_params.items():
            if isinstance(_v, (list, dict)):
                full_params[_k] = json.dumps(_v)
        rendered = render_steps(target["steps"], jinja_env, full_params)
        for i, sql in enumerate(rendered, 1):
            print(f"\n=== Step {i} ===\n{sql.strip()}")

        for d in startup_defs:
            rendered_startup = render_steps(d["steps"], jinja_env, {})
            asyncio.run(db.execute_steps(rendered_startup, d["meta"].get("transaction", False)))

        result = asyncio.run(engine.execute(target["meta"].get("name", target["path"].stem), **params))
        print(f"\n=== Result ===\n{json.dumps(result)}")
        return

    @asynccontextmanager
    async def _lifespan(app):
        await engine.run_startup()
        yield

    mcp = FastMCP(server_name, instructions=system_prompt, lifespan=_lifespan)

    for d in tool_defs:
        name = d["meta"].get("name", d["path"].stem)
        try:
            fn = _make_tool_fn(d, engine)
            mcp.add_tool(fn)
            _log.info("Registered tool: %s", name)
        except Exception as exc:
            _log.warning("Skipping tool %s — registration error: %s", name, exc)

    mcp.run()


if __name__ == "__main__":
    main()
