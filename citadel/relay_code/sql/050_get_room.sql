---
name: get_room
description: Returns entries in a room at summary level (no detail field). Supports pagination and status filtering.
transaction: false
parameters:
  room:
    type: string
    required: true
    description: Room name to list entries from
  status:
    type: string
    required: false
    default: active
    description: Filter by status — active, archived, or deprecated
  limit:
    type: integer
    required: false
    default: 50
    description: Maximum number of entries to return
  offset:
    type: integer
    required: false
    default: 0
    description: Number of entries to skip (for pagination)
  updated_after:
    type: string
    required: false
    description: "Only return entries updated after this ISO datetime (e.g. 2026-06-04T10:00:00Z). Use for incremental sync."
returns: Entries with id, title, summary, tags, status, updated_on, plus total_count for pagination
examples:
  - room: my-project
  - room: my-project
    status: archived
    limit: 20
    offset: 20
  - room: my-project
    updated_after: "2026-06-04T10:00:00Z"
---
SELECT id, title, summary, tags, status, updated_on,
       COUNT(*) OVER() AS total_count
FROM entries
WHERE room = '{{ room }}' AND status = '{{ status or "active" }}'
{% if updated_after is not none %}
AND updated_on > '{{ updated_after }}'
{% endif %}
ORDER BY updated_on DESC
LIMIT {{ limit or 50 }} OFFSET {{ offset or 0 }}
