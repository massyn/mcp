---
name: add_entry
description: Creates a new knowledge entry in a room. Auto-creates the room if it does not exist. Returns the new entry id and room.
transaction: true
parameters:
  room:
    type: string
    required: true
    description: Room name — topic container for the entry
  title:
    type: string
    required: true
    description: Short descriptive title
  summary:
    type: string
    required: true
    description: One-paragraph summary of the entry content
  detail:
    type: string
    required: true
    description: Full entry content in Markdown
  tags:
    type: string
    required: false
    default: "[]"
    description: JSON array of tag strings e.g. ["tag1","tag2"]
returns: id and room of the created entry
examples:
  - room: myproject
    title: Decision — use SQLite
    summary: Chose SQLite over Postgres for simplicity.
    detail: Full rationale here.
    tags: '["decision","database"]'
---
INSERT OR IGNORE INTO rooms (name, tags, aliases, created_on, updated_on)
VALUES ('{{ room }}', '[]', '[]', '{{ now() }}', '{{ now() }}')
---
INSERT INTO entries (id, room, title, summary, detail, tags, status, created_on, updated_on)
VALUES ('{{ uuid() }}', '{{ room }}', '{{ title }}', '{{ summary }}', '{{ detail }}', '{{ tags or "[]" }}', 'active', '{{ now() }}', '{{ now() }}')
RETURNING id, room
