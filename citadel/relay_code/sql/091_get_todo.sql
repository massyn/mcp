---
name: get_todo
description: Returns a single todo item by its integer id.
transaction: false
parameters:
  todo_id:
    type: integer
    required: true
    description: Integer id of the todo
returns: Full todo with all fields, or empty if not found
examples:
  - todo_id: 42
---
SELECT id, room, title, detail, priority, due_date, status, entry_id, completed_on, created_on, updated_on
FROM todos
WHERE id = {{ todo_id }}
