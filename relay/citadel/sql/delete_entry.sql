---
name: delete_entry
description: Permanently deletes a single entry from a room. Irreversible — use update_entry with status='archived' for soft-delete. Any todos linked to this entry have their entry_id cleared (they are not deleted).
transaction: true
parameters:
  room:
    type: string
    required: true
    description: Room the entry belongs to
  entry_id:
    type: string
    required: true
    description: UUID of the entry to delete
returns: rows_affected=1 on success, rows_affected=0 if entry not found
examples:
  - room: myproject
    entry_id: 550e8400-e29b-41d4-a716-446655440000
---
UPDATE todos SET entry_id = NULL WHERE entry_id = '{{ entry_id }}'
---
DELETE FROM entries
WHERE id = '{{ entry_id }}'
AND room = '{{ room }}'
