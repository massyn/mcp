"""Entry management MCP tools."""

import json
import uuid
from typing import Optional

from helpers import _now, _resolve_room, _slugify
from models import AddEntryInput, BulkEntryItem, UpdateEntryInput
from server import db, mcp
from sql import render


@mcp.tool()
async def citadel_get_room(
    room: str,
    status: str = "active",
    limit: int = 50,
    offset: int = 0,
) -> str:
    """
    Returns entries in a room at summary level (no detail field).
    Use status to filter by 'active', 'archived', or 'deprecated'.
    Use limit and offset for pagination (default: limit=50, offset=0).
    Response includes total so callers know whether more pages exist.
    Use citadel_get_entry to load the full detail for a specific entry.
    """
    try:
        if status not in ("active", "archived", "deprecated"):
            return json.dumps({"error": f"Invalid status: {status}"})
        canonical = await _resolve_room(room)
        if not canonical:
            return json.dumps({"error": f"Room not found: {room}"})
        total_row = await db.query_one(render("entries_count.sql"), (canonical, status))
        total = total_row["n"] if total_row else 0
        entries = await db.query(render("entries_list.sql"), (canonical, status, limit, offset))
        for e in entries:
            e["tags"] = json.loads(e["tags"])
        return json.dumps({"room": canonical, "total": total, "limit": limit, "offset": offset, "entries": entries})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_get_entry(entry_id: str, room: Optional[str] = None) -> str:
    """
    Returns the full entry including the detail field.
    entry_id alone is sufficient — room is an optional narrowing hint.
    """
    try:
        canonical_room = await _resolve_room(room) if room else None
        params: list = [entry_id]
        if canonical_room:
            params.append(canonical_room)
        entry = await db.query_one(render("entry_get.sql", with_room=canonical_room is not None), params)
        if entry is None:
            hint = f" in room {canonical_room}" if canonical_room else ""
            return json.dumps({"error": f"Entry not found: {entry_id}{hint}"})
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
    Creates a new knowledge entry in a room. Auto-creates the room if it doesn't exist.
    Returns the new entry id.

    Entries are knowledge artifacts — decisions, rationale, context, patterns, and outcomes.
    They are the library: persistent, reference-oriented, and designed to be read back later.
    Capture the WHY behind what was built or decided, not open work.

    Do not structure entries as todo lists. Actionable work belongs in citadel_add_todo.
    When a todo is completed and produces an outcome, update the linked entry with that
    outcome first — the entry absorbs the knowledge — then mark the todo done.
    """
    try:
        data = AddEntryInput(room=room, title=title, summary=summary, detail=detail, tags=tags or [])
        canonical = await _resolve_room(data.room)
        if canonical:
            room_slug = canonical
            room_aliases = "[]"
        else:
            room_slug = _slugify(data.room)
            room_aliases = json.dumps([data.room] if data.room != room_slug else [])
        now = _now()
        entry_id = str(uuid.uuid4())
        await db.batch([
            (render("room_upsert.sql"), (room_slug, room_aliases, now, now)),
            (render("entry_insert.sql"), (entry_id, room_slug, data.title, data.summary, data.detail, json.dumps(data.tags), now, now)),
            (render("room_touch.sql"), (now, room_slug)),
        ])
        return json.dumps({"status": "created", "id": entry_id, "room": room_slug})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_bulk_add_entries(entries: list[dict]) -> str:
    """
    Creates multiple knowledge entries in one call. Each entry must have: room, title, summary, detail.
    Tags are optional per entry. Rooms are auto-created if they don't exist.
    Returns a list of created ids and any per-entry errors (indexed by position).

    The same model applies as citadel_add_entry: entries are knowledge artifacts — decisions,
    rationale, context, and outcomes — not trackers for open work. Use citadel_add_todo
    for anything actionable.
    """
    try:
        if not entries:
            return json.dumps({"error": "entries list must not be empty"})

        now = _now()
        resolved_rooms: dict[str, str] = {}
        rooms_to_create: dict[str, str] = {}

        for raw in entries:
            room_input = raw.get("room", "")
            if not room_input or room_input in resolved_rooms:
                continue
            canonical = await _resolve_room(room_input)
            if canonical:
                resolved_rooms[room_input] = canonical
            else:
                slug = _slugify(room_input)
                aliases = json.dumps([room_input] if room_input != slug else [])
                resolved_rooms[room_input] = slug
                rooms_to_create[slug] = aliases

        statements: list[tuple] = [
            (render("room_upsert.sql"), (slug, aliases, now, now))
            for slug, aliases in rooms_to_create.items()
        ]

        created: list[dict] = []
        errors: list[dict] = []

        for i, raw in enumerate(entries):
            try:
                item = BulkEntryItem(**raw)
                room_slug = resolved_rooms.get(item.room, _slugify(item.room))
                entry_id = str(uuid.uuid4())
                statements.append((
                    render("entry_insert.sql"),
                    (entry_id, room_slug, item.title, item.summary, item.detail, json.dumps(item.tags), now, now),
                ))
                created.append({"index": i, "id": entry_id, "room": room_slug})
            except Exception as exc:
                errors.append({"index": i, "error": str(exc)})

        for room_slug in {c["room"] for c in created}:
            statements.append((render("room_touch.sql"), (now, room_slug)))

        if statements:
            await db.batch(statements)

        return json.dumps({"created": created, "errors": errors})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_move_entry(entry_id: str, from_room: str, to_room: str) -> str:
    """
    Moves an entry from one room to another.
    The destination room is auto-created if it doesn't exist.
    """
    try:
        from_canonical = await _resolve_room(from_room)
        if not from_canonical:
            return json.dumps({"error": f"Source room not found: {from_room}"})

        existing = await db.query_one(render("entry_exists.sql"), (entry_id, from_canonical))
        if not existing:
            return json.dumps({"error": f"Entry not found: {entry_id} in room {from_canonical}"})

        to_canonical = await _resolve_room(to_room)
        now = _now()

        if not to_canonical:
            slug = _slugify(to_room)
            aliases = json.dumps([to_room] if to_room != slug else [])
            await db.execute(render("room_upsert.sql"), (slug, aliases, now, now))
            to_canonical = slug

        await db.batch([
            (render("entry_move.sql"), (to_canonical, now, entry_id)),
            (render("room_touch.sql"), (now, from_canonical)),
            (render("room_touch.sql"), (now, to_canonical)),
        ])
        return json.dumps({"status": "moved", "id": entry_id, "from": from_canonical, "to": to_canonical})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_update_entry(
    room: str,
    entry_id: str,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    detail: Optional[str] = None,
    status: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> str:
    """
    Updates any combination of title, summary, detail, status, tags.
    Only provided fields are changed. Always updates updated_on.
    """
    try:
        data = UpdateEntryInput(
            room=room, entry_id=entry_id, title=title, summary=summary,
            detail=detail, status=status, tags=tags,
        )
        fields: list[str] = []
        values: list = []
        if data.title is not None:
            fields.append("title = ?"); values.append(data.title)
        if data.summary is not None:
            fields.append("summary = ?"); values.append(data.summary)
        if data.detail is not None:
            fields.append("detail = ?"); values.append(data.detail)
        if data.status is not None:
            fields.append("status = ?"); values.append(data.status)
        if data.tags is not None:
            fields.append("tags = ?"); values.append(json.dumps(data.tags))

        if not fields:
            return json.dumps({"status": "no_changes"})

        existing = await db.query_one(render("entry_exists.sql"), (data.entry_id, data.room))
        if not existing:
            return json.dumps({"error": f"Entry not found: {entry_id} in room {room}"})

        now = _now()
        values.extend([now, data.entry_id, data.room])

        await db.batch([
            (render("entry_update.sql", fields=fields), values),
            (render("room_touch.sql"), (now, data.room)),
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
        existing = await db.query_one(render("entry_exists.sql"), (entry_id, room))
        if not existing:
            return json.dumps({"error": f"Entry not found: {entry_id} in room {room}"})
        now = _now()
        await db.batch([
            (render("entry_delete.sql"), (entry_id, room)),
            (render("room_touch.sql"), (now, room)),
        ])
        return json.dumps({"status": "deleted", "id": entry_id, "room": room})
    except Exception as e:
        return json.dumps({"error": str(e)})
