---
name: get_todos_view
description: Lists todos with multi-status filter support. Accepts a JSON array of status strings.
transaction: false
parameters:
  room:
    type: string
    required: false
    description: Filter to a specific room
  status_json:
    type: string
    required: false
    description: "JSON array of statuses e.g. [\"open\",\"in_progress\"]. Omit for open only."
  priority_max:
    type: integer
    required: false
    description: Only return todos with priority <= this value
  limit:
    type: integer
    required: false
    default: 100
    description: Maximum number of results
---
SELECT id, room, title, detail, priority, due_date, status, entry_id, completed_on, created_on, updated_on
FROM todos
WHERE 1=1
{% if room is not none %}
AND room = '{{ room }}'
{% endif %}
{% if status_json is not none %}
AND status IN (SELECT value FROM json_each('{{ status_json }}'))
{% else %}
AND status = 'open'
{% endif %}
{% if priority_max is not none %}
AND priority <= {{ priority_max }}
{% endif %}
ORDER BY priority ASC, due_date ASC NULLS LAST, created_on ASC
LIMIT {{ limit or 100 }}
