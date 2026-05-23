"""Data access layer for the Citadel Viewer — thin wrappers over the relay engine."""

import asyncio
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

_here = Path(__file__).parent
sys.path.insert(0, str(_here.parent / "relay"))

from engine import Engine, build_db  # noqa: E402

_log = logging.getLogger("citadel_viewer.data")

# ---------------------------------------------------------------------------
# Engine setup
# ---------------------------------------------------------------------------

_turso_url = os.environ.get("TURSO_URL")
_db_type = os.environ.get("DB_TYPE", "turso" if _turso_url else "sqlite").lower()
_db_path_env = os.environ.get("DB_PATH")
_db_path = (
    Path(_db_path_env).expanduser().resolve()
    if _db_path_env
    else Path.home() / ".relay" / "relay.db"
)

_db = build_db(_db_type, _db_path, _turso_url, os.environ.get("TURSO_TOKEN"))
_engine = Engine(_db)
_engine.load(_here.parent / "relay" / "citadel" / "sql")
_engine.load(_here / "sql")

# Single persistent event loop — asyncio.run() creates/destroys loops per call,
# which breaks the database layer between requests.
_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True).start()


def _run(coro) -> Any:
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_schema() -> None:
    _run(_engine.run_startup())


def get_manifest(tags: Optional[list] = None) -> dict:
    rows = _run(_engine.execute("get_manifest")) or []
    rooms = sorted(rows, key=lambda r: r["name"].lower())
    return {"rooms": rooms}


def get_room(room: str, status: str = "active", limit: int = 50, offset: int = 0) -> dict:
    rows = _run(_engine.execute("get_room", room=room, status=status, limit=limit, offset=offset)) or []
    if not rows:
        exists = _run(_engine.query(
            "SELECT name FROM rooms WHERE name = '{{ room }}'", room=room
        ))
        if not exists:
            return {"error": f"room not found: {room}"}
    total = rows[0]["total_count"] if rows else 0
    entries = []
    for r in rows:
        e = dict(r)
        e.pop("total_count", None)
        e["tags"] = json.loads(e.get("tags") or "[]")
        entries.append(e)
    return {"entries": entries, "total": total, "offset": offset, "limit": limit}


def get_entry(entry_id: str, room: Optional[str] = None) -> dict:
    rows = _run(_engine.execute("get_entry", entry_id=entry_id, room=room)) or []
    if not rows:
        return {"error": "entry not found"}
    entry = dict(rows[0])
    entry["tags"] = json.loads(entry.get("tags") or "[]")
    return entry


def get_todos(
    room: Optional[str] = None,
    status: Optional[list] = None,
    priority_max: Optional[int] = None,
    limit: int = 100,
) -> dict:
    status_json = json.dumps(status) if status else None
    rows = _run(_engine.execute(
        "get_todos_view",
        room=room,
        status_json=status_json,
        priority_max=priority_max,
        limit=limit,
    )) or []
    return {"todos": rows}


def add_todo(
    room: str,
    title: str,
    detail: Optional[str] = None,
    priority: int = 3,
    due_date: Optional[str] = None,
) -> dict:
    result = _run(_engine.execute(
        "add_todo", room=room, title=title, detail=detail,
        priority=priority, due_date=due_date,
    ))
    if isinstance(result, list):
        return result[0] if result else {}
    return result or {}


def update_todo(
    todo_id: int,
    title: Optional[str] = None,
    detail: Optional[str] = None,
    priority: Optional[int] = None,
    due_date: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    result = _run(_engine.execute(
        "update_todo", todo_id=todo_id, title=title, detail=detail,
        priority=priority, due_date=due_date, status=status,
    ))
    return result or {}


def search(query: str, room: Optional[str] = None, status: str = "active", limit: int = 20) -> dict:
    rows = _run(_engine.execute("search", query=query, room=room, status=status, limit=limit)) or []
    return {"results": rows}


def get_tags(status: str = "active") -> list[tuple[str, int]]:
    rows = _run(_engine.execute("get_tags", status=status)) or []
    return [(r["tag"], r["cnt"]) for r in rows]


def get_velocity_data(room: Optional[str] = None) -> dict:
    rows = _run(_engine.execute("get_velocity", room=room)) or []
    weeks: list[str] = []
    rooms: list[str] = []
    for r in rows:
        if r["week"] not in weeks:
            weeks.append(r["week"])
        if r["room"] not in rooms:
            rooms.append(r["room"])
    rooms.sort()
    counts: dict[str, dict[str, int]] = {rm: {week: 0 for week in weeks} for rm in rooms}
    for r in rows:
        counts[r["room"]][r["week"]] = r["n"]
    return {"weeks": weeks, "rooms": rooms, "counts": counts}


def get_open_heatmap(room: Optional[str] = None) -> dict:
    rows = _run(_engine.execute("get_open_heatmap", room=room)) or []
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
    rows = _run(_engine.execute(
        "get_entries_by_tag", tag=tag, status=status, limit=limit, offset=offset,
    )) or []
    total = rows[0]["total_count"] if rows else 0
    entries = []
    for r in rows:
        e = dict(r)
        e.pop("total_count", None)
        e["tags"] = json.loads(e.get("tags") or "[]")
        entries.append(e)
    return {"tag": tag, "total": total, "limit": limit, "offset": offset, "entries": entries}
