---
name: get_todos
description: Lists todo items with optional filters. Defaults to open todos only. Results ordered by priority ASC, due_date ASC (nulls last), created_on ASC.
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
returns: List of todos with all fields
examples:
  - room: my-project
  - status: in_progress
  - priority_max: 2
    due_before: "2026-06-01"
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
ORDER BY priority ASC, due_date ASC NULLS LAST, created_on ASC
LIMIT {{ limit or 50 }}
