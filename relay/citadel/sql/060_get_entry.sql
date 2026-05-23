---
name: get_entry
description: Returns the full entry including the detail field.
transaction: false
parameters:
  entry_id:
    type: string
    required: true
    description: UUID of the entry
  room:
    type: string
    required: false
    description: Optional room name to narrow the lookup
returns: Full entry with id, room, title, summary, detail, tags, status, created_on, updated_on
examples:
  - entry_id: 550e8400-e29b-41d4-a716-446655440000
---
SELECT id, room, title, summary, detail, tags, status, created_on, updated_on
FROM entries
WHERE id = '{{ entry_id }}'
{% if room is not none %}
AND room = '{{ room }}'
{% endif %}
