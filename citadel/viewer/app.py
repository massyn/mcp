"""Citadel Viewer — read-only Flask web UI."""

import logging
import os
import re
import sys
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template, request, url_for

_here = Path(__file__).parent

load_dotenv(_here / ".env")

# Strip ANSI escape codes from all output.
_ANSI = re.compile(r'\x1b\[[0-9;]*[mGKHFABCDJsu]')

class _AnsiStripper:
    def __init__(self, stream):
        self._s = stream
    def write(self, text):
        self._s.write(_ANSI.sub('', text))
    def flush(self):
        self._s.flush()
    def __getattr__(self, name):
        return getattr(self._s, name)

sys.stdout = _AnsiStripper(sys.stdout)
sys.stderr = _AnsiStripper(sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

import data

app = Flask(__name__)

with app.app_context():
    data.init_schema()


def _index_ctx(**kwargs) -> dict:
    """Base context for all index.html renders — rooms for the sidebar."""
    manifest = data.get_manifest()
    return dict(rooms=manifest.get("rooms", []), **kwargs)


def _page_range(current: int, total: int, window: int = 2) -> list:
    """Page numbers with ellipsis for large ranges."""
    if total <= 1:
        return [1] if total == 1 else []
    pages: list = []
    for p in range(1, total + 1):
        if p == 1 or p == total or abs(p - current) <= window:
            pages.append(p)
        elif not pages or pages[-1] != "...":
            pages.append("...")
    return pages


@app.route("/")
def index():
    return redirect(url_for("entries_view"))


@app.route("/entries")
def entries_view():
    status = request.args.get("status", "active")
    room = request.args.get("room") or None
    tag = request.args.get("tag") or None
    q = request.args.get("q", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 25
    offset = (page - 1) * per_page

    if q:
        search_result = data.search(q, room=room, status=status, limit=50)
        entries = search_result.get("results", [])
        result = {"entries": entries, "total": len(entries), "offset": 0, "limit": 50}
        total_pages = 1
    else:
        result = data.get_all_entries(status=status, limit=per_page, offset=offset, room=room, tag=tag)
        total = result.get("total", 0)
        total_pages = max(1, (total + per_page - 1) // per_page)

    page_range = _page_range(page, total_pages)

    fparams: dict = {}
    if room:
        fparams["room"] = room
    if tag:
        fparams["tag"] = tag
    if status != "active":
        fparams["status"] = status
    if q:
        fparams["q"] = q
    filter_qs = urllib.parse.urlencode(fparams)

    manifest = data.get_manifest()
    all_rooms = [r["name"] for r in manifest.get("rooms", [])]
    filter_tags = data.get_tags(status=status)

    ctx = _index_ctx(
        active_room=room,
        entries_result=result,
        entries_status=status,
        entries_room=room,
        entries_tag=tag,
        entries_q=q,
        entries_page=page,
        entries_total_pages=total_pages,
        entries_page_range=page_range,
        entries_per_page=per_page,
        entries_filter_qs=filter_qs,
        all_rooms=all_rooms,
        filter_tags=filter_tags,
    )
    if request.headers.get("HX-Request"):
        return render_template("_entries.html", **ctx)
    return render_template("index.html", **ctx)


@app.route("/room/<room_name>")
def room_view(room_name: str):
    status = request.args.get("status", "active")
    page = request.args.get("page", 1, type=int)
    return redirect(url_for("entries_view", room=room_name, status=status, page=page))


@app.route("/entry/<entry_id>")
def entry_view(entry_id: str):
    room = request.args.get("room") or None
    entry = data.get_entry(entry_id, room=room)
    if "error" in entry:
        abort(404)
    if request.headers.get("HX-Request"):
        return render_template("_entry.html", entry=entry)
    return render_template(
        "index.html",
        **_index_ctx(active_room=entry.get("room"), entry=entry),
    )


@app.route("/tag/<tag_name>")
def tag_view(tag_name: str):
    status = request.args.get("status", "active")
    return redirect(url_for("entries_view", tag=tag_name, status=status))


@app.route("/todos")
def todos_view():
    room = request.args.get("room") or None
    status_filter = request.args.getlist("status") or ["open", "in_progress", "blocked"]
    priority_max = request.args.get("priority_max", type=int)
    priority_min = request.args.get("priority_min", type=int)
    result = data.get_todos(room=room, status=status_filter, priority_max=priority_max, priority_min=priority_min)
    todos = result.get("todos", [])
    room_counts: dict[str, int] = {}
    for t in todos:
        room_counts[t["room"]] = room_counts.get(t["room"], 0) + 1
    todo_rooms = sorted(room_counts.items())
    manifest = data.get_manifest()
    all_rooms = [r["name"] for r in manifest.get("rooms", [])]
    ctx = dict(
        todos=todos,
        todo_rooms=todo_rooms,
        selected_room=room,
        status_filter=status_filter,
        priority_max=priority_max,
        priority_min=priority_min,
        all_rooms=all_rooms,
    )
    if request.headers.get("HX-Request"):
        return render_template("_todos_content.html", **ctx)
    return render_template("todos.html", **ctx)


@app.route("/todos/add", methods=["POST"])
def todo_add():
    room = request.form.get("room", "").strip()
    title = request.form.get("title", "").strip()
    detail = request.form.get("detail", "").strip() or None
    priority = int(request.form.get("priority", 3))
    due_date = request.form.get("due_date", "").strip() or None
    data.add_todo(room=room, title=title, detail=detail, priority=priority, due_date=due_date)
    return redirect(url_for("todos_view"))


@app.route("/todos/<int:todo_id>/update", methods=["POST"])
def todo_update(todo_id: int):
    title = request.form.get("title", "").strip()
    detail = request.form.get("detail", "").strip() or None
    priority = int(request.form.get("priority", 3))
    due_date = request.form.get("due_date", "").strip() or None
    status = request.form.get("status", "").strip() or None
    room = request.form.get("room", "").strip() or None
    data.update_todo(
        todo_id=todo_id, title=title, detail=detail,
        priority=priority, due_date=due_date, status=status, room=room,
    )
    return redirect(url_for("todos_view"))


@app.route("/velocity")
def velocity_view():
    room = request.args.get("room") or None
    days = request.args.get("days", 14, type=int)
    if days not in (14, 30, 90, 365):
        days = 14
    burnup = data.get_burnup_data(room=room, days=days)
    heatmap = data.get_open_heatmap(room=room)
    deferred_heatmap = data.get_open_heatmap(room=room, statuses=("deferred",))
    return render_template(
        "velocity.html",
        **_index_ctx(burnup=burnup, heatmap=heatmap, deferred_heatmap=deferred_heatmap, selected_room=room, selected_days=days),
    )


@app.route("/search")
def search_view():
    query = request.args.get("q", "").strip()
    room = request.args.get("room") or None
    if not query:
        return render_template("_search_results.html", results=[], query="")
    result = data.search(query, room=room)
    return render_template(
        "_search_results.html",
        results=result.get("results", []),
        query=query,
        error=result.get("error"),
    )


if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT") or os.environ.get("PORT") or 5000)
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
