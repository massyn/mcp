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
from todos import citadel_get_todos  # noqa: E402

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
    return json.loads(_run(citadel_get_manifest(tags=tags)))


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
