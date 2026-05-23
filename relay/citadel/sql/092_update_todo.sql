---
name: update_todo
description: Updates any combination of fields on a todo. Only provided fields are changed. Sets completed_on automatically when status becomes 'done'.
transaction: false
parameters:
  todo_id:
    type: integer
    required: true
    description: Integer id of the todo to update
  title:
    type: string
    required: false
    description: New title
  detail:
    type: string
    required: false
    description: New detail content
  priority:
    type: integer
    required: false
    description: New priority 1-5
  due_date:
    type: string
    required: false
    description: New due date YYYY-MM-DD
  status:
    type: string
    required: false
    description: "New status: open, in_progress, blocked, done, cancelled, deferred"
  entry_id:
    type: string
    required: false
    description: Link to a knowledge entry UUID
returns: rows_affected=1 on success, 0 if todo not found
examples:
  - todo_id: 42
    status: in_progress
  - todo_id: 42
    status: done
---
UPDATE todos SET
  updated_on = '{{ now() }}'
{% if title is not none %}
  , title = '{{ title }}'
{% endif %}
{% if detail is not none %}
  , detail = '{{ detail }}'
{% endif %}
{% if priority is not none %}
  , priority = {{ priority }}
{% endif %}
{% if due_date is not none %}
  , due_date = '{{ due_date }}'
{% endif %}
{% if status is not none %}
  , status = '{{ status }}'
{% endif %}
{% if status == 'done' %}
  , completed_on = COALESCE(completed_on, '{{ now() }}')
{% endif %}
{% if entry_id is not none %}
  , entry_id = '{{ entry_id }}'
{% endif %}
WHERE id = {{ todo_id }}
