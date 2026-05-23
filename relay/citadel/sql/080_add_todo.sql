---
name: add_todo
description: Creates a new todo item linked to a room. Auto-creates the room if it does not exist. Returns the new todo id.
transaction: true
parameters:
  room:
    type: string
    required: true
    description: Room name the todo belongs to
  title:
    type: string
    required: true
    description: Short actionable title for the todo
  detail:
    type: string
    required: false
    description: Full description — write as a self-contained prompt if another agent will pick this up
  priority:
    type: integer
    required: false
    default: 3
    description: Priority 1 (critical) to 5 (nice-to-have), default 3
  due_date:
    type: string
    required: false
    description: ISO date string YYYY-MM-DD
  entry_id:
    type: string
    required: false
    description: UUID of a knowledge entry that provides context for this todo
returns: Integer id of the created todo
examples:
  - room: my-project
    title: Fix the login redirect bug
    priority: 2
    due_date: "2026-06-01"
---
INSERT OR IGNORE INTO rooms (name, aliases, tags, created_on, updated_on)
VALUES ('{{ room }}', '[]', '[]', '{{ now() }}', '{{ now() }}')
---
INSERT INTO todos (room, title, detail, priority, due_date, status, entry_id, completed_on, created_on, updated_on)
VALUES (
  '{{ room }}',
  '{{ title }}',
  {% if detail is not none %}'{{ detail }}'{% else %}NULL{% endif %},
  {{ priority or 3 }},
  {% if due_date is not none %}'{{ due_date }}'{% else %}NULL{% endif %},
  'open',
  {% if entry_id is not none %}'{{ entry_id }}'{% else %}NULL{% endif %},
  NULL,
  '{{ now() }}',
  '{{ now() }}'
)
RETURNING id, room
