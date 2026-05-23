---
name: delete_room
description: Permanently deletes a room, all its entries, and all its todos. Irreversible.
transaction: true
parameters:
  room:
    type: string
    required: true
    description: Room name to delete
returns: rows_affected=1 if the room was deleted, 0 if not found
examples:
  - room: old-project
---
DELETE FROM todos WHERE room = '{{ room }}'
---
DELETE FROM entries WHERE room = '{{ room }}'
---
DELETE FROM rooms WHERE name = '{{ room }}'
