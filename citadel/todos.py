"""Todo list MCP tools."""

import json
from typing import Optional

from helpers import _now, _resolve_room, _slugify
from server import db, mcp
from sql import render

_VALID_STATUSES = {"open", "in_progress", "blocked", "done", "cancelled", "deferred"}


@mcp.tool()
async def citadel_add_todo(
    room: str,
    title: str,
    detail: Optional[str] = None,
    priority: int = 3,
    due_date: Optional[str] = None,
    entry_id: Optional[str] = None,
) -> str:
    """
    Creates a new todo item linked to a room. Returns the integer todo id.
    priority: 1 (critical) to 5 (nice-to-have), default 3.
    due_date: optional ISO date string (YYYY-MM-DD).
    entry_id: optional — links this todo to a knowledge entry that provides context.
    Auto-creates the room if it doesn't exist.

    Todos are work items: actionable, completable, and time-bound. They are the system of
    record for what was done and when. Do not store knowledge in todos — that belongs in entries.

    The intended workflow: create a todo for the work, optionally link it to a relevant entry
    via entry_id for context. When the work is complete, update the linked entry with the
    outcome (what was decided, built, or learned), then mark this todo done. The todo
    disappears from the active view; the entry absorbs the knowledge permanently.
    """
    try:
        if not title.strip():
            return json.dumps({"error": "title must not be empty"})
        if priority not in range(1, 6):
            return json.dumps({"error": "priority must be between 1 and 5"})

        canonical = await _resolve_room(room)
        if canonical:
            room_slug = canonical
            room_aliases = "[]"
        else:
            room_slug = _slugify(room)
            room_aliases = json.dumps([room] if room != room_slug else [])

        now = _now()
        await db.execute(render("room_upsert.sql"), (room_slug, room_aliases, now, now))
        todo_id = await db.execute_lastrowid(
            render("todo_insert.sql"),
            (room_slug, title.strip(), detail, priority, due_date, entry_id, now, now),
        )
        await db.execute(render("room_touch.sql"), (now, room_slug))
        return json.dumps({"status": "created", "id": todo_id, "room": room_slug})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_get_todos(
    room: Optional[str] = None,
    status: Optional[list[str]] = None,
    priority_max: Optional[int] = None,
    due_before: Optional[str] = None,
    limit: int = 50,
) -> str:
    """
    Lists todo items with opinionated defaults.
    status defaults to ['open'] when not provided; pass an explicit list to filter differently,
    e.g. ['open','in_progress','blocked'] or all six statuses to see everything.
    Valid statuses: open, in_progress, blocked, done, cancelled, deferred.
    priority_max: only return items with priority <= this value (1=critical only, 5=all).
    due_before: only return items due on or before this ISO date (YYYY-MM-DD).
    room: optional — omit to search across all rooms.
    Results are ordered by priority ASC, due_date ASC (nulls last), created_on ASC.
    """
    try:
        statuses = status if status is not None else ["open"]
        if statuses:
            invalid = set(statuses) - _VALID_STATUSES
            if invalid:
                return json.dumps({"error": f"Invalid status values: {sorted(invalid)}"})
        if priority_max is not None and priority_max not in range(1, 6):
            return json.dumps({"error": "priority_max must be between 1 and 5"})

        canonical_room = await _resolve_room(room) if room else None
        if room and not canonical_room:
            return json.dumps({"error": f"Room not found: {room}"})

        params: list = []
        if canonical_room:
            params.append(canonical_room)
        params.extend(statuses)
        if priority_max is not None:
            params.append(priority_max)
        if due_before:
            params.append(due_before)
        params.append(limit)

        todos = await db.query(
            render("todos_list.sql", room=canonical_room, statuses=statuses,
                   priority_max=priority_max, due_before=due_before),
            params,
        )
        return json.dumps({"count": len(todos), "todos": todos})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_get_todo(todo_id: int) -> str:
    """
    Returns a single todo item by its integer id.
    """
    try:
        todo = await db.query_one(render("todo_get.sql"), (todo_id,))
        if todo is None:
            return json.dumps({"error": f"Todo not found: {todo_id}"})
        return json.dumps(todo)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_update_todo(
    todo_id: int,
    title: Optional[str] = None,
    detail: Optional[str] = None,
    priority: Optional[int] = None,
    due_date: Optional[str] = None,
    status: Optional[str] = None,
    entry_id: Optional[str] = None,
) -> str:
    """
    Updates any combination of fields on a todo. Only provided fields are changed.
    status must be one of: open, in_progress, blocked, done, cancelled, deferred.
    priority must be 1–5.

    Before marking status='done': if this todo has a linked entry_id, first call
    citadel_update_entry to record the outcome — what was decided, built, or learned.
    The entry absorbs the knowledge permanently; the todo then becomes a historical
    record of when the work was completed and recedes from the active view.
    """
    try:
        if status is not None and status not in _VALID_STATUSES:
            return json.dumps({"error": f"Invalid status: {status}. Must be one of: {sorted(_VALID_STATUSES)}"})
        if priority is not None and priority not in range(1, 6):
            return json.dumps({"error": "priority must be between 1 and 5"})

        existing = await db.query_one(render("todo_exists.sql"), (todo_id,))
        if not existing:
            return json.dumps({"error": f"Todo not found: {todo_id}"})

        fields: list[str] = []
        values: list = []
        if title is not None:
            fields.append("title = ?"); values.append(title)
        if detail is not None:
            fields.append("detail = ?"); values.append(detail)
        if priority is not None:
            fields.append("priority = ?"); values.append(priority)
        if due_date is not None:
            fields.append("due_date = ?"); values.append(due_date)
        if status is not None:
            fields.append("status = ?"); values.append(status)
        if entry_id is not None:
            fields.append("entry_id = ?"); values.append(entry_id)

        if not fields:
            return json.dumps({"status": "no_changes"})

        now = _now()
        values.extend([now, todo_id])
        await db.execute(render("todo_update.sql", fields=fields), values)
        return json.dumps({"status": "updated", "id": todo_id})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def citadel_delete_todo(todo_id: int) -> str:
    """
    Permanently deletes a todo item.
    This is irreversible — use citadel_update_todo with status='cancelled' to soft-delete.
    """
    try:
        existing = await db.query_one(render("todo_exists.sql"), (todo_id,))
        if not existing:
            return json.dumps({"error": f"Todo not found: {todo_id}"})
        await db.execute(render("todo_delete.sql"), (todo_id,))
        return json.dumps({"status": "deleted", "id": todo_id})
    except Exception as e:
        return json.dumps({"error": str(e)})
