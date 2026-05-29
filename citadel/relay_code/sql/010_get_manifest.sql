---
name: get_manifest
description: Returns all rooms with entry counts, sorted by most recently updated. Call this at the start of every conversation to orient on what knowledge exists.
transaction: false
parameters: {}
returns: List of rooms with name, aliases, tags, entry_count, updated_on
---
SELECT r.name, r.aliases, r.tags, r.updated_on, COUNT(e.id) AS entry_count
FROM rooms r
LEFT JOIN entries e ON e.room = r.name
GROUP BY r.name
ORDER BY r.updated_on DESC
