"""Data access layer for the Citadel Viewer — MCP HTTP client."""

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

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
            # Send required initialized notification
            notify_headers = _base_headers(_session_id)
            requests.post(
                _ENDPOINT,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=notify_headers,
                timeout=10,
            )
            _session_initialized = True
            _log.info("MCP session established: %s", _session_id or "(stateless)")
        except Exception as exc:
            _log.error("Failed to initialize MCP session: %s", exc)
            _session_initialized = True  # avoid retry loop
        return _session_id


def _call(tool: str, **arguments) -> list | dict | None:
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
        resp.raise_for_status()
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


def _parse_tags(raw) -> list:
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_schema() -> None:
    pass  # Schema is managed by the remote MCP server


def get_manifest(tags: Optional[list] = None) -> dict:
    rows = _call("get_manifest") or []
    if not isinstance(rows, list):
        rows = []
    rooms = sorted(rows, key=lambda r: r["name"].lower())
    return {"rooms": rooms}


def get_room(room: str, status: str = "active", limit: int = 50, offset: int = 0) -> dict:
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
    return {"entries": entries, "total": total, "offset": offset, "limit": limit}


def get_entry(entry_id: str, room: Optional[str] = None) -> dict:
    args: dict = {"entry_id": entry_id}
    if room:
        args["room"] = room
    rows = _call("get_entry", **args) or []
    if not isinstance(rows, list) or not rows:
        return {"error": "entry not found"}
    entry = dict(rows[0])
    entry["tags"] = _parse_tags(entry.get("tags"))
    return entry


def get_todos(
    room: Optional[str] = None,
    status: Optional[list] = None,
    priority_max: Optional[int] = None,
    priority_min: Optional[int] = None,
    limit: int = 100,
) -> dict:
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
    return _call("update_todo", **args) or {}


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

    all_todos: list[dict] = []
    for s in ("open", "in_progress", "blocked", "deferred", "done"):
        args: dict = {"status": s, "limit": 1000}
        if room:
            args["room"] = room
        rows = _call("get_todos", **args) or []
        if isinstance(rows, list):
            all_todos.extend(rows)

    open_series: list[int] = []
    closed_series: list[int] = []
    for day in date_series:
        open_count = 0
        closed_count = 0
        for t in all_todos:
            created = (t.get("created_on") or "")[:10]
            completed = (t.get("completed_on") or "")[:10]
            if not created or created > day:
                continue
            if completed and completed <= day:
                closed_count += 1
            else:
                open_count += 1
        open_series.append(open_count)
        closed_series.append(closed_count)

    return {"dates": date_series, "open": open_series, "closed": closed_series}


def get_open_heatmap(room: Optional[str] = None) -> dict:
    priorities = [1, 2, 3, 4, 5]
    rooms_seen: list[str] = []
    matrix: dict[str, dict[int, int]] = {}

    for s in ("open", "in_progress", "blocked"):
        args: dict = {"status": s, "limit": 500}
        if room:
            args["room"] = room
        rows = _call("get_todos", **args) or []
        if not isinstance(rows, list):
            continue
        for r in rows:
            room_name = r.get("room", "")
            priority = r.get("priority", 3)
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


def get_entries_by_tag(tag: str, status: str = "active", limit: int = 50, offset: int = 0) -> dict:
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
    return {"tag": tag, "total": total, "limit": limit, "offset": offset, "entries": matched[offset:offset + limit]}
