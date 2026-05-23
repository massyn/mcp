---
name: update_room_tags
description: Updates the tags on a room. Replaces the tag list entirely.
transaction: false
parameters:
  room:
    type: string
    required: true
    description: Room name to update
  tags:
    type: string
    required: true
    description: JSON array of tags e.g. ["project","active"] — replaces existing tags
returns: rows_affected=1 on success, 0 if room not found
examples:
  - room: my-project
    tags: '["project","paused"]'
---
UPDATE rooms SET tags = '{{ tags }}', updated_on = '{{ now() }}' WHERE name = '{{ room }}'
