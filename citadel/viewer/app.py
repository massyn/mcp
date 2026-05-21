"""Citadel Viewer — read-only Flask web UI."""

import logging
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, render_template, request

_here = Path(__file__).parent

# Load parent .env first as base, then local .env overrides
load_dotenv(_here.parent / ".env")
load_dotenv(_here / ".env", override=True)

# Strip ANSI escape codes from all output.
# Werkzeug's startup banner is printed via click.secho() which writes directly
# to stderr and ignores logging configuration and NO_COLOR when stdout is a TTY.
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

import data  # noqa: E402 — must follow sys.path setup in data.py

app = Flask(__name__)

with app.app_context():
    data.init_schema()


def _index_ctx(**kwargs) -> dict:
    """Base context for all index.html renders — rooms + tags for the sidebar."""
    manifest = data.get_manifest()
    return dict(rooms=manifest.get("rooms", []), tags=data.get_tags(), **kwargs)


@app.route("/")
def index():
    return render_template("index.html", **_index_ctx())


@app.route("/room/<room_name>")
def room_view(room_name: str):
    status = request.args.get("status", "active")
    offset = int(request.args.get("offset", 0))
    result = data.get_room(room_name, status=status, limit=50, offset=offset)
    if "error" in result:
        abort(404)
    if request.headers.get("HX-Request"):
        return render_template("_entries.html", room=room_name, result=result, status=status)
    return render_template(
        "index.html",
        **_index_ctx(
            active_room=room_name,
            entries_room=room_name,
            entries_result=result,
            entries_status=status,
        ),
    )


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
    offset = int(request.args.get("offset", 0))
    result = data.get_entries_by_tag(tag_name, status=status, limit=50, offset=offset)
    if request.headers.get("HX-Request"):
        return render_template("_tag_entries.html", tag=tag_name, result=result, status=status)
    return render_template(
        "index.html",
        **_index_ctx(active_tag=tag_name, tag_result=result, tag_status=status),
    )


@app.route("/todos")
def todos_view():
    room = request.args.get("room") or None
    status_filter = request.args.getlist("status") or ["open", "in_progress", "blocked"]
    priority_max = request.args.get("priority_max", type=int)
    result = data.get_todos(room=room, status=status_filter, priority_max=priority_max)
    todos = result.get("todos", [])
    room_counts: dict[str, int] = {}
    for t in todos:
        room_counts[t["room"]] = room_counts.get(t["room"], 0) + 1
    todo_rooms = sorted(room_counts.items())
    ctx = dict(
        todos=todos,
        todo_rooms=todo_rooms,
        selected_room=room,
        status_filter=status_filter,
        priority_max=priority_max,
    )
    if request.headers.get("HX-Request"):
        return render_template("_todos_content.html", **ctx)
    return render_template("todos.html", **ctx)


@app.route("/velocity")
def velocity_view():
    velocity = data.get_velocity_data()
    return render_template("velocity.html", **_index_ctx(velocity=velocity))


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
