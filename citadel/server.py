"""Shared MCP server and database instances."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from db import build_db

_log = logging.getLogger("citadel")

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
    try:
        await db.init_schema()
    except Exception as exc:
        _log.error("Database initialisation failed — server running in degraded state: %s", exc)
    yield


_INSTRUCTIONS = """
Citadel is a personal knowledge management system. It has two main constructs:

- **Entries**: durable knowledge — decisions, patterns, research, reference material. These persist indefinitely and absorb the outcome of completed work.
- **Todos**: work items — actionable, completable tasks. When done, mark them done and record the outcome in the linked entry.

## Writing CC-ready todos

Before saving a todo, ask yourself: is this something Claude Code is likely to pick up and action later?
If yes, write the `detail` field as a self-contained prompt. Claude Code has no conversation history and
no memory — the detail field is everything it has to work with.

**Bad detail**: "fix the auth bug"
**Good detail**: "In app/auth.py:54, replace flask_ENV with FLASK_ENV — affects config.py:11 and run.py:64 as well. See kickstand flask-patterns alignment entry da8372e9 for full context."

A CC-ready detail includes: file paths and line numbers, tool or function names, relevant entry IDs for
context, and the expected outcome. If a todo cannot be actioned from its detail field alone, it will be
ignored. Write it so a cold agent can pick it up without asking a single follow-up question.
"""

mcp = FastMCP("citadel", instructions=_INSTRUCTIONS, lifespan=_lifespan)
