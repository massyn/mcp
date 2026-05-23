---
name: rename_room
description: Renames a room. All entries and todos are re-pointed automatically. The old name is stored as an alias on the new room.
transaction: true
parameters:
  room:
    type: string
    required: true
    description: Current room name
  new_name:
    type: string
    required: true
    description: New room name — use lowercase hyphenated slug
returns: New room name on success, or error if source room does not exist
examples:
  - room: old-name
    new_name: new-name
---
INSERT INTO rooms (name, aliases, tags, created_on, updated_on)
SELECT '{{ new_name }}', json_array('{{ room }}'), tags, created_on, '{{ now() }}'
FROM rooms
WHERE name = '{{ room }}'
---
UPDATE entries SET room = '{{ new_name }}' WHERE room = '{{ room }}'
---
UPDATE todos SET room = '{{ new_name }}' WHERE room = '{{ room }}'
---
DELETE FROM rooms WHERE name = '{{ room }}'
RETURNING '{{ new_name }}' AS name
