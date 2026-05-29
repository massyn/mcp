---
name: merge_rooms
description: Merges a source room into a destination room. All entries and todos are moved. The source room is deleted. Note — source aliases are not migrated in this version.
transaction: true
parameters:
  source:
    type: string
    required: true
    description: Room to merge from (will be deleted)
  destination:
    type: string
    required: true
    description: Room to merge into (must already exist)
returns: rows_affected from the source room deletion — 1 on success, 0 if source not found
examples:
  - source: old-room
    destination: new-room
---
UPDATE entries SET room = '{{ destination }}' WHERE room = '{{ source }}'
---
UPDATE todos SET room = '{{ destination }}' WHERE room = '{{ source }}'
---
DELETE FROM rooms WHERE name = '{{ source }}'
