---
name: add_room
description: Creates a new room. Returns the room name if created, or nothing if it already exists (INSERT OR IGNORE).
transaction: false
parameters:
  name:
    type: string
    required: true
    description: Room name — use lowercase hyphenated slug e.g. my-project
  tags:
    type: string
    required: false
    default: "[]"
    description: JSON array of tags e.g. ["project","active"]
returns: Room name of the created room, or empty if already exists
examples:
  - name: my-project
    tags: '["project"]'
---
INSERT OR IGNORE INTO rooms (name, aliases, tags, created_on, updated_on)
VALUES ('{{ name }}', '[]', '{{ tags or "[]" }}', '{{ now() }}', '{{ now() }}')
RETURNING name
