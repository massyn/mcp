"""Room management MCP tools."""

import json
from typing import Optional

from helpers import _now, _resolve_room, _slugify
from server import db, mcp
from sql import render


@mcp.tool()
async def citadel_get_manifest(tags: Optional[list[str]] = None) -> str:
    """
    Returns all rooms (optionally filtered by tags).
    Tag filtering matches both room tags and entry tags — a room is included if
    any of its own tags or any of its active entries' tags intersect with the requested tags.
    Each room includes: name, aliases, tags, entry_count, updated_on.
    Call this at the start of every conversation to see what knowledge exists.
    """
    try:
        rooms = await db.query(render("rooms_manifest.sql"))
        for r in rooms:
            r["tags"] = json.loads(r["tags"])
            r["aliases"] = json.loads(r.get("aliases") or "[]")

        if tags:
            tag_set = set(tags)
            entry_rows = await db.query(render("rooms_entry_tags.sql"))
            room_entry_tags: dict[str, set[str]] = {}
            for row in entry_rows:
                room_entry_tags.setdefault(row["room"], set()).update(json.loads(row["tags"]))

            rooms = [
                r for r in rooms
                if tag_set.intersection(r["tags"])
                or tag_set.intersection(room_entry_tags.get(r["name"], set()))
            ]

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
        await db.execute(render("room_insert.sql"), (slug, aliases, json.dumps(tags), now, now))
        return json.dumps({"status": "created", "room": slug})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_update_room(
    room: str,
    name: Optional[str] = None,
    tags: Optional[list[str]] = None,
    add_aliases: Optional[list[str]] = None,
) -> str:
    """
    Updates a room's name, tags, or aliases.
    - name: renames the room (all entries re-pointed automatically; old name kept as alias).
    - tags: replaces the room's tag list entirely.
    - add_aliases: appends new aliases without removing existing ones.
    At least one of name, tags, or add_aliases must be provided.
    Returns the updated room slug.
    """
    try:
        canonical = await _resolve_room(room)
        if not canonical:
            return json.dumps({"error": f"Room not found: {room}"})

        if name is None and tags is None and add_aliases is None:
            return json.dumps({"status": "no_changes"})

        room_row = await db.query_one(render("room_get_detail.sql"), (canonical,))
        now = _now()

        new_tags = json.loads(room_row["tags"]) if tags is None else tags
        current_aliases: list[str] = json.loads(room_row.get("aliases") or "[]")

        if add_aliases:
            for alias in add_aliases:
                s = _slugify(alias)
                if s and s not in current_aliases:
                    current_aliases.append(s)

        if name is not None:
            new_name = _slugify(name)
            if not new_name:
                return json.dumps({"error": "New room name must not be empty"})
            if new_name != canonical:
                conflict = await _resolve_room(new_name)
                if conflict and conflict != canonical:
                    return json.dumps({"error": f"Room already exists: {new_name}"})
                if canonical not in current_aliases:
                    current_aliases.append(canonical)
                await db.batch([
                    (render("room_rename_insert.sql"), (new_name, json.dumps(current_aliases), json.dumps(new_tags), now, canonical)),
                    (render("room_rename_entries.sql"), (new_name, canonical)),
                    (render("room_delete.sql"), (canonical,)),
                ])
                return json.dumps({"status": "updated", "room": new_name})

        await db.execute(
            render("room_update.sql"),
            (json.dumps(new_tags), json.dumps(current_aliases), now, canonical),
        )
        return json.dumps({"status": "updated", "room": canonical})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_delete_room(room: str) -> str:
    """
    Permanently deletes a room and all its entries.
    This is irreversible. Returns the count of entries removed along with the room.
    """
    try:
        canonical = await _resolve_room(room)
        if not canonical:
            return json.dumps({"error": f"Room not found: {room}"})
        count_row = await db.query_one(render("room_entry_count.sql"), (canonical,))
        entry_count = count_row["n"] if count_row else 0
        await db.batch([
            (render("room_delete_entries.sql"), (canonical,)),
            (render("room_delete.sql"), (canonical,)),
        ])
        return json.dumps({"status": "deleted", "room": canonical, "entries_removed": entry_count})
    except Exception as e:
        return json.dumps({"error": str(e)})
