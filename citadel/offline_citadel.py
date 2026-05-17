"""Generate a static HTML snapshot of the Citadel knowledge base."""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import markdown as md_lib
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape

from db import build_db

# ---------------------------------------------------------------------------
# Configuration — mirrors citadel_mcp.py
# ---------------------------------------------------------------------------

load_dotenv(Path(__file__).parent / ".env")

_db_env = os.environ.get("DB_PATH")
_db_path = (
    Path(_db_env).expanduser().resolve()
    if _db_env
    else Path.home() / ".citadel" / "citadel.db"
)

_md = md_lib.Markdown(extensions=["extra", "nl2br"])


def _render_md(text: str) -> str:
    _md.reset()
    return _md.convert(text or "")


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


async def fetch_data() -> tuple[list[dict], list[dict]]:
    db = build_db(
        db_path=_db_path,
        turso_url=os.environ.get("TURSO_URL"),
        turso_token=os.environ.get("TURSO_TOKEN"),
    )
    try:
        rooms = await db.query(
            "SELECT name, tags, created_on, updated_on FROM rooms ORDER BY name"
        )
        for room in rooms:
            room["tags"] = json.loads(room["tags"] or "[]")
            entries = await db.query(
                "SELECT id, title, summary, detail, tags, status, created_on, updated_on "
                "FROM entries WHERE room = ? ORDER BY updated_on DESC",
                (room["name"],),
            )
            for entry in entries:
                entry["tags"] = json.loads(entry["tags"] or "[]")
                entry["detail_html"] = _render_md(entry["detail"])
            room["entries"] = entries

        try:
            todos = await db.query(
                "SELECT id, room, title, detail, priority, due_date, status, entry_id "
                "FROM todos "
                "WHERE status NOT IN ('done', 'cancelled') "
                "ORDER BY priority ASC, due_date ASC, created_on ASC"
            )
        except Exception:
            todos = []
    finally:
        await db.close()
    return rooms, todos


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a static HTML snapshot of the Citadel knowledge base."
    )
    parser.add_argument(
        "--template",
        default=str(Path(__file__).parent / "templates" / "citadel.html.j2"),
        help="Path to the Jinja2 template file (default: templates/citadel.html.j2)",
    )
    parser.add_argument(
        "--output",
        default="citadel.html",
        help="Output HTML file path (default: citadel.html)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    template_path = Path(args.template)
    if not template_path.exists():
        print(f"Error: template not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    rooms, todos = asyncio.run(fetch_data())
    total_entries = sum(len(r["entries"]) for r in rooms)

    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(template_path.name)

    rendered = template.render(
        rooms=rooms,
        todos=todos,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        total_rooms=len(rooms),
        total_entries=total_entries,
        total_todos=len(todos),
    )

    output_path = Path(args.output)
    output_path.write_text(rendered, encoding="utf-8")
    print(
        f"Written to {output_path} "
        f"({len(rooms)} rooms, {total_entries} entries, {len(todos)} open todos)"
    )


if __name__ == "__main__":
    main()
