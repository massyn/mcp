"""Shared MCP server and database instances."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from db import build_db

load_dotenv(Path(__file__).parent / ".env")

_db_env = os.environ.get("DB_PATH")
_db_path = (
    Path(_db_env).expanduser().resolve()
    if _db_env
    else Path.home() / ".citadel" / "citadel.db"
)

db = build_db(
    db_path=_db_path,
    turso_url=os.environ.get("TURSO_URL"),
    turso_token=os.environ.get("TURSO_TOKEN"),
)


@asynccontextmanager
async def _lifespan(app):
    await db.init_schema()
    yield


mcp = FastMCP("citadel", lifespan=_lifespan)
