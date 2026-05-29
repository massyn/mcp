---
name: move_entry
description: Moves an entry from one room to another. Auto-creates the destination room if it does not exist.
transaction: true
parameters:
  entry_id:
    type: string
    required: true
    description: UUID of the entry to move
  from_room:
    type: string
    required: true
    description: Current room name
  to_room:
    type: string
    required: true
    description: Destination room name
returns: rows_affected=1 on success
examples:
  - entry_id: 550e8400-e29b-41d4-a716-446655440000
    from_room: inbox
    to_room: my-project
---
INSERT OR IGNORE INTO rooms (name, aliases, tags, created_on, updated_on)
VALUES ('{{ to_room }}', '[]', '[]', '{{ now() }}', '{{ now() }}')
---
UPDATE entries
SET room = '{{ to_room }}', updated_on = '{{ now() }}'
WHERE id = '{{ entry_id }}' AND room = '{{ from_room }}'
