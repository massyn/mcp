"""Data access layer for the Citadel Viewer — MCP HTTP client."""

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

_here = Path(__file__).parent
load_dotenv(_here.parent / ".env")
load_dotenv(_here / ".env", override=True)

_log = logging.getLogger("citadel_viewer.data")

_ENDPOINT = os.environ["CITADEL_MCP_ENDPOINT"]
_TOKEN = os.environ["CITADEL_TOKEN"]

_session_lock = threading.Lock()
_session_initialized = False
_session_id: str | None = None
_req_lock = threading.Lock()
_req_id = 0

# Kept for get_entry (full detail) only — everything else uses the mirror.
_CACHE_TTL = int(os.environ.get("CITADEL_CACHE_TTL", "300"))
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_MISSING = object()


def _cache_get(key: str) -> Any:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is not None and time.monotonic() - entry[0] < _CACHE_TTL:
            return entry[1]
        return _MISSING


def _cache_set(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)


def _next_id() -> int:
    global _req_id
    with _req_lock:
        _req_id += 1
        return _req_id


def _base_headers(session_id: str | None = None) -> dict:
    h = {
        "Authorization": f"Bearer {_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        h["Mcp-Session-Id"] = session_id
    return h


def _parse_response(resp: requests.Response) -> dict | None:
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                data_str = line[5:].strip()
                if data_str and data_str != "[DONE]":
                    try:
                        return json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
        return None
    return resp.json()


def _reset_session() -> None:
    global _session_initialized, _session_id
    with _session_lock:
        _log.info("Resetting MCP session (will re-initialise on next call)")
        _session_initialized = False
        _session_id = None


def _ensure_session() -> str | None:
    global _session_initialized, _session_id
    with _session_lock:
        if _session_initialized:
            return _session_id
        try:
            resp = requests.post(
                _ENDPOINT,
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "citadel-viewer", "version": "1.0"},
                    },
                    "id": 0,
                },
                headers=_base_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            _session_id = resp.headers.get("Mcp-Session-Id")
            requests.post(
                _ENDPOINT,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=_base_headers(_session_id),
                timeout=10,
            )
            _session_initialized = True
            _log.info("MCP session established: %s", _session_id or "(stateless)")
        except Exception as exc:
            _log.error("Failed to initialise MCP session: %s", exc)
        return _session_id


def _call(tool: str, **arguments) -> list | dict | None:
    for attempt in range(2):
        session_id = _ensure_session()
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool,
                "arguments": {k: v for k, v in arguments.items() if v is not None},
            },
            "id": _next_id(),
        }
        try:
            resp = requests.post(
                _ENDPOINT,
                json=payload,
                headers=_base_headers(session_id),
                timeout=30,
            )
            if resp.status_code in (400, 404, 410):
                _log.warning("Session rejected (%s) on %s — resetting", resp.status_code, tool)
                _reset_session()
                continue
            resp.raise_for_status()
        except requests.ConnectionError as exc:
            _log.error("Connection error calling %s: %s", tool, exc)
            _reset_session()
            continue
        except requests.RequestException as exc:
            _log.error("HTTP error calling %s: %s", tool, exc)
            return None

        body = _parse_response(resp)
        if body is None:
            _log.error("Empty response from %s", tool)
            return None
        if "error" in body:
            _log.error("MCP error calling %s: %s", tool, body["error"])
            return None

        content = body.get("result", {}).get("content", [])
        for block in content:
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except (json.JSONDecodeError, TypeError):
                    _log.warning("Non-JSON text from %s", tool)
                    return None
        return None

    _log.error("Gave up calling %s after retries", tool)
    return None


def _parse_tags(raw) -> list:
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return []


def _ts_to_local_date(ts: str) -> str:
    """Convert a UTC ISO timestamp to a local date string using the system timezone."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().date().isoformat()
    except (ValueError, OverflowError):
        return ts[:10]


# ---------------------------------------------------------------------------
# In-memory mirror cache
# ---------------------------------------------------------------------------

_SYNC_TODOS_INTERVAL = int(os.environ.get("VIEWER_TODO_SYNC", "30"))
_SYNC_ENTRIES_INTERVAL = int(os.environ.get("VIEWER_ENTRY_SYNC", "300"))
_ALL_TODO_STATUSES = ("open", "in_progress", "blocked", "done", "cancelled", "deferred")


class _MirrorCache:
    """
    Warm in-memory mirror of all todos and active entries.

    On startup: full load via MCP.
    Every VIEWER_TODO_SYNC seconds (default 30): delta sync todos via updated_after.
    Every VIEWER_ENTRY_SYNC seconds (default 300): delta sync entries via updated_after.
    After any write: todos are invalidated so the next request picks up the change.
    """

    def __init__(self) -> None:
        self._todos: dict[int, dict] = {}
        self._entries: dict[str, dict] = {}   # summary-level only; keyed by entry id
        self._rooms: list[dict] = []
        self._last_todo_sync: str | None = None
        self._last_entry_sync: str | None = None
        self._todo_ts: float = 0.0
        self._entry_ts: float = 0.0
        self._lock = threading.Lock()
        self.ready = False

    @staticmethod
    def _utcnow() -> str:
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    def warm_up(self) -> None:
        _log.info("Mirror cache: warming up...")
        try:
            self._full_sync_todos()
            self._full_sync_entries()
            self.ready = True
            _log.info("Mirror cache: ready — %d todos, %d entries",
                      len(self._todos), len(self._entries))
        except Exception:
            _log.exception("Mirror cache: warm-up failed; live MCP calls will be used instead")

    def _full_sync_todos(self) -> None:
        todos: dict[int, dict] = {}
        for s in _ALL_TODO_STATUSES:
            rows = _call("get_todos", status=s, limit=2000) or []
            if isinstance(rows, list):
                for r in rows:
                    todos[r["id"]] = r
        self._todos = todos
        self._last_todo_sync = self._utcnow()
        self._todo_ts = time.monotonic()

    def _full_sync_entries(self) -> None:
        rooms_raw = _call("get_manifest") or []
        if not isinstance(rooms_raw, list):
            return
        rooms = sorted(rooms_raw, key=lambda r: r["name"].lower())
        entries: dict[str, dict] = {}
        for room_info in rooms:
            room_name = room_info["name"]
            rows = _call("get_room", room=room_name, status="active", limit=500) or []
            if isinstance(rows, list):
                for r in rows:
                    e = dict(r)
                    e.pop("total_count", None)
                    e["tags"] = _parse_tags(e.get("tags"))
                    e.setdefault("room", room_name)
                    entries[e["id"]] = e
        self._entries = entries
        self._rooms = rooms
        self._last_entry_sync = self._utcnow()
        self._entry_ts = time.monotonic()

    def _delta_sync_todos(self) -> None:
        since = self._last_todo_sync
        new_sync = self._utcnow()
        changed = 0
        for s in _ALL_TODO_STATUSES:
            rows = _call("get_todos", status=s, limit=500, updated_after=since) or []
            if isinstance(rows, list):
                for r in rows:
                    self._todos[r["id"]] = r
                    changed += 1
        self._last_todo_sync = new_sync
        self._todo_ts = time.monotonic()
        if changed:
            _log.info("Mirror cache: todo delta — %d changed", changed)

    def _delta_sync_entries(self) -> None:
        since = self._last_entry_sync
        new_sync = self._utcnow()
        rooms_raw = _call("get_manifest") or []
        if isinstance(rooms_raw, list):
            self._rooms = sorted(rooms_raw, key=lambda r: r["name"].lower())
            changed = 0
            for room_info in self._rooms:
                room_name = room_info["name"]
                rows = _call("get_room", room=room_name, status="active",
                             limit=500, updated_after=since) or []
                if isinstance(rows, list):
                    for r in rows:
                        e = dict(r)
                        e.pop("total_count", None)
                        e["tags"] = _parse_tags(e.get("tags"))
                        e.setdefault("room", room_name)
                        self._entries[e["id"]] = e
                        changed += 1
            if changed:
                _log.info("Mirror cache: entry delta — %d changed", changed)
        self._last_entry_sync = new_sync
        self._entry_ts = time.monotonic()

    def refresh_if_stale(self) -> None:
        if not self.ready:
            return
        now = time.monotonic()
        todo_stale = now - self._todo_ts >= _SYNC_TODOS_INTERVAL
        entry_stale = now - self._entry_ts >= _SYNC_ENTRIES_INTERVAL
        if not todo_stale and not entry_stale:
            return
        if not self._lock.acquire(blocking=False):
            return  # another thread is already syncing
        try:
            now = time.monotonic()
            if now - self._todo_ts >= _SYNC_TODOS_INTERVAL:
                self._delta_sync_todos()
            if now - self._entry_ts >= _SYNC_ENTRIES_INTERVAL:
                self._delta_sync_entries()
        except Exception:
            _log.exception("Mirror cache: refresh failed")
        finally:
            self._lock.release()

    def invalidate_todos(self) -> None:
        """Force a todo sync on the next request — call after any write."""
        self._todo_ts = 0.0

    # --- Query helpers ---

    def get_manifest(self) -> dict:
        return {"rooms": list(self._rooms)}

    def get_todos(
        self,
        room: Optional[str] = None,
        status_filter: Optional[list] = None,
        priority_max: Optional[int] = None,
        priority_min: Optional[int] = None,
        limit: int = 100,
    ) -> list[dict]:
        todos = list(self._todos.values())
        if room:
            todos = [t for t in todos if t.get("room") == room]
        if status_filter:
            allowed = set(status_filter)
            todos = [t for t in todos if t.get("status") in allowed]
        if priority_max is not None:
            todos = [t for t in todos if t.get("priority", 3) <= priority_max]
        if priority_min is not None:
            todos = [t for t in todos if t.get("priority", 3) >= priority_min]
        todos.sort(key=lambda t: (
            t.get("priority", 3),
            t.get("due_date") or "9999-99-99",
            t.get("created_on") or "",
        ))
        return todos[:limit]

    def all_todos(self) -> list[dict]:
        return list(self._todos.values())

    def get_entries(
        self,
        room: Optional[str] = None,
        status: str = "active",
        limit: int = 25,
        offset: int = 0,
        tag: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        entries = list(self._entries.values())
        if room:
            entries = [e for e in entries if e.get("room") == room]
        if status:
            entries = [e for e in entries if e.get("status") == status]
        if tag:
            entries = [e for e in entries if tag in e.get("tags", [])]
        entries.sort(key=lambda e: e.get("updated_on") or "", reverse=True)
        total = len(entries)
        return entries[offset:offset + limit], total

    def get_tags(self, status: str = "active") -> list[tuple[str, int]]:
        tag_counts: dict[str, int] = {}
        for e in self._entries.values():
            if e.get("status") == status:
                for tag in e.get("tags", []):
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
        return sorted(tag_counts.items())


_mirror = _MirrorCache()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_schema() -> None:
    _mirror.warm_up()


def refresh_mirror() -> None:
    _mirror.refresh_if_stale()


def get_manifest(tags: Optional[list] = None) -> dict:
    if _mirror.ready:
        return _mirror.get_manifest()
    rows = _call("get_manifest") or []
    return {"rooms": sorted(rows, key=lambda r: r["name"].lower()) if isinstance(rows, list) else []}


def get_room(room: str, status: str = "active", limit: int = 50, offset: int = 0) -> dict:
    """Direct MCP fetch for a single room — used by get_entry fallback and non-active entry views."""
    key = f"room:{room}:{status}:{limit}:{offset}"
    cached = _cache_get(key)
    if cached is not _MISSING:
        return cached
    rows = _call("get_room", room=room, status=status, limit=limit, offset=offset) or []
    if not isinstance(rows, list):
        return {"error": f"room not found: {room}"}
    if not rows:
        manifest = get_manifest()
        if not any(r["name"] == room for r in manifest.get("rooms", [])):
            return {"error": f"room not found: {room}"}
    total = rows[0]["total_count"] if rows else 0
    entries = []
    for r in rows:
        e = dict(r)
        e.pop("total_count", None)
        e["tags"] = _parse_tags(e.get("tags"))
        e.setdefault("room", room)
        entries.append(e)
    result = {"entries": entries, "total": total, "offset": offset, "limit": limit}
    _cache_set(key, result)
    return result


def get_entry(entry_id: str, room: Optional[str] = None) -> dict:
    key = f"entry:{entry_id}:{room}"
    cached = _cache_get(key)
    if cached is not _MISSING:
        return cached
    args: dict = {"entry_id": entry_id}
    if room:
        args["room"] = room
    rows = _call("get_entry", **args) or []
    if not isinstance(rows, list) or not rows:
        return {"error": "entry not found"}
    entry = dict(rows[0])
    entry["tags"] = _parse_tags(entry.get("tags"))
    _cache_set(key, entry)
    return entry


def get_todos(
    room: Optional[str] = None,
    status: Optional[list] = None,
    priority_max: Optional[int] = None,
    priority_min: Optional[int] = None,
    limit: int = 100,
) -> dict:
    if _mirror.ready:
        return {"todos": _mirror.get_todos(
            room=room,
            status_filter=status,
            priority_max=priority_max,
            priority_min=priority_min,
            limit=limit,
        )}
    # fallback: live MCP
    statuses = status or ["open"]
    all_todos: list[dict] = []
    seen_ids: set = set()
    per_status_limit = max(limit, 200)
    for s in statuses:
        args: dict = {"status": s, "limit": per_status_limit}
        if room:
            args["room"] = room
        if priority_max is not None:
            args["priority_max"] = priority_max
        rows = _call("get_todos", **args) or []
        if isinstance(rows, list):
            for r in rows:
                if r["id"] not in seen_ids:
                    if priority_min is not None and r.get("priority", 3) < priority_min:
                        continue
                    seen_ids.add(r["id"])
                    all_todos.append(r)
    all_todos.sort(key=lambda t: (
        t.get("priority", 3),
        t.get("due_date") or "9999-99-99",
        t.get("created_on") or "",
    ))
    return {"todos": all_todos[:limit]}


def add_todo(
    room: str,
    title: str,
    detail: Optional[str] = None,
    priority: int = 3,
    due_date: Optional[str] = None,
) -> dict:
    args: dict = {"room": room, "title": title, "priority": priority}
    if detail:
        args["detail"] = detail
    if due_date:
        args["due_date"] = due_date
    result = _call("add_todo", **args)
    _mirror.invalidate_todos()
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
    room: Optional[str] = None,
) -> dict:
    args: dict = {"todo_id": todo_id}
    if title is not None:
        args["title"] = title
    if detail is not None:
        args["detail"] = detail
    if priority is not None:
        args["priority"] = priority
    if due_date is not None:
        args["due_date"] = due_date
    if status is not None:
        args["status"] = status
    if room is not None:
        args["room"] = room
    result = _call("update_todo", **args) or {}
    _mirror.invalidate_todos()
    return result


def search(query: str, room: Optional[str] = None, status: str = "active", limit: int = 20) -> dict:
    args: dict = {"query": query, "status": status, "limit": limit}
    if room:
        args["room"] = room
    rows = _call("search", **args) or []
    if isinstance(rows, list):
        for r in rows:
            r["tags"] = _parse_tags(r.get("tags"))
    return {"results": rows if isinstance(rows, list) else []}


def get_tags(status: str = "active") -> list[tuple[str, int]]:
    if _mirror.ready:
        return _mirror.get_tags(status=status)
    manifest = get_manifest()
    tag_counts: dict[str, int] = {}
    for room_info in manifest.get("rooms", []):
        result = get_room(room_info["name"], status=status, limit=200)
        for entry in result.get("entries", []):
            for tag in entry.get("tags", []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return sorted(tag_counts.items())


def get_burnup_data(room: Optional[str] = None, days: int = 14) -> dict:
    from datetime import date, timedelta

    today = date.today()
    start = today - timedelta(days=days - 1)
    date_series = [(start + timedelta(days=i)).isoformat() for i in range(days)]

    _burnup_statuses = frozenset(("open", "in_progress", "blocked", "done"))
    if _mirror.ready:
        all_todos = [t for t in _mirror.all_todos() if t.get("status") in _burnup_statuses]
        if room:
            all_todos = [t for t in all_todos if t.get("room") == room]
    else:
        all_todos = []
        for s in ("open", "in_progress", "blocked", "done"):
            args: dict = {"status": s, "limit": 1000}
            if room:
                args["room"] = room
            rows = _call("get_todos", **args) or []
            if isinstance(rows, list):
                all_todos.extend(rows)

    open_series: list[int] = []
    closed_series: list[int] = []
    created_series: list[int] = []
    for day in date_series:
        open_count = 0
        closed_count = 0
        created_count = 0
        for t in all_todos:
            created = _ts_to_local_date(t.get("created_on") or "")
            completed = _ts_to_local_date(t.get("completed_on") or "")
            if not created or created > day:
                continue
            if created == day:
                created_count += 1
            if completed and completed <= day:
                if completed == day:
                    closed_count += 1
            else:
                open_count += 1
        open_series.append(open_count)
        closed_series.append(closed_count)
        created_series.append(created_count)

    return {"dates": date_series, "open": open_series, "closed": closed_series, "created": created_series}


def get_open_heatmap(room: Optional[str] = None, statuses: tuple = ("open", "in_progress", "blocked")) -> dict:
    priorities = [1, 2, 3, 4, 5]
    rooms_seen: list[str] = []
    matrix: dict[str, dict[int, int]] = {}

    if _mirror.ready:
        source = [
            t for t in _mirror.all_todos()
            if t.get("status") in statuses and (not room or t.get("room") == room)
        ]
    else:
        source = []
        for s in statuses:
            args: dict = {"status": s, "limit": 500}
            if room:
                args["room"] = room
            rows = _call("get_todos", **args) or []
            if isinstance(rows, list):
                source.extend(rows)

    for t in source:
        room_name = t.get("room", "")
        priority = t.get("priority", 3)
        if not room_name:
            continue
        if room_name not in rooms_seen:
            rooms_seen.append(room_name)
            matrix[room_name] = {p: 0 for p in priorities}
        matrix[room_name][priority] = matrix[room_name].get(priority, 0) + 1

    all_ns = [matrix[rm][p] for rm in rooms_seen for p in priorities]
    max_val = max(all_ns, default=1) or 1
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


def get_all_entries(
    status: str = "active",
    limit: int = 25,
    offset: int = 0,
    room: Optional[str] = None,
    tag: Optional[str] = None,
) -> dict:
    if _mirror.ready and status == "active":
        page, total = _mirror.get_entries(room=room, status=status,
                                           limit=limit, offset=offset, tag=tag)
        return {"entries": page, "total": total, "offset": offset, "limit": limit}
    # fallback: live MCP (also handles non-active status views)
    if tag:
        return get_entries_by_tag(tag, status=status, limit=limit, offset=offset)
    if room:
        return get_room(room, status=status, limit=limit, offset=offset)
    manifest = get_manifest()
    all_entries: list[dict] = []
    for room_info in manifest.get("rooms", []):
        result = get_room(room_info["name"], status=status, limit=500)
        all_entries.extend(result.get("entries", []))
    all_entries.sort(key=lambda e: e.get("updated_on") or "", reverse=True)
    total = len(all_entries)
    return {
        "entries": all_entries[offset : offset + limit],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def get_entries_by_tag(tag: str, status: str = "active", limit: int = 50, offset: int = 0) -> dict:
    if _mirror.ready and status == "active":
        page, total = _mirror.get_entries(status=status, limit=limit, offset=offset, tag=tag)
        return {"tag": tag, "total": total, "limit": limit, "offset": offset, "entries": page}
    manifest = get_manifest()
    matched: list[dict] = []
    for room_info in manifest.get("rooms", []):
        room_name = room_info["name"]
        result = get_room(room_name, status=status, limit=200)
        for entry in result.get("entries", []):
            if tag in entry.get("tags", []):
                entry.setdefault("room", room_name)
                matched.append(entry)
    matched.sort(key=lambda e: e.get("updated_on") or "", reverse=True)
    total = len(matched)
    return {"tag": tag, "total": total, "limit": limit, "offset": offset,
            "entries": matched[offset:offset + limit]}
