---
name: get_entries_by_tag
description: Returns paginated entries matching a tag, with total_count for pagination.
transaction: false
parameters:
  tag:
    type: string
    required: true
    description: Tag value to filter by
  status:
    type: string
    required: false
    default: active
    description: Entry status — active, archived, or deprecated
  limit:
    type: integer
    required: false
    default: 50
    description: Maximum number of results
  offset:
    type: integer
    required: false
    default: 0
    description: Number of results to skip for pagination
---
WITH filtered AS (
  SELECT DISTINCT e.id, e.room, e.title, e.summary, e.tags, e.status, e.updated_on
  FROM entries e, json_each(e.tags)
  WHERE json_each.value = '{{ tag }}' AND e.status = '{{ status or "active" }}'
),
counted AS (
  SELECT *, COUNT(*) OVER() AS total_count FROM filtered
)
SELECT * FROM counted
ORDER BY updated_on DESC
LIMIT {{ limit or 50 }} OFFSET {{ offset or 0 }}
