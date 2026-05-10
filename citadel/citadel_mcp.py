"""Citadel MCP — personal knowledge management server for LLMs."""

import argparse
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, field_validator

from db import build_db

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv(Path(__file__).parent / ".env")

_db_env = os.environ.get("DB_PATH")
_db_path = Path(_db_env).expanduser().resolve() if _db_env else Path.home() / ".citadel" / "citadel.db"

db = build_db(
    db_path=_db_path,
    turso_url=os.environ.get("TURSO_URL"),
    turso_token=os.environ.get("TURSO_TOKEN"),
)


@asynccontextmanager
async def _lifespan(app):
    await db.init_schema()
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slugify(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


async def _resolve_room(name: str) -> str | None:
    """Return the canonical room name for a given name or alias, or None if not found."""
    slug = _slugify(name)
    row = await db.query_one("SELECT name FROM rooms WHERE name = ?", (slug,))
    if row:
        return row["name"]
    row = await db.query_one(
        "SELECT name FROM rooms WHERE aliases LIKE ?", (f'%"{slug}"%',)
    )
    return row["name"] if row else None


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

EntryStatus = Literal["active", "archived", "deprecated"]


class AddRoomInput(BaseModel):
    name: str
    tags: list[str] = []

    @field_validator("name")
    @classmethod
    def name_is_slug(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Room name must not be empty")
        return v


class AddEntryInput(BaseModel):
    room: str
    title: str
    summary: str
    detail: str
    tags: list[str] = []

    @field_validator("room", "title", "summary", "detail")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be empty")
        return v


class UpdateEntryInput(BaseModel):
    room: str
    entry_id: str
    summary: Optional[str] = None
    detail: Optional[str] = None
    status: Optional[EntryStatus] = None
    tags: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("citadel", lifespan=_lifespan)


@mcp.tool()
async def citadel_get_manifest(tags: Optional[list[str]] = None) -> str:
    """
    Returns all rooms (optionally filtered by tags).
    Each room includes: name, tags, entry_count, updated_on.
    Call this at the start of every conversation to see what knowledge exists.
    """
    try:
        rooms = await db.query(
            "SELECT r.name, r.aliases, r.tags, r.updated_on, COUNT(e.id) AS entry_count "
            "FROM rooms r LEFT JOIN entries e ON e.room = r.name "
            "GROUP BY r.name ORDER BY r.updated_on DESC"
        )
        if tags:
            tag_set = set(tags)
            rooms = [r for r in rooms if tag_set.intersection(json.loads(r["tags"]))]
        for r in rooms:
            r["tags"] = json.loads(r["tags"])
            r["aliases"] = json.loads(r.get("aliases") or "[]")
        return json.dumps({"rooms": rooms})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_add_room(name: str, tags: list[str] = []) -> str:
    """
    Creates a new room. The name is normalised to a lowercase hyphenated slug;
    the original name is stored as an alias. Returns success or an already-exists message.
    """
    try:
        slug = _slugify(name)
        if not slug:
            return json.dumps({"error": "Room name must not be empty"})
        existing = await _resolve_room(slug)
        if existing:
            return json.dumps({"status": "exists", "room": existing})
        aliases = json.dumps([name] if name != slug else [])
        now = _now()
        await db.execute(
            "INSERT INTO rooms (name, aliases, tags, created_on, updated_on) VALUES (?, ?, ?, ?, ?)",
            (slug, aliases, json.dumps(tags), now, now),
        )
        return json.dumps({"status": "created", "room": slug})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_get_room(room: str, status: str = "active") -> str:
    """
    Returns all entries in a room at summary level (no detail field).
    Use this to scan what's in a room before deciding what to load fully.
    """
    try:
        if status not in ("active", "archived", "deprecated"):
            return json.dumps({"error": f"Invalid status: {status}"})
        room = await _resolve_room(room) or room
        room_row = await db.query_one("SELECT name FROM rooms WHERE name = ?", (room,))
        if not room_row:
            return json.dumps({"error": f"Room not found: {room}"})
        entries = await db.query(
            "SELECT id, title, summary, tags, status, updated_on "
            "FROM entries WHERE room = ? AND status = ? ORDER BY updated_on DESC",
            (room, status),
        )
        for e in entries:
            e["tags"] = json.loads(e["tags"])
        return json.dumps({"room": room, "entries": entries})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_get_entry(room: str, entry_id: str) -> str:
    """
    Returns the full entry including the detail field.
    """
    try:
        entry = await db.query_one(
            "SELECT * FROM entries WHERE id = ? AND room = ?", (entry_id, room)
        )
        if entry is None:
            return json.dumps({"error": f"Entry not found: {entry_id} in room {room}"})
        entry["tags"] = json.loads(entry["tags"])
        return json.dumps(entry)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_add_entry(
    room: str,
    title: str,
    summary: str,
    detail: str,
    tags: Optional[list[str]] = None,
) -> str:
    """
    Creates a new entry. Auto-creates the room if it doesn't exist.
    Returns the new entry id.
    """
    try:
        data = AddEntryInput(room=room, title=title, summary=summary, detail=detail, tags=tags or [])
        canonical = await _resolve_room(data.room)
        if canonical:
            room_aliases = "[]"
            data = data.model_copy(update={"room": canonical})
        else:
            slug = _slugify(data.room)
            room_aliases = json.dumps([data.room] if data.room != slug else [])
            data = data.model_copy(update={"room": slug})
        now = _now()
        entry_id = str(uuid.uuid4())
        await db.batch([
            (
                "INSERT OR IGNORE INTO rooms (name, aliases, tags, created_on, updated_on) VALUES (?, ?, '[]', ?, ?)",
                (data.room, room_aliases, now, now),
            ),
            (
                "INSERT INTO entries (id, room, title, summary, detail, tags, status, created_on, updated_on) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                (entry_id, data.room, data.title, data.summary, data.detail, json.dumps(data.tags), now, now),
            ),
            (
                "UPDATE rooms SET updated_on = ? WHERE name = ?",
                (now, data.room),
            ),
        ])
        return json.dumps({"status": "created", "id": entry_id, "room": data.room})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_update_entry(
    room: str,
    entry_id: str,
    summary: Optional[str] = None,
    detail: Optional[str] = None,
    status: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> str:
    """
    Updates any combination of summary, detail, status, tags.
    Only provided fields are changed. Always updates updated_on.
    """
    try:
        data = UpdateEntryInput(
            room=room, entry_id=entry_id, summary=summary, detail=detail, status=status, tags=tags
        )
        fields: list[str] = []
        values: list = []
        if data.summary is not None:
            fields.append("summary = ?")
            values.append(data.summary)
        if data.detail is not None:
            fields.append("detail = ?")
            values.append(data.detail)
        if data.status is not None:
            fields.append("status = ?")
            values.append(data.status)
        if data.tags is not None:
            fields.append("tags = ?")
            values.append(json.dumps(data.tags))

        if not fields:
            return json.dumps({"status": "no_changes"})

        existing = await db.query_one(
            "SELECT id FROM entries WHERE id = ? AND room = ?", (data.entry_id, data.room)
        )
        if not existing:
            return json.dumps({"error": f"Entry not found: {entry_id} in room {room}"})

        now = _now()
        fields.append("updated_on = ?")
        values.extend([now, data.entry_id, data.room])

        await db.batch([
            (f"UPDATE entries SET {', '.join(fields)} WHERE id = ? AND room = ?", values),
            ("UPDATE rooms SET updated_on = ? WHERE name = ?", (now, data.room)),
        ])
        return json.dumps({"status": "updated", "id": entry_id})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_delete_entry(room: str, entry_id: str) -> str:
    """
    Permanently deletes a single entry from a room.
    This is irreversible — use citadel_update_entry with status='archived' for soft-delete.
    """
    try:
        existing = await db.query_one(
            "SELECT id FROM entries WHERE id = ? AND room = ?", (entry_id, room)
        )
        if not existing:
            return json.dumps({"error": f"Entry not found: {entry_id} in room {room}"})
        now = _now()
        await db.batch([
            ("DELETE FROM entries WHERE id = ? AND room = ?", (entry_id, room)),
            ("UPDATE rooms SET updated_on = ? WHERE name = ?", (now, room)),
        ])
        return json.dumps({"status": "deleted", "id": entry_id, "room": room})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_delete_room(room: str) -> str:
    """
    Permanently deletes a room and all its entries.
    This is irreversible. Returns the count of entries removed along with the room.
    """
    try:
        room = await _resolve_room(room) or room
        existing = await db.query_one("SELECT name FROM rooms WHERE name = ?", (room,))
        if not existing:
            return json.dumps({"error": f"Room not found: {room}"})
        count_row = await db.query_one(
            "SELECT COUNT(*) AS n FROM entries WHERE room = ?", (room,)
        )
        entry_count = count_row["n"] if count_row else 0
        await db.batch([
            ("DELETE FROM entries WHERE room = ?", (room,)),
            ("DELETE FROM rooms WHERE name = ?", (room,)),
        ])
        return json.dumps({"status": "deleted", "room": room, "entries_removed": entry_count})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_search(
    query: str,
    room: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> str:
    """
    Full-text search across title + summary + detail.
    Optionally scoped to a room or filtered by tags.
    Returns summary-level results (no detail field).
    """
    try:
        if not query.strip():
            return json.dumps({"error": "Query must not be empty"})
        like = f"%{query}%"
        sql = (
            "SELECT id, room, title, summary, tags, status, updated_on "
            "FROM entries WHERE (title LIKE ? OR summary LIKE ? OR detail LIKE ?)"
        )
        params: list = [like, like, like]
        if room:
            room = await _resolve_room(room) or room
            sql += " AND room = ?"
            params.append(room)
        sql += " ORDER BY updated_on DESC"

        results = await db.query(sql, params)
        if tags:
            tag_set = set(tags)
            results = [r for r in results if tag_set.intersection(json.loads(r["tags"]))]
        for r in results:
            r["tags"] = json.loads(r["tags"])
        return json.dumps({"query": query, "count": len(results), "results": results})
    except Exception as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Citadel MCP server")
    parser.add_argument("--http", action="store_true", help="Run as HTTP server instead of stdio")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (HTTP mode only)")
    parser.add_argument("--port", type=int, default=8000, help="Port (HTTP mode only)")
    args = parser.parse_args()

    if args.http:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()
