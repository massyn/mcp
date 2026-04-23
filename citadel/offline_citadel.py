"""Generate a static HTML snapshot of the Citadel knowledge base."""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

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

# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


async def fetch_data() -> list[dict]:
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
            room["entries"] = entries
    finally:
        await db.close()
    return rooms


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

    rooms = asyncio.run(fetch_data())

    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(template_path.name)

    rendered = template.render(
        rooms=rooms,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        total_rooms=len(rooms),
        total_entries=sum(len(r["entries"]) for r in rooms),
    )

    output_path = Path(args.output)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"Written to {output_path} ({len(rooms)} rooms, {sum(len(r['entries']) for r in rooms)} entries)")


if __name__ == "__main__":
    main()
