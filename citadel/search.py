"""Search MCP tool — uses FTS5 for ranked full-text search."""

import json
from typing import Optional

from helpers import _resolve_room
from server import db, mcp
from sql import render


def _to_fts_query(query: str) -> str:
    """Convert a plain search string to an FTS5 prefix-match expression."""
    terms = query.strip().split()
    return " ".join(f"{t}*" for t in terms if t)


@mcp.tool()
async def citadel_search(
    query: str,
    room: Optional[str] = None,
    tags: Optional[list[str]] = None,
    status: Optional[str] = "active",
    limit: int = 20,
) -> str:
    """
    Full-text search across title + summary + detail using FTS5 ranked search.
    Results are ordered by relevance. Each term is matched as a prefix (e.g. 'pyth'
    matches 'python'). Multiple words are treated as AND (both must appear).
    Optionally scoped to a room or filtered by tags.
    status defaults to 'active'; pass null to search all statuses.
    limit caps the number of results returned (default 20).
    Returns summary-level results (no detail field).
    """
    try:
        if not query.strip():
            return json.dumps({"error": "Query must not be empty"})
        if status and status not in ("active", "archived", "deprecated"):
            return json.dumps({"error": f"Invalid status: {status}"})

        fts_query = _to_fts_query(query)
        canonical_room = await _resolve_room(room) if room else None

        params: list = [fts_query]
        if status:
            params.append(status)
        if canonical_room:
            params.append(canonical_room)
        params.append(limit)

        results = await db.query(
            render("search_entries.sql", status=status, room=canonical_room),
            params,
        )

        if tags:
            tag_set = set(tags)
            results = [r for r in results if tag_set.intersection(json.loads(r["tags"]))]

        for r in results:
            r["tags"] = json.loads(r["tags"])

        return json.dumps({"query": query, "count": len(results), "results": results})
    except Exception as e:
        return json.dumps({"error": str(e)})
