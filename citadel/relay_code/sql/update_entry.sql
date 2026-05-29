---
name: update_entry
description: Updates one or more fields on an existing entry. Only provided fields are changed; updated_on is always refreshed.
transaction: false
parameters:
  room:
    type: string
    required: true
    description: Room the entry belongs to
  entry_id:
    type: string
    required: true
    description: UUID of the entry to update
  title:
    type: string
    required: false
    description: New title (omit to leave unchanged)
  summary:
    type: string
    required: false
    description: New summary (omit to leave unchanged)
  detail:
    type: string
    required: false
    description: New detail content in Markdown (omit to leave unchanged)
  status:
    type: string
    required: false
    description: New status — active, archived, or deprecated
  tags:
    type: string
    required: false
    description: New JSON tag array e.g. ["tag1","tag2"] (omit to leave unchanged)
returns: Confirmation with updated entry id, or rows_affected=0 if not found
examples:
  - room: myproject
    entry_id: 550e8400-e29b-41d4-a716-446655440000
    summary: Updated summary text.
---
UPDATE entries SET
  updated_on = '{{ now() }}'
{% if title is not none %}
  , title = '{{ title }}'
{% endif %}
{% if summary is not none %}
  , summary = '{{ summary }}'
{% endif %}
{% if detail is not none %}
  , detail = '{{ detail }}'
{% endif %}
{% if status is not none %}
  , status = '{{ status }}'
{% endif %}
{% if tags is not none %}
  , tags = '{{ tags }}'
{% endif %}
WHERE id = '{{ entry_id }}'
AND room = '{{ room }}'
