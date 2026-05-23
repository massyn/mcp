---
name: get_tags
description: Returns all tags with their entry counts, filtered by entry status.
transaction: false
parameters:
  status:
    type: string
    required: false
    default: active
    description: Entry status to filter by — active, archived, or deprecated
---
SELECT json_each.value AS tag, COUNT(*) AS cnt
FROM entries, json_each(entries.tags)
WHERE entries.status = '{{ status or "active" }}'
GROUP BY json_each.value ORDER BY json_each.value
