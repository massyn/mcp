"""Shared utilities used across tool modules."""

import re
from datetime import datetime, timezone

from server import db
from sql import render


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slugify(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


async def _resolve_room(name: str) -> str | None:
    """Return the canonical room name for a given name or alias, or None if not found."""
    slug = _slugify(name)
    row = await db.query_one(render("room_resolve_name.sql"), (slug,))
    if row:
        return row["name"]
    row = await db.query_one(render("room_resolve_alias.sql"), (f'%"{slug}"%',))
    return row["name"] if row else None
