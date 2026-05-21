"""Sync wrappers around async Citadel functions for use in Flask routes."""

import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from entries import citadel_get_entry, citadel_get_room  # noqa: E402
from rooms import citadel_get_manifest  # noqa: E402
from search import citadel_search  # noqa: E402
from server import db  # noqa: E402
from todos import citadel_add_todo, citadel_get_todos, citadel_update_todo  # noqa: E402

# Single persistent event loop running in a daemon thread.
# asyncio.run() opens and closes a loop on every call, which breaks the
# database layer between requests. run_coroutine_threadsafe submits work
# to this loop without ever tearing it down.
_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True).start()


def _run(coro):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()


def init_schema() -> None:
    _run(db.init_schema())


def get_manifest(tags: Optional[list] = None) -> dict:
    result = json.loads(_run(citadel_get_manifest(tags=tags)))
    if "rooms" in result:
        result["rooms"] = sorted(result["rooms"], key=lambda r: r["name"].lower())
    return result


def get_room(room: str, status: str = "active", limit: int = 50, offset: int = 0) -> dict:
    return json.loads(_run(citadel_get_room(room=room, status=status, limit=limit, offset=offset)))


def get_entry(entry_id: str, room: Optional[str] = None) -> dict:
    return json.loads(_run(citadel_get_entry(entry_id=entry_id, room=room)))


def get_todos(
    room: Optional[str] = None,
    status: Optional[list] = None,
    priority_max: Optional[int] = None,
    limit: int = 100,
) -> dict:
    return json.loads(_run(citadel_get_todos(
        room=room, status=status, priority_max=priority_max, limit=limit
    )))


def add_todo(
    room: str,
    title: str,
    detail: Optional[str] = None,
    priority: int = 3,
    due_date: Optional[str] = None,
) -> dict:
    return json.loads(_run(citadel_add_todo(
        room=room, title=title, detail=detail, priority=priority, due_date=due_date
    )))


def update_todo(
    todo_id: int,
    title: Optional[str] = None,
    detail: Optional[str] = None,
    priority: Optional[int] = None,
    due_date: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    return json.loads(_run(citadel_update_todo(
        todo_id=todo_id, title=title, detail=detail,
        priority=priority, due_date=due_date, status=status,
    )))


def search(query: str, room: Optional[str] = None, status: str = "active", limit: int = 20) -> dict:
    return json.loads(_run(citadel_search(query=query, room=room, status=status, limit=limit)))


def get_tags(status: str = "active") -> list[tuple[str, int]]:
    rows = _run(db.query(
        "SELECT json_each.value AS tag, COUNT(*) AS cnt "
        "FROM entries, json_each(entries.tags) "
        "WHERE entries.status = ? "
        "GROUP BY json_each.value ORDER BY json_each.value",
        (status,),
    ))
    return [(r["tag"], r["cnt"]) for r in rows]


def get_velocity_data(room: Optional[str] = None) -> dict:
    if room:
        rows = _run(db.query(
            "SELECT strftime('%Y-W%W', completed_on) AS week, room, COUNT(*) AS n "
            "FROM todos "
            "WHERE status = 'done' AND completed_on IS NOT NULL AND room = ? "
            "GROUP BY week, room ORDER BY week, room",
            (room,),
        ))
    else:
        rows = _run(db.query(
            "SELECT strftime('%Y-W%W', completed_on) AS week, room, COUNT(*) AS n "
            "FROM todos "
            "WHERE status = 'done' AND completed_on IS NOT NULL "
            "GROUP BY week, room ORDER BY week, room"
        ))
    weeks: list[str] = []
    rooms: list[str] = []
    for r in rows:
        if r["week"] not in weeks:
            weeks.append(r["week"])
        if r["room"] not in rooms:
            rooms.append(r["room"])
    rooms.sort()

    counts: dict[str, dict[str, int]] = {room: {week: 0 for week in weeks} for room in rooms}
    for r in rows:
        counts[r["room"]][r["week"]] = r["n"]

    return {"weeks": weeks, "rooms": rooms, "counts": counts}


def get_open_heatmap(room: Optional[str] = None) -> dict:
    params_room = (room,) if room else ()
    where_room = "AND room = ?" if room else ""

    rows = _run(db.query(
        f"SELECT room, priority, COUNT(*) AS n FROM todos "
        f"WHERE status IN ('open','in_progress','blocked') {where_room} "
        f"GROUP BY room, priority ORDER BY room, priority",
        params_room,
    ))

    priorities = [1, 2, 3, 4, 5]
    rooms_seen: list[str] = []
    matrix: dict[str, dict[int, int]] = {}
    for r in rows:
        if r["room"] not in rooms_seen:
            rooms_seen.append(r["room"])
            matrix[r["room"]] = {p: 0 for p in priorities}
        matrix[r["room"]][r["priority"]] = r["n"]

    max_val = max((r["n"] for r in rows), default=1)
    col_totals = {p: sum(matrix[rm].get(p, 0) for rm in rooms_seen) for p in priorities}
    row_totals = {rm: sum(matrix[rm].values()) for rm in rooms_seen}
    grand_total = sum(row_totals.values())
    return {
        "rooms": rooms_seen,
        "priorities": priorities,
        "matrix": matrix,
        "max_val": max_val,
        "col_totals": col_totals,
        "row_totals": row_totals,
        "grand_total": grand_total,
    }


def get_entries_by_tag(tag: str, status: str = "active", limit: int = 50, offset: int = 0) -> dict:
    count_row = _run(db.query_one(
        "SELECT COUNT(DISTINCT e.id) AS n "
        "FROM entries e, json_each(e.tags) "
        "WHERE json_each.value = ? AND e.status = ?",
        (tag, status),
    ))
    total = count_row["n"] if count_row else 0
    entries = _run(db.query(
        "SELECT DISTINCT e.id, e.room, e.title, e.summary, e.tags, e.status, e.updated_on "
        "FROM entries e, json_each(e.tags) "
        "WHERE json_each.value = ? AND e.status = ? "
        "ORDER BY e.updated_on DESC LIMIT ? OFFSET ?",
        (tag, status, limit, offset),
    ))
    for e in entries:
        e["tags"] = json.loads(e["tags"])
    return {"tag": tag, "total": total, "limit": limit, "offset": offset, "entries": entries}
