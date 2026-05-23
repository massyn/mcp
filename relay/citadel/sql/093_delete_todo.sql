---
name: delete_todo
description: Permanently deletes a todo item. Irreversible — use update_todo with status='cancelled' to soft-delete.
transaction: false
parameters:
  todo_id:
    type: integer
    required: true
    description: Integer id of the todo to delete
returns: rows_affected=1 on success, 0 if not found
examples:
  - todo_id: 42
---
DELETE FROM todos WHERE id = {{ todo_id }}
