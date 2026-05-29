---
name: search
description: Full-text search across entry title, summary, and detail using FTS5. Multiple words are AND-matched. Use trailing * for prefix matching e.g. "pyth*" matches "python".
transaction: false
parameters:
  query:
    type: string
    required: true
    description: FTS5 search query. Multiple words = AND. Prefix match with *. Example "auth login"
  room:
    type: string
    required: false
    description: Limit search to a specific room
  status:
    type: string
    required: false
    description: Filter by entry status — active, archived, deprecated. Defaults to active.
  limit:
    type: integer
    required: false
    default: 20
    description: Maximum number of results
returns: Matched entries with id, room, title, summary, tags, status, updated_on ordered by relevance
examples:
  - query: authentication
  - query: "flask deploy*"
    room: my-project
---
SELECT e.id, e.room, e.title, e.summary, e.tags, e.status, e.updated_on
FROM entries_fts
JOIN entries e ON entries_fts.rowid = e.rowid
WHERE entries_fts MATCH '{{ query }}'
{% if status is not none %}
AND e.status = '{{ status }}'
{% else %}
AND e.status = 'active'
{% endif %}
{% if room is not none %}
AND e.room = '{{ room }}'
{% endif %}
ORDER BY rank
LIMIT {{ limit or 20 }}
