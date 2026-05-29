---
name: get_todos
description: Lists todo items with optional filters. Defaults to open todos only. Results ordered by priority ASC, due_date ASC (nulls last), created_on ASC unless sort_by is specified.
transaction: false
parameters:
  room:
    type: string
    required: false
    description: Filter to a specific room (omit for all rooms)
  status:
    type: string
    required: false
    description: "Filter by status: open, in_progress, blocked, done, cancelled, deferred. Omit for open only."
  priority_max:
    type: integer
    required: false
    description: Only return todos with priority <= this value (1=critical only, 5=all)
  due_before:
    type: string
    required: false
    description: Only return todos due on or before this ISO date YYYY-MM-DD
  limit:
    type: integer
    required: false
    default: 50
    description: Maximum number of results
  sort_by:
    type: string
    required: false
    description: "Column to sort by: created_on, updated_on, completed_on, priority, room. Omit for default priority/due_date/created_on ordering."
  sort_order:
    type: string
    required: false
    default: asc
    description: "Sort direction: asc or desc. Defaults to asc."
returns: List of todos with all fields
examples:
  - room: my-project
  - status: in_progress
  - priority_max: 2
    due_before: "2026-06-01"
  - sort_by: created_on
    sort_order: desc
  - sort_by: updated_on
    sort_order: desc
---
SELECT id, room, title, detail, priority, due_date, status, entry_id, completed_on, created_on, updated_on
FROM todos
WHERE 1=1
{% if room is not none %}
AND room = '{{ room }}'
{% endif %}
{% if status is not none %}
AND status = '{{ status }}'
{% else %}
AND status = 'open'
{% endif %}
{% if priority_max is not none %}
AND priority <= {{ priority_max }}
{% endif %}
{% if due_before is not none %}
AND due_date <= '{{ due_before }}'
{% endif %}
{% if sort_by is not none %}
ORDER BY
{% if sort_by == 'updated_on' %}updated_on
{% elif sort_by == 'completed_on' %}completed_on
{% elif sort_by == 'room' %}room
{% elif sort_by == 'created_on' %}created_on
{% else %}priority
{% endif %}
{% if sort_order == 'desc' %}DESC{% else %}ASC{% endif %} NULLS LAST
{% else %}
ORDER BY priority ASC, due_date ASC NULLS LAST, created_on ASC
{% endif %}
LIMIT {{ limit or 50 }}
